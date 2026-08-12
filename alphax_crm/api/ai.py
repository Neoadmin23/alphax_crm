"""Local-AI layer for AlphaX CRM.

All inference is sent to a locally-hosted endpoint configured in AlphaX CRM
Settings (ai_base_url) — Ollama-compatible by default — so no lead/customer
data leaves the box. PDPL-clean by design.

Functions here are invoked as background jobs (see crm/lead.py, crm/opportunity.py)
so a slow model never blocks a document save.
"""

import json

import frappe
from frappe.utils import now_datetime

from alphax_crm.crm.utils import get_settings, log_error


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def _chat(system, user, settings=None, expect_json=False):
    """Call the configured local model. Ollama /api/chat by default."""
    settings = settings or get_settings()
    base = (settings.ai_base_url or "http://localhost:11434").rstrip("/")
    model = settings.ai_model or "llama3.1"
    url = f"{base}{settings.ai_chat_path or '/api/chat'}"

    import requests  # lazy import; available in the Frappe bench env

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if expect_json:
        body["format"] = "json"

    headers = {"Content-Type": "application/json"}
    if settings.ai_api_key:
        headers["Authorization"] = f"Bearer {settings.get_password('ai_api_key')}"

    resp = requests.post(url, json=body, headers=headers, timeout=settings.ai_timeout or 60)
    resp.raise_for_status()
    data = resp.json()
    # Ollama: {"message": {"content": "..."}}; OpenAI-style fallback handled too.
    if "message" in data:
        return data["message"]["content"]
    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Lead processing
# ---------------------------------------------------------------------------
def process_lead(lead):
    settings = get_settings()
    if not settings.ai_enabled:
        return
    try:
        doc = frappe.get_doc("Lead", lead)
    except frappe.DoesNotExistError:
        return

    context = _lead_context(doc)

    if settings.ai_classify_leads:
        try:
            _classify(doc, context, settings)
        except Exception:
            log_error("ai classify")

    if settings.ai_draft_reply and doc.get("email_id"):
        try:
            _draft_reply(doc, context, settings)
        except Exception:
            log_error("ai draft reply")

    frappe.db.commit()


def _lead_context(doc):
    parts = [
        f"Name: {doc.get('lead_name')}",
        f"Company: {doc.get('company_name')}",
        f"Source: {doc.get('source')}",
        f"Industry: {doc.get('industry')}",
        f"Territory: {doc.get('territory')}",
    ]
    msg = doc.get("alphax_inbound_message")
    if msg:
        parts.append(f"Inbound message: {msg}")
    return "\n".join(p for p in parts if p and not p.endswith(": None"))


def _classify(doc, context, settings):
    system = (
        "You are a B2B sales qualification assistant for a Saudi/GCC software "
        "vendor. Classify the lead. Respond ONLY with JSON: "
        '{"fit": "High|Medium|Low", "urgency": "High|Medium|Low", '
        '"intent": "one short phrase", "summary": "one sentence"}.'
    )
    raw = _chat(system, context, settings, expect_json=True)
    try:
        result = json.loads(raw)
    except Exception:
        result = {"summary": raw[:240]}

    brief = (
        f"Fit: {result.get('fit', '-')} | Urgency: {result.get('urgency', '-')} | "
        f"Intent: {result.get('intent', '-')}\n{result.get('summary', '')}"
    )
    frappe.db.set_value("Lead", doc.name, "alphax_ai_brief", brief, update_modified=False)


def _draft_reply(doc, context, settings):
    lang = "Reply bilingually in Arabic and English." if settings.ai_bilingual else "Reply in English."
    system = (
        "You are a professional Saudi B2B sales rep. Draft a concise, warm first "
        f"response to this inbound lead. {lang} Keep it under 120 words. "
        "Do not invent pricing or commitments."
    )
    draft = _chat(system, context, settings)
    frappe.db.set_value("Lead", doc.name, "alphax_ai_draft_reply", draft, update_modified=False)


# ---------------------------------------------------------------------------
# Opportunity brief
# ---------------------------------------------------------------------------
def summarize_opportunity(opportunity):
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    try:
        opp = frappe.get_doc("Opportunity", opportunity)
    except frappe.DoesNotExistError:
        return None

    comms = frappe.get_all(
        "Communication",
        filters={"reference_doctype": "Opportunity", "reference_name": opportunity},
        fields=["sent_or_received", "content", "creation"],
        order_by="creation asc",
        limit=30,
    )
    thread = "\n".join(
        f"[{c.sent_or_received}] {frappe.utils.strip_html(c.content or '')[:400]}" for c in comms
    ) or "No communications recorded yet."

    system = (
        "Summarize this sales opportunity for a busy account manager in 3-4 "
        "sentences: where it stands, the customer's apparent need, and the "
        "recommended next best action."
    )
    user = f"Opportunity: {opp.name}\nStatus: {opp.status}\n\nThread:\n{thread}"

    try:
        brief = _chat(system, user, settings)
    except Exception:
        log_error("ai opportunity brief")
        return None

    frappe.db.set_value("Opportunity", opportunity, "alphax_ai_brief", brief, update_modified=False)
    frappe.db.commit()
    return brief
