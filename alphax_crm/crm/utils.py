"""Shared helpers for AlphaX CRM Automation."""

import frappe

SETTINGS_DT = "AlphaX CRM Settings"


def get_settings():
    """Return the cached AlphaX CRM Settings single doc."""
    return frappe.get_cached_doc(SETTINGS_DT)


def is_enabled(flag):
    """Return truthy value of a boolean field on the settings single."""
    try:
        return bool(get_settings().get(flag))
    except Exception:
        return False


def log_error(title, message=None):
    """Thin wrapper so all module errors land under one searchable title."""
    frappe.log_error(message=message or frappe.get_traceback(), title=f"AlphaX CRM: {title}")


def ai_request_headers(settings, api_key=None, cf_access_client_id=None):
    """Headers for a call to the configured AI endpoint — shared by api/ai.py,
    api/ai_query.py and api/ai_setup.py's connection test, so the three
    places that talk to the AI server never drift apart on auth handling.

    Two independent, stackable auth layers:
      - Authorization: Bearer <ai_api_key> — for an API-key-protected
        endpoint (an OpenAI-compatible gateway, say).
      - CF-Access-Client-Id / CF-Access-Client-Secret — Cloudflare Access
        Service Token headers, for an Ollama instance sitting behind a named
        Cloudflare Tunnel that's locked down with a Cloudflare Access
        "service auth" policy (see AlphaX CRM Settings > AI Assist > Secure
        Remote Access). This is what lets the CRM reach a model hosted on a
        private laptop/network without that endpoint being a bare, unauthenticated
        public URL. Cloudflare validates these headers at its edge, before
        the request ever reaches the tunnel — a request without them (or
        with the wrong values) never reaches Ollama at all.

    api_key/cf_access_client_id let a caller (the connection-tester) try an
    unsaved value before hitting Save; the secret always comes from the
    saved settings, since Password fields are never sent from the browser.
    """
    headers = {"Content-Type": "application/json"}

    key = api_key if api_key is not None else (settings.get_password("ai_api_key") if settings.ai_api_key else None)
    if key:
        headers["Authorization"] = f"Bearer {key}"

    client_id = cf_access_client_id if cf_access_client_id is not None else settings.ai_cf_access_client_id
    client_secret = settings.get_password("ai_cf_access_client_secret") if settings.ai_cf_access_client_secret else None
    if client_id and client_secret:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret

    return headers


def active_lead_workflow_field():
    """The workflow_state_field of whichever Workflow is currently active
    for Lead, or None if there isn't one. Cached per-request via
    frappe.local since this is a database-only fact that can't change
    mid-request, and multiple call sites (PreLead conversion, Lead
    transition logging) need it.
    """
    if not hasattr(frappe.local, "_alphax_active_lead_wf_field"):
        frappe.local._alphax_active_lead_wf_field = frappe.db.get_value(
            "Workflow", {"document_type": "Lead", "is_active": 1}, "workflow_state_field"
        )
    return frappe.local._alphax_active_lead_wf_field
