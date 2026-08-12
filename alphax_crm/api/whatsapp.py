"""WhatsApp Business Cloud API intake for AlphaX CRM.

One endpoint handles both Meta webhook phases:

    GET  /api/method/alphax_crm.api.whatsapp.webhook   -> verification handshake
    POST /api/method/alphax_crm.api.whatsapp.webhook   -> inbound message events

Set the Callback URL to the POST endpoint and the Verify Token to
`whatsapp_verify_token` in AlphaX CRM Settings. Inbound events are signature-
checked (X-Hub-Signature-256 against the App Secret), de-duplicated by WhatsApp
message id, and turned into Leads + threaded Communications. Heavy work
(lead creation, media download, auto-ack send) runs in the background so Meta
always receives a fast 200.
"""

import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from alphax_crm.crm.utils import get_settings, log_error

GRAPH = "https://graph.facebook.com"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def webhook(**kwargs):
    if frappe.request and frappe.request.method == "GET":
        return _verify_handshake()
    return _receive()


def _verify_handshake():
    """Echo hub.challenge back to Meta when the verify token matches."""
    from werkzeug.wrappers import Response

    settings = get_settings()
    args = frappe.form_dict
    mode = args.get("hub.mode")
    token = args.get("hub.verify_token")
    challenge = args.get("hub.challenge")

    expected = settings.get_password("whatsapp_verify_token", raise_exception=False)
    if mode == "subscribe" and expected and token == expected:
        return Response(challenge or "", status=200, mimetype="text/plain")

    return Response("forbidden", status=403, mimetype="text/plain")


def _receive():
    settings = get_settings()
    if not settings.whatsapp_enabled:
        frappe.local.response["http_status_code"] = 200
        return {"status": "ignored"}

    raw = frappe.request.get_data() if frappe.request else b""

    # Signature validation (skipped only if no App Secret configured).
    app_secret = settings.get_password("whatsapp_app_secret", raise_exception=False)
    if app_secret:
        sig = frappe.get_request_header("X-Hub-Signature-256") or ""
        if not _valid_signature(raw, sig, app_secret):
            frappe.local.response["http_status_code"] = 401
            return {"status": "bad_signature"}

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        payload = {}

    # Acknowledge immediately; process after the response is committed.
    frappe.enqueue(
        "alphax_crm.api.whatsapp.process_events",
        queue="short",
        payload=payload,
        enqueue_after_commit=True,
    )
    frappe.local.response["http_status_code"] = 200
    return {"status": "received"}


def _valid_signature(raw, header, app_secret):
    if not header.startswith("sha256="):
        return False
    expected = header.split("=", 1)[1]
    digest = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


# ---------------------------------------------------------------------------
# Event processing (background)
# ---------------------------------------------------------------------------
def process_events(payload):
    settings = get_settings()
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            messages = value.get("messages") or []
            if not messages:
                continue  # delivery/read status callbacks — ignore
            contacts = {c.get("wa_id"): c for c in (value.get("contacts") or [])}
            for msg in messages:
                try:
                    _handle_message(msg, contacts, settings)
                except Exception:
                    log_error("whatsapp handle message")
    frappe.db.commit()


def _handle_message(msg, contacts, settings):
    wamid = msg.get("id")
    wa_id = msg.get("from")
    if not wamid or not wa_id:
        return

    # Idempotency — WhatsApp redelivers; never double-log a message.
    if frappe.db.exists("Communication", {"alphax_wa_message_id": wamid}):
        return

    profile = (contacts.get(wa_id, {}).get("profile") or {})
    contact_name = profile.get("name") or wa_id
    text, media = _extract_content(msg)

    lead = _resolve_lead(wa_id, contact_name, text, settings)

    comm = frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Chat",
            "sent_or_received": "Received",
            "subject": f"WhatsApp from {contact_name}",
            "content": text or f"[{msg.get('type', 'message')}]",
            "reference_doctype": "Lead",
            "reference_name": lead.name,
            "phone_no": wa_id,
            "sender": wa_id,
            "alphax_wa_message_id": wamid,
        }
    )
    comm.flags.ignore_permissions = True
    comm.insert(ignore_permissions=True)

    if media and settings.whatsapp_download_media:
        try:
            _download_media(media, lead.name, settings)
        except Exception:
            log_error("whatsapp media download")

    if settings.whatsapp_auto_ack:
        frappe.enqueue(
            "alphax_crm.api.whatsapp.send_acknowledgment",
            queue="short",
            wa_id=wa_id,
            lead=lead.name,
            enqueue_after_commit=True,
        )


def _extract_content(msg):
    """Return (text, media_dict|None) for the supported message types."""
    mtype = msg.get("type")
    if mtype == "text":
        return (msg.get("text", {}) or {}).get("body", ""), None
    if mtype in ("image", "document", "audio", "video", "sticker"):
        media = msg.get(mtype, {}) or {}
        caption = media.get("caption", "")
        label = media.get("filename") or mtype
        return (caption or f"[{label}]"), {"id": media.get("id"), "type": mtype, "filename": media.get("filename")}
    if mtype == "location":
        loc = msg.get("location", {}) or {}
        return f"[location] {loc.get('latitude')},{loc.get('longitude')} {loc.get('name', '')}".strip(), None
    if mtype in ("button", "interactive"):
        block = msg.get(mtype, {}) or {}
        reply = block.get("button_reply") or block.get("list_reply") or {}
        return reply.get("title") or block.get("text", "") or "[interactive reply]", None
    return f"[{mtype or 'message'}]", None


def _resolve_lead(wa_id, contact_name, text, settings):
    """Find a Lead by phone/mobile == wa_id, else create one."""
    for field in ("mobile_no", "phone", "whatsapp_no"):
        if not frappe.get_meta("Lead").has_field(field):
            continue
        name = frappe.db.get_value("Lead", {field: wa_id}, "name")
        if name:
            return frappe.get_doc("Lead", name)
        # WhatsApp wa_id has no leading '+'; try the normalized variant too.
        name = frappe.db.get_value("Lead", {field: f"+{wa_id}"}, "name")
        if name:
            return frappe.get_doc("Lead", name)

    lead = frappe.new_doc("Lead")
    lead.lead_name = contact_name
    lead.mobile_no = f"+{wa_id}" if not str(wa_id).startswith("+") else wa_id
    if frappe.get_meta("Lead").has_field("whatsapp_no"):
        lead.whatsapp_no = lead.mobile_no
    lead.source = settings.whatsapp_default_source or "WhatsApp"
    # Inbound contact = the person reached out first.
    lead.alphax_lawful_basis = "Legitimate Interest"
    lead.alphax_consent_source = "WhatsApp Inbound"
    if text and frappe.get_meta("Lead").has_field("alphax_inbound_message"):
        lead.alphax_inbound_message = text
    lead.flags.ignore_permissions = True
    lead.flags.alphax_skip_dq = True
    lead.insert(ignore_permissions=True)
    return lead


# ---------------------------------------------------------------------------
# Outbound (auto-ack + generic send)
# ---------------------------------------------------------------------------
def send_acknowledgment(wa_id, lead=None):
    settings = get_settings()
    if not (settings.whatsapp_enabled and settings.whatsapp_auto_ack):
        return
    mode = settings.whatsapp_ack_mode or "Text"
    try:
        if mode == "Template" and settings.whatsapp_ack_template:
            resp = send_template(wa_id, settings.whatsapp_ack_template, settings.whatsapp_ack_language or "en_US", settings)
            body = f"[template: {settings.whatsapp_ack_template}]"
        else:
            body = settings.whatsapp_ack_text or "Thank you for contacting AlphaX."
            resp = send_text(wa_id, body, settings)
    except Exception:
        log_error("whatsapp auto-ack send")
        return

    if lead:
        _log_outbound(lead, wa_id, body, resp)


def send_text(wa_id, body, settings=None):
    settings = settings or get_settings()
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    return _post_message(payload, settings)


def send_template(wa_id, template_name, language, settings=None, components=None):
    settings = settings or get_settings()
    template = {"name": template_name, "language": {"code": language}}
    if components:
        template["components"] = components
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "template",
        "template": template,
    }
    return _post_message(payload, settings)


def _post_message(payload, settings):
    import requests

    version = settings.whatsapp_api_version or "v21.0"
    phone_id = settings.whatsapp_phone_number_id
    token = settings.get_password("whatsapp_access_token", raise_exception=False)
    if not (phone_id and token):
        frappe.throw(_("WhatsApp Phone Number ID and Access Token are required."))

    url = f"{GRAPH}/{version}/{phone_id}/messages"
    resp = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _log_outbound(lead, wa_id, body, resp):
    wamid = None
    try:
        wamid = (resp.get("messages") or [{}])[0].get("id")
    except Exception:
        pass
    doc = frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Chat",
            "sent_or_received": "Sent",
            "subject": "WhatsApp auto-acknowledgment",
            "content": body,
            "reference_doctype": "Lead",
            "reference_name": lead,
            "phone_no": wa_id,
            "recipients": wa_id,
            "alphax_wa_message_id": wamid,
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Media download (optional, PDPL-local: stored on the Frappe host)
# ---------------------------------------------------------------------------
def _download_media(media, lead_name, settings):
    import requests

    media_id = media.get("id")
    if not media_id:
        return
    version = settings.whatsapp_api_version or "v21.0"
    token = settings.get_password("whatsapp_access_token", raise_exception=False)
    headers = {"Authorization": f"Bearer {token}"}

    meta = requests.get(f"{GRAPH}/{version}/{media_id}", headers=headers, timeout=30).json()
    url = meta.get("url")
    if not url:
        return
    binary = requests.get(url, headers=headers, timeout=60).content

    filename = media.get("filename") or f"whatsapp_{media_id}"
    saved = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": filename,
            "attached_to_doctype": "Lead",
            "attached_to_name": lead_name,
            "is_private": 1,
            "content": binary,
        }
    )
    saved.flags.ignore_permissions = True
    saved.insert(ignore_permissions=True)
