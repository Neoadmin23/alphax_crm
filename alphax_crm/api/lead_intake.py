"""Channel-agnostic lead intake for AlphaX CRM.

Public-ish endpoint that turns inbound payloads (website forms, Meta/Google
lead ads, WhatsApp Business webhooks) into ERPNext Leads with consent tracking.

Secure with a shared token in AlphaX CRM Settings (intake_token). Call as:

    POST /api/method/alphax_crm.api.lead_intake.capture
    Header:  X-AlphaX-Token: <intake_token>
    Body:    {"lead_name": "...", "email_id": "...", "mobile_no": "...",
              "source": "Website", "message": "...", "consent": true,
              "lawful_basis": "Consent"}
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from alphax_crm.crm.utils import get_settings, log_error

# Map common inbound keys to Lead fields.
FIELD_MAP = {
    "name": "lead_name",
    "full_name": "lead_name",
    "lead_name": "lead_name",
    "email": "email_id",
    "email_id": "email_id",
    "phone": "phone",
    "mobile": "mobile_no",
    "mobile_no": "mobile_no",
    "whatsapp": "whatsapp_no",
    "company": "company_name",
    "company_name": "company_name",
    "source": "source",
    "territory": "territory",
    "industry": "industry",
}


@frappe.whitelist(allow_guest=True)
def capture(**kwargs):
    settings = get_settings()

    # ---- auth ----
    token = frappe.get_request_header("X-AlphaX-Token")
    expected = settings.get_password("intake_token", raise_exception=False) if settings.intake_token else None
    if not expected or token != expected:
        frappe.local.response["http_status_code"] = 401
        return {"ok": False, "error": "unauthorized"}

    # Accept JSON body or form kwargs.
    payload = kwargs or {}
    if frappe.request and frappe.request.data:
        try:
            payload = {**payload, **json.loads(frappe.request.data)}
        except Exception:
            pass

    try:
        lead = _build_lead(payload, settings)
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"ok": True, "lead": lead.name, "score": lead.get("alphax_lead_score")}
    except frappe.DuplicateEntryError:
        return {"ok": False, "error": "duplicate"}
    except Exception:
        log_error("intake")
        frappe.local.response["http_status_code"] = 500
        return {"ok": False, "error": "intake_failed"}


def _build_lead(payload, settings):
    lead = frappe.new_doc("Lead")
    lead.source = settings.default_source or "Campaign"

    for key, value in payload.items():
        field = FIELD_MAP.get(key.lower())
        if field and value:
            lead.set(field, value)

    if not lead.lead_name:
        lead.lead_name = payload.get("lead_name") or payload.get("email") or "AlphaX Lead"

    # Consent / lawful basis (PDPL).
    if payload.get("consent"):
        lead.alphax_consent_given = 1
        lead.alphax_consent_datetime = now_datetime()
        lead.alphax_consent_source = payload.get("source") or "Web Intake"
    lead.alphax_lawful_basis = payload.get("lawful_basis") or "Consent"

    # Stash the raw inbound message so the AI layer / reps have context.
    msg = payload.get("message") or payload.get("notes")
    if msg and frappe.get_meta("Lead").has_field("alphax_inbound_message"):
        lead.alphax_inbound_message = msg

    lead.flags.ignore_permissions = True
    lead.flags.alphax_skip_dq = True
    return lead
