"""AlphaX Sales Leaderboard — per salesperson, side by side: what they closed
in the selected period, and what they're currently carrying in open
pipeline right now. Deliberately two different time scopes in one row
(closed = bounded by the date filter, open pipeline = a live snapshot as of
now) because "what did you close this quarter" and "what are you sitting on
right now" are both real management questions and neither one alone tells
the full story — a rep with a great quarter and an empty pipeline needs a
different conversation than one with a mediocre quarter and a full one.

Avg. Cycle Days is an approximation: standard Opportunity has no dedicated
"closed on" date, so this uses the record's last-modified timestamp for won
deals as the closest available proxy for when it actually closed. Treat it
as directional, not exact, especially on records that were edited after
closing for unrelated reasons.
"""

import frappe
from frappe import _
from frappe.utils import date_diff


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are required."))

    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won_status = settings.won_status or "Converted"
    lost_status = settings.lost_status or "Lost"

    base_conditions = {}
    if filters.get("territory"):
        base_conditions["territory"] = filters.territory

    closed_conditions = dict(base_conditions)
    closed_conditions["transaction_date"] = ["between", [filters.from_date, filters.to_date]]
    closed_conditions["status"] = ["in", [won_status, lost_status]]
    closed_rows = frappe.get_all(
        "Opportunity",
        filters=closed_conditions,
        fields=["opportunity_owner", "status", "opportunity_amount", "transaction_date", "modified"],
        limit_page_length=0,
    )

    open_conditions = dict(base_conditions)
    open_conditions["status"] = ["not in", [won_status, lost_status]]
    open_rows = frappe.get_all(
        "Opportunity", filters=open_conditions, fields=["opportunity_owner", "opportunity_amount"], limit_page_length=0
    )

    board = {}

    def bucket(owner):
        return board.setdefault(owner or _("(not assigned)"), {
            "won_count": 0, "won_value": 0.0, "lost_count": 0,
            "open_count": 0, "open_value": 0.0, "cycle_days": [],
        })

    for r in closed_rows:
        b = bucket(r.opportunity_owner)
        amount = r.opportunity_amount or 0
        if r.status == won_status:
            b["won_count"] += 1
            b["won_value"] += amount
            if r.transaction_date and r.modified:
                b["cycle_days"].append(date_diff(r.modified, r.transaction_date))
        elif r.status == lost_status:
            b["lost_count"] += 1

    for r in open_rows:
        b = bucket(r.opportunity_owner)
        b["open_count"] += 1
        b["open_value"] += r.opportunity_amount or 0

    data = []
    for owner, b in board.items():
        total_closed = b["won_count"] + b["lost_count"]
        win_rate = round(b["won_count"] / total_closed * 100, 1) if total_closed else 0
        avg_deal = round(b["won_value"] / b["won_count"], 2) if b["won_count"] else 0
        avg_cycle = round(sum(b["cycle_days"]) / len(b["cycle_days"]), 1) if b["cycle_days"] else None
        data.append({
            "owner": owner,
            "won_count": b["won_count"],
            "won_value": b["won_value"],
            "win_rate": win_rate,
            "avg_deal_size": avg_deal,
            "avg_cycle_days": avg_cycle,
            "open_count": b["open_count"],
            "open_value": b["open_value"],
        })
    data.sort(key=lambda x: x["won_value"], reverse=True)

    columns = [
        {"label": _("Owner"), "fieldname": "owner", "fieldtype": "Link", "options": "User", "width": 160},
        {"label": _("Won (period)"), "fieldname": "won_count", "fieldtype": "Int", "width": 100},
        {"label": _("Won Value (period)"), "fieldname": "won_value", "fieldtype": "Currency", "width": 150},
        {"label": _("Win Rate %"), "fieldname": "win_rate", "fieldtype": "Percent", "width": 100},
        {"label": _("Avg Deal Size"), "fieldname": "avg_deal_size", "fieldtype": "Currency", "width": 130},
        {"label": _("Avg Cycle (days)"), "fieldname": "avg_cycle_days", "fieldtype": "Float", "width": 130},
        {"label": _("Open Deals (now)"), "fieldname": "open_count", "fieldtype": "Int", "width": 120},
        {"label": _("Open Pipeline (now)"), "fieldname": "open_value", "fieldtype": "Currency", "width": 150},
    ]
    return columns, data
