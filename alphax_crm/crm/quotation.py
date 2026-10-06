"""Quotation-side hooks for AlphaX CRM.

Quotation is a core ERPNext doctype (Selling module), not one this app owns
— wired via hooks.doc_events, same pattern as Communication/Comment.

Covers the standalone half of WF-02/WF-03 that doesn't depend on a Lead
being linked to the Quotation at all: whoever holds the Approver role
should see quotation activity as it happens, full stop. The fuller
WF-02/03/04 behavior (checking a Quotation exists for a specific Lead,
confirming its creation back to the Lead Owner, tracking its validity) needs
an actual Lead<->Quotation link, which doesn't exist in this app yet —
that's phase 2.
"""

import frappe

from alphax_crm.crm.utils import get_settings, log_error


def on_submit(doc, method=None):
    settings = get_settings()
    if not settings.get("notify_approvers_on_quotation", 1):
        return
    try:
        _notify_approvers(doc, settings)
    except Exception:
        log_error("quotation submit notify")


# ---------------------------------------------------------------------------
# Guard against core's Quotation -> Lead status sync clobbering Lead Stage
# ---------------------------------------------------------------------------
# Core ERPNext's Quotation.update_lead() — called from its own on_submit(),
# on_cancel(), and declare_enquiry_lost() (the "Set as Lost" action) — always
# ends with `frappe.get_doc("Lead", self.party_name).set_status(update=True)`.
# That core method has no concept of this app's Lead Stage values (Lost
# Quotation / Lost with reason / Won / Postponed / ...); it only knows "a
# Quotation exists against this Lead", so it unconditionally forces the
# Lead's status back to the generic "Quotation" stage — even one that was
# just submitted as Lost or cancelled. This is a long-standing core
# limitation (see frappe/erpnext#4956), not anything this app does, and it
# happens via a direct db_set() on the Lead that bypasses this app's own
# Lead validate() hooks entirely — stage_flow.py never even sees it.
#
# Hooked onto every Quotation lifecycle point core calls update_lead() from
# (on_submit, on_cancel) plus on_update/on_update_after_submit to also catch
# declare_enquiry_lost(), which ends with a plain self.save() rather than a
# submit/cancel transition. Idempotent and cheap once the Lead Stage is
# already correct.
def guard_lead_stage(doc, method=None):
    settings = get_settings()
    if not settings.get("guard_quotation_lead_stage", 1):
        return
    if doc.get("quotation_to") != "Lead" or not doc.get("party_name"):
        return
    # Only step in once the deal itself is off — a normal submit that
    # advances the pipeline SHOULD set Lead Stage to "Quotation"; that's
    # core working as intended, not the bug being guarded against here.
    deal_is_off = doc.get("status") == "Lost" or doc.docstatus == 2
    if not deal_is_off:
        return
    try:
        _restore_lead_stage(doc, settings)
    except Exception:
        log_error("guard lead stage after quotation sync")


def _restore_lead_stage(doc, settings):
    if not frappe.db.exists("Lead", doc.party_name):
        return
    meta = frappe.get_meta("Lead")
    if not meta.has_field("status"):
        return
    current_stage = frappe.db.get_value("Lead", doc.party_name, "status")
    # Only correct the specific damage core causes — it only ever forces
    # the Lead to the generic "Quotation" stage, never anything else — so a
    # Lead already sitting on some other value (someone's deliberate manual
    # choice, made after this correction already ran) is left alone.
    if (current_stage or "").strip().lower() != "quotation":
        return

    lost_quotation_stage = (settings.get("lost_quotation_stage_value") or "Lost Quotation").strip()
    if not lost_quotation_stage:
        return

    from alphax_crm.crm.utils import ensure_select_option

    ensure_select_option("Lead", "status", lost_quotation_stage)
    frappe.db.set_value("Lead", doc.party_name, "status", lost_quotation_stage, update_modified=False)

    if meta.has_field("won_or_lost_date") and not frappe.db.get_value("Lead", doc.party_name, "won_or_lost_date"):
        frappe.db.set_value("Lead", doc.party_name, "won_or_lost_date", frappe.utils.nowdate(), update_modified=False)

    lead_doc = frappe.get_doc("Lead", doc.party_name)
    lead_doc.add_comment(
        "Comment",
        text=(
            f"AlphaX: Lead Stage auto-corrected to \"{lost_quotation_stage}\" — linked Quotation "
            f"{doc.name} is Lost/cancelled, and ERPNext had reset Lead Stage back to \"Quotation\"."
        ),
    )


@frappe.whitelist()
def backfill_lead_stage_for_lost_quotations():
    """One-off repair for Leads that got stuck on "Quotation" before
    guard_lead_stage() was turned on (or while it was off) — the guard only
    runs the next time something touches the linked Quotation, so a Lead
    whose Quotation already went Lost/cancelled before then stays wrong
    until someone opens that Quotation again. Scans every Lost or
    cancelled Quotation whose linked Lead is still sitting on "Quotation"
    and re-runs the same correction once.

    Callable from the UI (a System Manager can run it via
    /app/background_jobs or the console) or from a bench console:
        bench --site <site> execute alphax_crm.crm.quotation.backfill_lead_stage_for_lost_quotations
    Safe to run any time — idempotent, and a no-op once nothing is left to
    fix. Ignores the guard_quotation_lead_stage toggle itself: running this
    by hand is a deliberate one-off repair, not the automatic guard, so it
    corrects regardless of whether that toggle happens to be off.
    """
    frappe.only_for("System Manager")
    settings = get_settings()

    candidates = frappe.get_all(
        "Quotation",
        filters=[
            ["quotation_to", "=", "Lead"],
            ["party_name", "is", "set"],
        ],
        or_filters=[["status", "=", "Lost"], ["docstatus", "=", 2]],
        fields=["name", "party_name", "status", "docstatus"],
    )

    fixed, skipped = [], 0
    for row in candidates:
        current_stage = frappe.db.get_value("Lead", row.party_name, "status")
        if (current_stage or "").strip().lower() != "quotation":
            skipped += 1
            continue
        doc = frappe._dict(row)
        try:
            _restore_lead_stage(doc, settings)
            fixed.append({"quotation": row.name, "lead": row.party_name})
        except Exception:
            log_error("backfill lead stage")

    frappe.db.commit()
    return {"fixed": fixed, "already_correct_or_unaffected": skipped}


def approver_users(settings=None):
    """Every enabled user holding the configured Approver role."""
    settings = settings or get_settings()
    role = (settings.get("approver_role") or "Sales Manager").strip()
    if not role:
        return []
    users = frappe.get_all(
        "Has Role",
        filters={"role": role, "parenttype": "User"},
        pluck="parent",
    )
    if not users:
        return []
    return frappe.get_all(
        "User",
        filters={"name": ["in", users], "enabled": 1},
        pluck="name",
    )


def notify_users(users, subject, message, document_type=None, document_name=None):
    for user in users:
        if not user or user == "Administrator":
            continue
        try:
            frappe.get_doc(
                {
                    "doctype": "Notification Log",
                    "subject": subject,
                    "email_content": frappe.utils.markdown(message) if message else None,
                    "for_user": user,
                    "type": "Alert",
                    "document_type": document_type,
                    "document_name": document_name,
                }
            ).insert(ignore_permissions=True)
        except Exception:
            log_error("notify_users")


def _notify_approvers(doc, settings):
    users = approver_users(settings)
    if not users:
        return
    party = doc.get("party_name") or doc.get("customer_name") or doc.get("quotation_to")
    subject = f"AlphaX: Quotation {doc.name} submitted ({party or ''})"
    message = (
        f"{doc.get('owner')} submitted Quotation {doc.name}"
        + (f" for {party}" if party else "")
        + f", amount {doc.get('grand_total')} {doc.get('currency') or ''}."
    )
    notify_users(users, subject, message, "Quotation", doc.name)
