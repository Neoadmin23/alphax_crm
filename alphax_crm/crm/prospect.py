"""Prospect (pre-lead) automation for AlphaX CRM.

Implements the sales process flow:
  Sales person creates Prospect -> contacts customer -> sets a status.
  Each status maps to a behavior (configured in AlphaX Prospect Status):
    * Convert to Lead      -> auto-create a Lead, SAME owner, Pending Review
    * Close (Not Interested)
    * Mark Unreachable
    * Schedule Follow-up   -> ensures a follow-up reminder (ToDo) exists
    * None                 -> no automation

The lead's owner is the prospect owner (no re-assignment required), and the
lead enters the review workflow at "Pending Review".
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from alphax_crm.crm.utils import get_settings, log_error

BEHAVIOR_CONVERT = "Convert to Lead"
BEHAVIOR_CLOSE = "Close (Not Interested)"
BEHAVIOR_UNREACHABLE = "Mark Unreachable"
BEHAVIOR_FOLLOWUP = "Schedule Follow-up"


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def validate(doc, method=None):
    if not doc.get("status"):
        default = frappe.db.get_value("AlphaX Prospect Status", {"is_default": 1}, "name")
        doc.status = default or "New"
    if not doc.get("prospect_owner"):
        doc.prospect_owner = frappe.session.user
    if doc.get("follow_up_notes") and not doc.get("last_contacted_on"):
        doc.last_contacted_on = now_datetime()


# ---------------------------------------------------------------------------
# on_update  (post-save automation)
# ---------------------------------------------------------------------------
def on_update(doc, method=None):
    settings = get_settings()
    before = doc.get_doc_before_save()
    previous_status = before.get("status") if before else None

    # Record status change as activity.
    if settings.get("activity_monitor_enabled", 1) and settings.get("capture_status_change", 1):
        if before and previous_status != doc.get("status") and doc.get("status"):
            try:
                from alphax_crm.crm.activity import record_activity

                record_activity("AlphaX Prospect", doc.name, f"Status \u2192 {doc.status}",
                                frappe.session.user, f"Status changed to {doc.status}")
            except Exception:
                log_error("prospect status activity")

    behavior = frappe.db.get_value("AlphaX Prospect Status", doc.get("status"), "behavior") or "None"

    if behavior == BEHAVIOR_CONVERT:
        if settings.get("prospect_autoconvert", 1) and not doc.get("lead"):
            try:
                _convert_to_lead(doc, settings)
                _clear_conversion_failure(doc)
            except Exception as e:
                log_error("prospect convert")
                _revert_status(doc, previous_status, e)
    elif behavior == BEHAVIOR_FOLLOWUP:
        try:
            _ensure_followup(doc)
        except Exception:
            log_error("prospect followup")


def _revert_status(doc, previous_status, error):
    """Conversion failed after the status change was already committed
    (on_update runs post-save). Left as-is, the Prospect would show a
    status like "Interested" with no Lead behind it and no visible reason
    why — confusing, and easy to miss since the failure was only logged.
    Revert the status itself and record the failure as a persistent flag +
    message on the record (not just a one-time toast) so it stays visible
    on the form, and filterable in the list, until the underlying issue is
    fixed and conversion actually succeeds.
    """
    fallback = (
        previous_status
        or frappe.db.get_value("AlphaX Prospect Status", {"is_default": 1}, "name")
        or "New"
    )
    message = str(error)
    updates = {"conversion_failed": 1, "conversion_error": message}
    if fallback != doc.get("status"):
        updates["status"] = fallback
        doc.status = fallback
    frappe.db.set_value("AlphaX Prospect", doc.name, updates, update_modified=False)
    doc.conversion_failed = 1
    doc.conversion_error = message
    doc.notify_update()
    frappe.msgprint(
        _("Could not convert to Lead, so the status was reverted to {0}.<br>Reason: {1}<br>"
          "This will stay flagged on the record until it converts successfully.").format(
            frappe.bold(fallback), frappe.utils.escape_html(message)
        ),
        title=_("Conversion Failed"),
        indicator="red",
    )


def _clear_conversion_failure(doc):
    if doc.get("conversion_failed"):
        frappe.db.set_value(
            "AlphaX Prospect", doc.name,
            {"conversion_failed": 0, "conversion_error": ""},
            update_modified=False,
        )
        doc.conversion_failed = 0
        doc.conversion_error = ""


def _active_lead_workflow_field():
    """The workflow_state_field of whichever Workflow is currently active
    for Lead, or None if there isn't one. Cached per-request via
    frappe.local since this is a database-only fact that can't change
    mid-request, and both conversion paths call it.
    """
    if not hasattr(frappe.local, "_alphax_active_lead_wf_field"):
        frappe.local._alphax_active_lead_wf_field = frappe.db.get_value(
            "Workflow", {"document_type": "Lead", "is_active": 1}, "workflow_state_field"
        )
    return frappe.local._alphax_active_lead_wf_field


def _convert_to_lead(doc, settings):
    # Optionally route via the Smart Lead data-entry doc (config-driven).
    if (settings.get("prospect_convert_target") == "Smart Lead then Lead"
            and frappe.db.exists("DocType", "AlphaX Smart Lead")):
        _convert_via_smart_lead(doc, settings)
        return

    lead = frappe.new_doc("Lead")
    lead.lead_name = doc.prospect_name
    lead.company_name = doc.get("company_name")
    lead.email_id = doc.get("email_id")
    lead.mobile_no = doc.get("mobile_no")
    lead.phone = doc.get("phone")

    meta = frappe.get_meta("Lead")
    if doc.get("source") and frappe.db.exists("Lead Source", doc.source):
        lead.source = doc.source
    if doc.get("territory") and frappe.db.exists("Territory", doc.territory):
        lead.territory = doc.territory
    if doc.get("industry") and meta.has_field("industry") and frappe.db.exists("Industry Type", doc.industry):
        lead.industry = doc.industry
    if doc.get("city") and meta.has_field("city"):
        lead.city = doc.city
    if doc.get("job_title") and meta.has_field("job_title"):
        lead.job_title = doc.job_title

    # Carry over any accounting dimensions present on both docs.
    try:
        from alphax_crm.setup.install import active_accounting_dimensions

        for fn, _label, _dt in active_accounting_dimensions():
            if doc.get(fn) and meta.has_field(fn):
                lead.set(fn, doc.get(fn))
    except Exception:
        pass

    # Same sales person remains the owner — no re-assignment.
    if doc.get("prospect_owner"):
        lead.lead_owner = doc.prospect_owner

    # Enter the review workflow — but only touch alphax_review_status if
    # that's actually the field the *currently active* Lead workflow
    # governs. It belonged to the now-superseded "AlphaX Lead Review"
    # workflow; force-setting it while a different workflow (e.g. "Lead
    # Approval -CRM", field workflow_state, entry state "Draft") is active
    # trips that workflow's own transition validation ("not allowed from
    # Draft to Pending Review") since "Pending Review" isn't even one of
    # its states. If no active workflow uses this field, leave it alone
    # and let Frappe's own engine put the Lead in the real entry state.
    review_required = settings.get("prospect_review_required", 1)
    if meta.has_field("alphax_review_status") and _active_lead_workflow_field() == "alphax_review_status":
        lead.alphax_review_status = "Pending Review" if review_required else "Approved"
    if meta.has_field("alphax_prospect"):
        lead.alphax_prospect = doc.name

    # Don't let the data-quality gate block automatic creation.
    lead.flags.alphax_skip_dq = True
    lead.flags.ignore_permissions = True
    lead.insert(ignore_permissions=True)

    frappe.db.set_value(
        "AlphaX Prospect", doc.name,
        {"lead": lead.name, "converted": 1},
        update_modified=False,
    )
    doc.db_set("lead", lead.name, update_modified=False)
    doc.db_set("converted", 1, update_modified=False)

    lead.add_comment("Comment", text=_("Created automatically from Prospect {0}.").format(doc.name))
    frappe.msgprint(
        _("Lead {0} created and submitted for review. Owner: {1}.").format(
            frappe.utils.get_link_to_form("Lead", lead.name), doc.get("prospect_owner") or lead.lead_owner
        ),
        alert=True,
    )


def _ensure_followup(doc):
    """Create a follow-up ToDo for the owner if a date is set and none exists."""
    if not doc.get("follow_up_date") or not doc.get("prospect_owner"):
        return
    exists = frappe.db.exists(
        "ToDo",
        {"reference_type": "AlphaX Prospect", "reference_name": doc.name, "status": "Open"},
    )
    if exists:
        return
    todo = frappe.get_doc(
        {
            "doctype": "ToDo",
            "allocated_to": doc.prospect_owner,
            "date": doc.follow_up_date,
            "reference_type": "AlphaX Prospect",
            "reference_name": doc.name,
            "description": _("Follow up with prospect {0} ({1}).").format(doc.prospect_name, doc.name),
            "priority": "Medium",
        }
    )
    todo.flags.ignore_permissions = True
    todo.insert(ignore_permissions=True)


def _convert_via_smart_lead(doc, settings):
    """Prospect -> Smart Lead -> Lead. The Smart Lead's own save maps to the Lead."""
    sl = frappe.new_doc("AlphaX Smart Lead")
    sl.organization = doc.get("company_name") or doc.prospect_name
    sl.contact_name = doc.prospect_name
    sl.email = doc.get("email_id")
    sl.mobile_no = doc.get("mobile_no")
    sl.phone = doc.get("phone")
    sl.job_title = doc.get("job_title")
    if doc.get("source") and frappe.db.exists("Lead Source", doc.source):
        sl.lead_source = doc.source
    if doc.get("territory") and frappe.db.exists("Territory", doc.territory):
        sl.territory = doc.territory
    sl.lead_owner = doc.get("prospect_owner") or frappe.session.user
    sl.status = "Interested"
    sl.flags.ignore_permissions = True
    sl.insert(ignore_permissions=True)

    lead_name = frappe.db.get_value("AlphaX Smart Lead", sl.name, "lead")
    if lead_name:
        meta = frappe.get_meta("Lead")
        updates = {}
        if meta.has_field("alphax_prospect"):
            updates["alphax_prospect"] = doc.name
        if meta.has_field("alphax_review_status") and _active_lead_workflow_field() == "alphax_review_status":
            updates["alphax_review_status"] = "Pending Review" if settings.get("prospect_review_required", 1) else "Approved"
        if updates:
            frappe.db.set_value("Lead", lead_name, updates, update_modified=False)
        frappe.db.set_value("AlphaX Prospect", doc.name,
                            {"lead": lead_name, "converted": 1}, update_modified=False)
        doc.db_set("lead", lead_name, update_modified=False)
        doc.db_set("converted", 1, update_modified=False)
        frappe.msgprint(
            frappe._("Smart Lead {0} created and mapped to Lead {1}.").format(
                sl.name, frappe.utils.get_link_to_form("Lead", lead_name)),
            alert=True)
