"""Local-AI layer for AlphaX CRM.

All inference is sent to a locally-hosted endpoint configured in AlphaX CRM
Settings (ai_base_url) — Ollama-compatible by default — so no lead/customer
data leaves the box. PDPL-clean by design.

Functions here are invoked as background jobs (see crm/lead.py, crm/opportunity.py)
so a slow model never blocks a document save.
"""

import frappe

from alphax_crm.crm.utils import ai_request_headers, get_settings, log_error


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def _chat(system, user, settings=None, expect_json=False, feature="adhoc", reference=None):
    """Call the configured model through the AlphaX AI engine (provider choice,
    governance, PII masking and the AI log all live in alphax_crm/ai/engine.py)."""
    from alphax_crm.ai.engine import complete

    return complete(system, user, feature=feature, reference=reference, want_json=expect_json, temperature=0.2)


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

    if settings.get("ai_next_action_on_new_lead"):
        try:
            from alphax_crm.ai.sales import next_best_action

            next_best_action(doc.name)
        except Exception:
            log_error("ai next action")

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
    raw = _chat(system, context, settings, expect_json=True, feature="lead_classify", reference=("Lead", doc.name))
    try:
        from alphax_crm.ai.pure import extract_json

        result = extract_json(raw)
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
    draft = _chat(system, context, settings, feature="lead_draft_reply", reference=("Lead", doc.name))
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
        brief = _chat(system, user, settings, feature="opportunity_brief", reference=("Opportunity", opportunity))
    except Exception:
        log_error("ai opportunity brief")
        return None

    frappe.db.set_value("Opportunity", opportunity, "alphax_ai_brief", brief, update_modified=False)
    frappe.db.commit()
    return brief
