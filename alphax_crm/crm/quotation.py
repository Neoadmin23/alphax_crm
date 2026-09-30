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
