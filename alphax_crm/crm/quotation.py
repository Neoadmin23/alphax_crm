"""Quotation close handling and explicit repair for older Lead stages."""

import frappe

from alphax_crm.crm.utils import get_settings, log_error


def on_submit(doc, method=None):
    """Approver notification now lives in crm/workflow.py (WF-02/WF-03): email + in-app,
    business hours, de-duplicated and logged. Kept as a no-op for hook compatibility."""
    return


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
    if doc.docstatus != 1:
        return
    # Only step in once the deal itself is off — a normal submit that
    # advances the pipeline SHOULD set Lead Stage to "Quotation"; that's
    # core working as intended, not the bug being guarded against here.
    # Only a quotation marked Lost ends the deal. A cancelled quotation is usually being
    # amended (cancel -> amend -> resubmit), so it must not push the Lead to Lost Quotation.
    deal_is_off = doc.get("status") == "Lost"
    if not deal_is_off:
        return
    if doc.flags.get("alphax_lost_handled"):
        return
    doc.flags.alphax_lost_handled = True
    from alphax_crm.crm.workflow import quotation_marked_lost
    quotation_marked_lost(doc)


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

    # Lost only: a cancelled quotation is normally being amended and must not close the Lead
    candidates = frappe.get_all(
        "Quotation",
        filters=[["docstatus", "=", 1], ["quotation_to", "=", "Lead"], ["party_name", "is", "set"], ["status", "=", "Lost"]],
        fields=["name", "party_name", "status", "docstatus"],
    )

    fixed, skipped = [], 0
    for row in candidates:
        current_stage = frappe.db.get_value("Lead", row.party_name, "status")
        if (current_stage or "").strip().lower() != "quotation":
            skipped += 1
            continue
        doc = frappe.get_doc("Quotation", row.name)
        try:
            from alphax_crm.crm.workflow import quotation_marked_lost
            quotation_marked_lost(doc)
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
