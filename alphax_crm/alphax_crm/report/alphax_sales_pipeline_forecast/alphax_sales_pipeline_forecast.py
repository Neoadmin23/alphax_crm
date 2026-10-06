"""AlphaX Sales Pipeline & Forecast — open Opportunity value by sales stage,
weighted by each stage's own probability, so a manager can see not just how
much pipeline exists but how much of it is realistically likely to close.

"Open" means not yet in the configured won/lost status (AlphaX CRM Settings
> Sales Analytics) — a closed deal, won or lost, no longer belongs in an
active forecast. Date range filters on the opportunity's creation date
(when it entered the pipeline), not its expected close date, so this
answers "how much pipeline did we build in this period" rather than "what's
closing soon" — a separate, narrower question this report doesn't try to
also answer in the same table.
"""

import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))

    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won_status = settings.won_status or "Converted"
    lost_status = settings.lost_status or "Lost"

    conditions = {
        "transaction_date": ["between", [filters.from_date, filters.to_date]],
        "status": ["not in", [won_status, lost_status]],
    }
    if filters.get("territory"):
        conditions["territory"] = filters.territory
    if filters.get("opportunity_owner"):
        conditions["opportunity_owner"] = filters.opportunity_owner

    meta = frappe.get_meta("Opportunity")
    has_probability = meta.has_field("probability")
    fields = ["sales_stage", "opportunity_amount"]
    if has_probability:
        fields.append("probability")

    rows = frappe.get_all("Opportunity", filters=conditions, fields=fields, limit_page_length=0)

    groups = {}
    for r in rows:
        stage = r.sales_stage or _("(not set)")
        g = groups.setdefault(stage, {"count": 0, "amount": 0.0, "weighted": 0.0})
        amount = r.opportunity_amount or 0
        probability = (r.probability if has_probability else 100) or 0
        g["count"] += 1
        g["amount"] += amount
        g["weighted"] += amount * probability / 100.0

    data = [
        {
            "sales_stage": stage,
            "count": g["count"],
            "amount": g["amount"],
            "weighted_amount": round(g["weighted"], 2),
        }
        for stage, g in groups.items()
    ]
    data.sort(key=lambda x: x["amount"], reverse=True)

    columns = [
        {"label": _("Sales Stage"), "fieldname": "sales_stage", "fieldtype": "Data", "width": 180},
        {"label": _("Open Deals"), "fieldname": "count", "fieldtype": "Int", "width": 100},
        {"label": _("Pipeline Value"), "fieldname": "amount", "fieldtype": "Currency", "width": 150},
        {"label": _("Weighted (Forecast)"), "fieldname": "weighted_amount", "fieldtype": "Currency", "width": 160},
    ]
    return columns, data
