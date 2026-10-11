"""AlphaX CRM AI Assistant — ask anything, anywhere.

Global (navbar) and per-screen ("Ask AI about this") natural-language
querying over CRM data, backed by the same local/self-hosted model already
configured in AlphaX CRM Settings > AI Assist. Two hard rules shape this
module, both about not trusting the model with anything it could get wrong
in a way that matters:

1. The model NEVER writes SQL and NEVER sees a fieldname/table name it then
   gets to choose freely. It only ever picks a *capability name* plus a few
   parameters from a small, explicit allow-list (ALLOWED — doctype by
   doctype, field by field) declared below. Every parameter the model
   returns is re-validated against that allow-list here, in Python, before
   it touches a query — an injected or hallucinated fieldname is dropped,
   not executed. This is what makes it safe to let a possibly-small,
   possibly-wrong local model drive a live data query at all.
2. Every query goes through `frappe.get_list`/`frappe.get_all` with the
   CALLING USER'S OWN permissions (never `ignore_permissions`), so a Sales
   User asking "list my leads" only ever sees what they could already see
   in the list view — the assistant is a faster way to ask, not a way
   around Frappe's own row-level permission model.

The model is asked, in one call, to translate the question into
{"capability": "...", "params": {...}} (or {"capability": "none", "answer":
"..."} for a question that isn't about CRM data at all — a how-to question,
for instance). If it picked a real capability, that capability actually
runs against the database, and the *real* result rows are handed back to
the model in a second call to write the sentence a human reads — so the
numbers in the final answer are the numbers that were actually queried, not
whatever the model guessed the first time.
"""

import json

import frappe
from frappe import _

from alphax_crm.crm.utils import ai_request_headers, get_settings, log_error


# ---------------------------------------------------------------------------
# Allow-list: the only doctypes/fields this module will ever query or group
# by, and the only fields it will ever put into a SELECT list. Extend this
# when a new reportable field is added — never bypass it.
# ---------------------------------------------------------------------------
ALLOWED = {
    "Lead": {
        "group_by": ["status", "custom_lead_status", "source", "territory", "industry", "lead_owner"],
        "filters": ["status", "custom_lead_status", "source", "territory", "industry", "lead_owner"],
        "metric_fields": [],
        "list_fields": ["name", "lead_name", "company_name", "status", "custom_lead_status", "source", "territory", "lead_owner", "creation"],
        "date_field": "creation",
    },
    "Opportunity": {
        "group_by": ["status", "sales_stage", "territory", "opportunity_owner"],
        "filters": ["status", "sales_stage", "territory", "opportunity_owner"],
        "metric_fields": ["opportunity_amount"],
        "list_fields": ["name", "party_name", "status", "sales_stage", "territory", "opportunity_owner", "opportunity_amount", "expected_closing", "creation"],
        "date_field": "transaction_date",
    },
    "AlphaX PreLead": {
        "group_by": ["status", "source", "industry", "city", "prospect_owner"],
        "filters": ["status", "source", "industry", "city", "prospect_owner", "converted"],
        "metric_fields": [],
        "list_fields": ["name", "prospect_name", "company_name", "status", "source", "industry", "prospect_owner", "converted", "creation"],
        "date_field": "creation",
    },
}
DOCTYPES = list(ALLOWED.keys())
MAX_ROWS = 50


def _clamp_limit(limit):
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    return max(1, min(n, MAX_ROWS))


def _valid_filters(doctype, raw_filters):
    """Only pass through filters on allow-listed fields with plain scalar
    values — never a dict/list from the model that could smuggle in an
    operator-based Frappe filter targeting a different field."""
    allowed_fields = set(ALLOWED[doctype]["filters"])
    out = {}
    if not isinstance(raw_filters, dict):
        return out
    for k, v in raw_filters.items():
        if k in allowed_fields and isinstance(v, (str, int, float, bool)):
            out[k] = v
    return out


def _apply_date_range(doctype, filters, date_from, date_to):
    field = ALLOWED[doctype]["date_field"]
    conditions = dict(filters)
    if date_from:
        conditions[field] = [">=", date_from]
    if date_to:
        existing = conditions.get(field)
        if isinstance(existing, list):
            conditions[field] = ["between", [existing[1], date_to]] if existing[0] == ">=" else ["<=", date_to]
        else:
            conditions[field] = ["<=", date_to]
    return conditions


# ---------------------------------------------------------------------------
# Capabilities — each takes validated params, queries with the CALLING
# user's own permissions, and returns {"columns", "rows", "chart"}.
# ---------------------------------------------------------------------------
def _cap_aggregate(params):
    doctype = params.get("doctype")
    if doctype not in ALLOWED:
        frappe.throw(_("Unsupported doctype: {0}").format(doctype))
    spec = ALLOWED[doctype]
    group_by = params.get("group_by")
    if group_by not in spec["group_by"]:
        frappe.throw(_("Cannot group {0} by {1}").format(doctype, group_by))
    metric = params.get("metric", "count")
    metric_field = params.get("metric_field")
    filters = _valid_filters(doctype, params.get("filters") or {})
    filters = _apply_date_range(doctype, filters, params.get("date_from"), params.get("date_to"))
    limit = _clamp_limit(params.get("limit", 15))

    if metric in ("sum", "avg") and metric_field in spec["metric_fields"]:
        value_expr = f"{metric}(`{metric_field}`) as value"
        value_label = f"{metric}({metric_field})"
    else:
        metric = "count"
        value_expr = "count(name) as value"
        value_label = "count"

    rows = frappe.get_list(
        doctype,
        filters=filters,
        fields=[f"`{group_by}` as label", value_expr],
        group_by=group_by,
        order_by="value desc",
        limit_page_length=limit,
        ignore_permissions=False,
    )
    rows = [{"label": r.label or _("(not set)"), "value": r.value or 0} for r in rows]
    return {
        "columns": [group_by, value_label],
        "rows": [[r["label"], r["value"]] for r in rows],
        "chart": {"type": "bar", "title": f"{doctype}: {value_label} by {group_by}", "labels": [r["label"] for r in rows], "values": [r["value"] for r in rows]},
    }


def _cap_list_records(params):
    doctype = params.get("doctype")
    if doctype not in ALLOWED:
        frappe.throw(_("Unsupported doctype: {0}").format(doctype))
    spec = ALLOWED[doctype]
    filters = _valid_filters(doctype, params.get("filters") or {})
    filters = _apply_date_range(doctype, filters, params.get("date_from"), params.get("date_to"))
    limit = _clamp_limit(params.get("limit", 20))
    fields = spec["list_fields"]

    rows = frappe.get_list(
        doctype,
        filters=filters,
        fields=fields,
        order_by="creation desc",
        limit_page_length=limit,
        ignore_permissions=False,
    )
    return {
        "columns": fields,
        "rows": [[r.get(f) for f in fields] for r in rows],
        "chart": None,
    }


def _cap_pipeline_value(params):
    group_by = params.get("group_by") if params.get("group_by") in ("status", "sales_stage", "territory") else "sales_stage"
    return _cap_aggregate({"doctype": "Opportunity", "group_by": group_by, "metric": "sum", "metric_field": "opportunity_amount", "limit": 20})


def _cap_conversion_funnel(_params):
    won_status = (get_settings().won_status or "Converted")
    stages = [
        (_("PreLeads"), frappe.get_list("AlphaX PreLead", filters={}, limit_page_length=0, ignore_permissions=False)),
        (_("Converted to Lead"), frappe.get_list("AlphaX PreLead", filters={"converted": 1}, limit_page_length=0, ignore_permissions=False)),
        (_("Opportunities"), frappe.get_list("Opportunity", filters={}, limit_page_length=0, ignore_permissions=False)),
        (_("Won Opportunities"), frappe.get_list("Opportunity", filters={"status": won_status}, limit_page_length=0, ignore_permissions=False)),
    ]
    rows = [[label, len(recs)] for label, recs in stages]
    return {
        "columns": [_("Stage"), _("Count")],
        "rows": rows,
        "chart": {"type": "bar", "title": str(_("Conversion Funnel")), "labels": [r[0] for r in rows], "values": [r[1] for r in rows]},
    }


def _cap_overdue_followups(params):
    agent = params.get("agent")
    filters = {"next_follow_up_date": ["<", frappe.utils.today()]}
    if agent:
        filters["agent"] = agent
    rows = frappe.get_list(
        "AlphaX Follow-up",
        filters=filters,
        fields=["name", "reference_doctype", "reference_name", "agent", "next_follow_up_date", "next_action"],
        order_by="next_follow_up_date asc",
        limit_page_length=MAX_ROWS,
        ignore_permissions=False,
    )
    cols = ["name", "reference_doctype", "reference_name", "agent", "next_follow_up_date", "next_action"]
    return {
        "columns": cols,
        "rows": [[r.get(c) for c in cols] for r in rows],
        "chart": None,
    }


def _cap_stage_durations(_params):
    rows = frappe.get_list(
        "AlphaX Stage Transition Log",
        fields=["field_label", "from_value", "to_value", "days_since_previous"],
        filters={"days_since_previous": [">", 0]},
        limit_page_length=500,
        ignore_permissions=False,
    )
    agg = {}
    for r in rows:
        key = f"{r.from_value} → {r.to_value}"
        agg.setdefault(key, []).append(r.days_since_previous or 0)
    summary = sorted(
        ({"label": k, "avg_days": round(sum(v) / len(v), 1), "count": len(v)} for k, v in agg.items()),
        key=lambda x: x["avg_days"],
        reverse=True,
    )[:15]
    return {
        "columns": [_("Transition"), _("Avg Days"), _("Count")],
        "rows": [[s["label"], s["avg_days"], s["count"]] for s in summary],
        "chart": {"type": "bar", "title": str(_("Average Days Between Stage Changes")), "labels": [s["label"] for s in summary], "values": [s["avg_days"] for s in summary]},
    }


CAPABILITIES = {
    "aggregate": _cap_aggregate,
    "list_records": _cap_list_records,
    "pipeline_value": _cap_pipeline_value,
    "conversion_funnel": _cap_conversion_funnel,
    "overdue_followups": _cap_overdue_followups,
    "stage_durations": _cap_stage_durations,
}

_CAPABILITY_DOC = """
- "aggregate": count/sum/avg one of {doctypes} grouped by an allowed field.
  params: {{"doctype": "...", "group_by": "...", "metric": "count|sum|avg",
  "metric_field": "..." (only for sum/avg), "filters": {{...}}, "date_from":
  "YYYY-MM-DD", "date_to": "YYYY-MM-DD", "limit": 15}}
- "list_records": a filtered list of records (not aggregated).
  params: {{"doctype": "...", "filters": {{...}}, "date_from", "date_to", "limit": 20}}
- "pipeline_value": sum of Opportunity amount, grouped by "status", "sales_stage" or "territory".
  params: {{"group_by": "sales_stage"}}
- "conversion_funnel": PreLead -> converted -> Opportunity -> Won counts. No params.
- "overdue_followups": AlphaX Follow-up rows whose next follow-up date has passed.
  params: {{"agent": "user@example.com"}} (optional)
- "stage_durations": average days between lead-stage transitions (from the
  Lead Stage Automation feature). No params.

Allowed fields per doctype (only ever use these — anything else will be rejected):
{fields}
""".format(
    doctypes=", ".join(f'"{d}"' for d in DOCTYPES),
    fields="\n".join(
        f'  {dt}: group_by/filters = {ALLOWED[dt]["group_by"]}, metric_fields = {ALLOWED[dt]["metric_fields"]}'
        for dt in DOCTYPES
    ),
)


def _plan_prompt(question, context):
    system = (
        "You are the query planner for a CRM assistant. Given a user's question, "
        "decide which ONE capability (if any) answers it, and with what parameters. "
        "Respond ONLY with JSON, no other text. If the question needs live CRM data, "
        'respond {"capability": "<name>", "params": {...}}. If it is a general '
        'question that does not need live data (how-to, definitions, advice), '
        'respond {"capability": "none", "answer": "<a helpful, concise answer>"}.\n\n'
        "Available capabilities:\n" + _CAPABILITY_DOC
    )
    user = question
    if context:
        user = f"[Currently viewing: {context}]\n{question}"
    return system, user


def _answer_prompt(question, capability, result):
    columns = result.get("columns") or []
    rows = (result.get("rows") or [])[:30]
    system = (
        "You are a CRM assistant. The user asked a question; the system already "
        "queried the real data for them, shown below as columns and rows. Write a "
        "concise answer (2-4 sentences) that directly answers the question using "
        "ONLY the numbers/values actually present in this data — never invent a "
        "number that isn't here. If the data is empty, say so plainly."
    )
    user = (
        f"Question: {question}\n\nCapability used: {capability}\n"
        f"Columns: {columns}\nRows: {json.dumps(rows, default=str)}"
    )
    return system, user


def _chat(system, user, settings, expect_json=False):
    """Same transport as api/ai.py's _chat — duplicated locally (rather than
    imported) because that one is private to the lead/opportunity pipeline
    and this module's calling convention differs slightly (it always needs
    the raw text back, never writes straight to a doctype field)."""
    base = (settings.ai_base_url or "http://localhost:11434").rstrip("/")
    model = settings.ai_model or "llama3.2:3b"
    url = f"{base}{settings.ai_chat_path or '/api/chat'}"

    import requests

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if expect_json:
        body["format"] = "json"
    headers = ai_request_headers(settings)

    resp = requests.post(url, json=body, headers=headers, timeout=settings.ai_timeout or 60)
    resp.raise_for_status()
    data = resp.json()
    if "message" in data:
        return data["message"]["content"]
    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    return json.dumps(data)


@frappe.whitelist()
def ask(question, context_doctype=None, context_name=None):
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in"), frappe.AuthenticationError)
    settings = get_settings()
    if not settings.ai_enabled:
        return {"answer": str(_("AI Assist is not enabled. Ask a System Manager to turn it on and set up a local AI server in AlphaX CRM Settings.")), "table": None, "chart": None}

    context = None
    if context_doctype and context_name and frappe.has_permission(context_doctype, "read", context_name):
        context = f"{context_doctype} {context_name}"

    system, user = _plan_prompt(question, context)
    try:
        raw = _chat(system, user, settings, expect_json=True)
        plan = json.loads(raw)
    except Exception:
        log_error("ai assistant: plan")
        return {"answer": str(_("Sorry, I couldn't reach the AI server just now. Check AI Assist in Settings.")), "table": None, "chart": None}

    capability = plan.get("capability")
    if capability == "none" or capability not in CAPABILITIES:
        return {"answer": plan.get("answer") or str(_("I'm not sure how to answer that from CRM data.")), "table": None, "chart": None}

    try:
        result = CAPABILITIES[capability](plan.get("params") or {})
    except frappe.PermissionError:
        return {"answer": str(_("You don't have permission to see that data.")), "table": None, "chart": None}
    except Exception:
        log_error("ai assistant: capability")
        return {"answer": str(_("Something went wrong running that query.")), "table": None, "chart": None}

    try:
        ans_system, ans_user = _answer_prompt(question, capability, result)
        answer_text = _chat(ans_system, ans_user, settings, expect_json=False)
    except Exception:
        log_error("ai assistant: summarize")
        answer_text = str(_("Here's what I found (couldn't reach the AI server to summarize it):"))

    return {
        "answer": answer_text,
        "table": {"columns": result["columns"], "rows": result["rows"]} if result.get("rows") else None,
        "chart": result.get("chart"),
    }
