"""Opportunity automation for AlphaX CRM."""

import frappe
from frappe.utils import add_days, nowdate

from alphax_crm.crm.utils import get_settings, log_error


def validate(doc, method=None):
    settings = get_settings()
    if not doc.get("alphax_next_activity_date"):
        days = settings.first_followup_days or 1
        doc.alphax_next_activity_date = add_days(nowdate(), days)


def after_insert(doc, method=None):
    settings = get_settings()
    if settings.ai_enabled and settings.ai_summarize_opportunity:
        frappe.enqueue(
            "alphax_crm.api.ai.summarize_opportunity",
            queue="long",
            opportunity=doc.name,
            enqueue_after_commit=True,
        )


@frappe.whitelist()
def refresh_brief(opportunity):
    """On-demand AI brief, callable from a client-side button."""
    settings = get_settings()
    if not (settings.ai_enabled and settings.ai_summarize_opportunity):
        frappe.throw("AI summarization is disabled in AlphaX CRM Settings.")
    from alphax_crm.api.ai import summarize_opportunity

    return summarize_opportunity(opportunity)


# ---------------------------------------------------------------------------
# on_update -> capture status change as activity
# ---------------------------------------------------------------------------
def on_update(doc, method=None):
    settings = get_settings()
    if not settings.get("activity_monitor_enabled", 1) or not settings.get("capture_status_change", 1):
        return
    before = doc.get_doc_before_save()
    if not before or before.get("status") == doc.get("status") or not doc.get("status"):
        return
    try:
        from alphax_crm.crm.activity import record_activity

        record_activity("Opportunity", doc.name, f"Status \u2192 {doc.status}",
                        frappe.session.user, f"Status changed to {doc.status}")
    except Exception:
        log_error("opportunity status activity")
