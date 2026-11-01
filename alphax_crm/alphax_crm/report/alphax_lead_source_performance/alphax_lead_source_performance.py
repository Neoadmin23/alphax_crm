"""AlphaX Lead Source Performance — which acquisition channels actually turn
into business, not just which bring in the most raw volume.

Combines both ends of the funnel this app tracks per source: PreLead
capture-and-qualify (source -> converted to Lead) and, once qualified,
whether that Lead ultimately reached a "won" Lead Stage. Two funnels rather
than a single number because a source that captures a lot of PreLeads but
converts poorly is a very different problem from one that converts well
but barely captures anything — collapsing them into one ratio would hide
which half of the funnel needs attention.

"Won" isn't hardcoded to a literal string: it's read off whichever Lead
Stage(s) in AlphaX CRM Settings > Lead Stage Automation contain the word
"won" (case-insensitive), since that mapping is admin-configurable and the
installed default (Customer -> Won) is only a starting point, not a fixed
vocabulary this report can safely assume everyone keeps.
"""

import frappe
from frappe import _


def _won_lead_stages(settings):
    stages = {row.lead_stage for row in (settings.lead_stage_map or []) if row.lead_stage}
    won = [s for s in stages if "won" in s.lower()]
    return won or ["Won"]


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))

    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won_stages = _won_lead_stages(settings)
    date_range = ["between", [filters.from_date, filters.to_date]]

    prelead_conditions = {"creation": date_range}
    lead_conditions = {"creation": date_range}
    if filters.get("source"):
        prelead_conditions["source"] = filters.source
        lead_conditions["source"] = filters.source

    preleads = frappe.get_all(
        "AlphaX PreLead", filters=prelead_conditions, fields=["source", "converted"], limit_page_length=0
    )
    leads_meta = frappe.get_meta("Lead")
    lead_fields = ["source", "status"]
    leads = (
        frappe.get_all("Lead", filters=lead_conditions, fields=lead_fields, limit_page_length=0)
        if leads_meta.has_field("source")
        else []
    )

    sources = {}

    def bucket(source):
        return sources.setdefault(
            source or _("(not set)"),
            {"preleads": 0, "prelead_converted": 0, "leads": 0, "leads_won": 0},
        )

    for p in preleads:
        b = bucket(p.source)
        b["preleads"] += 1
        if p.converted:
            b["prelead_converted"] += 1

    for l in leads:
        b = bucket(l.source)
        b["leads"] += 1
        if l.status in won_stages:
            b["leads_won"] += 1

    data = []
    for source, b in sources.items():
        prelead_rate = round(b["prelead_converted"] / b["preleads"] * 100, 1) if b["preleads"] else 0
        lead_win_rate = round(b["leads_won"] / b["leads"] * 100, 1) if b["leads"] else 0
        data.append({
            "source": source,
            "preleads": b["preleads"],
            "prelead_converted": b["prelead_converted"],
            "prelead_conversion_rate": prelead_rate,
            "leads": b["leads"],
            "leads_won": b["leads_won"],
            "lead_win_rate": lead_win_rate,
        })
    data.sort(key=lambda x: x["preleads"] + x["leads"], reverse=True)

    columns = [
        {"label": _("Source"), "fieldname": "source", "fieldtype": "Link", "options": "Lead Source", "width": 150},
        {"label": _("PreLeads"), "fieldname": "preleads", "fieldtype": "Int", "width": 90},
        {"label": _("PreLeads Converted"), "fieldname": "prelead_converted", "fieldtype": "Int", "width": 130},
        {"label": _("PreLead Conv. %"), "fieldname": "prelead_conversion_rate", "fieldtype": "Percent", "width": 120},
        {"label": _("Leads"), "fieldname": "leads", "fieldtype": "Int", "width": 90},
        {"label": _("Leads Won"), "fieldname": "leads_won", "fieldtype": "Int", "width": 90},
        {"label": _("Lead Win %"), "fieldname": "lead_win_rate", "fieldtype": "Percent", "width": 100},
    ]
    return columns, data
