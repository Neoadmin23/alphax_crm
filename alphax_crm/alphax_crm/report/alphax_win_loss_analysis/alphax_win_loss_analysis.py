"""AlphaX Win/Loss Analysis — closed deals (won or lost, per the statuses
configured in AlphaX CRM Settings > Sales Analytics), grouped by month,
territory or owner, with a win rate alongside the raw counts and value —
the number a sales manager actually wants isn't "how many deals closed", it
is "what fraction of what we fought for did we keep."

Grouped on the opportunity's creation date, not a dedicated "closed on"
date — standard Opportunity has no such field — so this reads as "of the
deals that ENTERED the pipeline in this window, how did they ultimately
resolve", which can include deals that took a while to close either way.
"""

import frappe
from frappe import _

GROUP_FIELD = {
    "Month": None,  # computed from transaction_date, not a plain field
    "Territory": "territory",
    "Owner": "opportunity_owner",
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))

    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won_status = settings.won_status or "Converted"
    lost_status = settings.lost_status or "Lost"
    group_by = filters.get("group_by") or "Month"

    conditions = {
        "transaction_date": ["between", [filters.from_date, filters.to_date]],
        "status": ["in", [won_status, lost_status]],
    }
    if filters.get("territory"):
        conditions["territory"] = filters.territory

    rows = frappe.get_all(
        "Opportunity",
        filters=conditions,
        fields=["status", "opportunity_amount", "transaction_date", "territory", "opportunity_owner"],
        limit_page_length=0,
    )

    groups = {}
    sort_keys = {}
    for r in rows:
        if group_by == "Month" and r.transaction_date:
            d = frappe.utils.getdate(r.transaction_date)
            key = frappe.utils.formatdate(d, "MMM yyyy")
            sort_keys[key] = (d.year, d.month)
        else:
            key = r.get(GROUP_FIELD.get(group_by, "territory")) or _("(not set)")
        g = groups.setdefault(key, {"won_count": 0, "won_value": 0.0, "lost_count": 0, "lost_value": 0.0})
        amount = r.opportunity_amount or 0
        if r.status == won_status:
            g["won_count"] += 1
            g["won_value"] += amount
        elif r.status == lost_status:
            g["lost_count"] += 1
            g["lost_value"] += amount

    data = []
    for key, g in groups.items():
        total = g["won_count"] + g["lost_count"]
        win_rate = round(g["won_count"] / total * 100, 1) if total else 0
        data.append({
            "group_label": key,
            "won_count": g["won_count"],
            "won_value": g["won_value"],
            "lost_count": g["lost_count"],
            "lost_value": g["lost_value"],
            "win_rate": win_rate,
        })

    if group_by == "Month":
        data.sort(key=lambda x: sort_keys.get(x["group_label"], (0, 0)))
    else:
        data.sort(key=lambda x: x["won_value"], reverse=True)

    columns = [
        {"label": _(group_by), "fieldname": "group_label", "fieldtype": "Data", "width": 140},
        {"label": _("Won"), "fieldname": "won_count", "fieldtype": "Int", "width": 80},
        {"label": _("Won Value"), "fieldname": "won_value", "fieldtype": "Currency", "width": 140},
        {"label": _("Lost"), "fieldname": "lost_count", "fieldtype": "Int", "width": 80},
        {"label": _("Lost Value"), "fieldname": "lost_value", "fieldtype": "Currency", "width": 140},
        {"label": _("Win Rate %"), "fieldname": "win_rate", "fieldtype": "Percent", "width": 100},
    ]
    return columns, data
