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

    # Record status change as activity.
    if settings.get("activity_monitor_enabled", 1) and settings.get("capture_status_change", 1):
        before = doc.get_doc_before_save()
        if before and before.get("status") != doc.get("status") and doc.get("status"):
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
            except Exception:
                log_error("prospect convert")
    elif behavior == BEHAVIOR_FOLLOWUP:
        try:
            _ensure_followup(doc)
        except Exception:
            log_error("prospect followup")


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

    # Enter the review workflow.
    review_required = settings.get("prospect_review_required", 1)
    if meta.has_field("alphax_review_status"):
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
        if meta.has_field("alphax_review_status"):
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
