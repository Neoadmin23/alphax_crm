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


def ensure_select_option(doctype, fieldname, value, clear_cache=True):
    """Make sure `value` is an allowed option on a Select field, adding it
    via a Property Setter (the exact mechanism Customize Form itself uses)
    if it isn't already one. No-ops if the field already allows it.

    Why this exists: AlphaX CRM Settings lets an admin freely define
    mappings whose target is a Select field on a core doctype — most
    notably Lead Stage Map, which drives what value automation writes into
    Lead's native `status` field. A value typed into that mapping is not
    automatically a legal option on `status` — Frappe's own Select
    validation (BaseDocument._validate_selects) rejects anything not
    already listed, with a "<Field> cannot be "<value>". It should be one
    of ..." error. Before this helper existed, the shipped default mapping
    (seed_lead_stage_map) introduced stage names — "Qualified lead",
    "Postponed", "Contract Under Signing", "Won", "Lost with reason" — that
    were never added to `status`'s option list anywhere, so choosing any of
    them blocked the save for every user, with no clear cause in the error
    text. Calling this whenever such a mapping is defined or used closes
    that gap for good, for this mapping and any future one — the point of
    making these mappings admin-configurable in the first place is that a
    newly typed value should just work, not require a separate manual
    Customize Form step nobody remembers to do.

    Returns True if a Property Setter was created/changed.
    """
    value = (value or "").strip()
    if not value:
        return False
    meta = frappe.get_meta(doctype)
    field = meta.get_field(fieldname)
    if not field or field.fieldtype != "Select":
        return False
    current = (field.options or "").split("\n")
    if value in [o.strip() for o in current]:
        return False

    new_options = [o for o in current if o.strip()] + [value]
    ps_name = frappe.db.get_value(
        "Property Setter",
        {"doc_type": doctype, "field_name": fieldname, "property": "options"},
        "name",
    )
    if ps_name:
        frappe.db.set_value("Property Setter", ps_name, "value", "\n".join(new_options))
    else:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": fieldname,
            "property": "options",
            "property_type": "Text",
            "value": "\n".join(new_options),
        }).insert(ignore_permissions=True)

    if clear_cache:
        frappe.clear_cache(doctype=doctype)
    return True


def ensure_fetch_if_empty(doctype, fieldname):
    """Turn on "Fetch If Empty" (via Property Setter) for an editable
    fetch_from field that doesn't already have it on.

    Frappe's default for a fetch_from field is fetch_if_empty=0, which
    means the field is re-fetched from its link source and OVERWRITTEN on
    every save of the parent document — even if a user has since edited it
    directly. That's correct for a read-only mirror field, but for an
    *editable* one it silently destroys a manual edit the next time anyone
    saves the record, with no error and no trace of what happened — it just
    looks like the data vanished. Flipping fetch_if_empty on keeps the
    auto-fill-when-blank behavior without ever clobbering a value someone
    has since typed in by hand.

    No-ops if the field isn't a fetch_from field, doesn't exist, or already
    has fetch_if_empty on. Returns True if a Property Setter was created or
    changed.
    """
    meta = frappe.get_meta(doctype)
    field = meta.get_field(fieldname)
    if not field or not field.fetch_from or field.fetch_if_empty:
        return False

    ps_name = frappe.db.get_value(
        "Property Setter",
        {"doc_type": doctype, "field_name": fieldname, "property": "fetch_if_empty"},
        "name",
    )
    if ps_name:
        frappe.db.set_value("Property Setter", ps_name, "value", "1")
    else:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": fieldname,
            "property": "fetch_if_empty",
            "property_type": "Check",
            "value": "1",
        }).insert(ignore_permissions=True)
    return True


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
