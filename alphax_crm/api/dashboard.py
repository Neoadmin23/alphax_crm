"""AlphaX Executive Dashboard — the single management-facing screen this app
was missing: KPIs, pipeline, funnel, trend and a leaderboard in one view,
the way a Salesforce/Zoho "Sales Dashboard" would be laid out, but reading
directly off this app's own PreLead -> Lead -> Opportunity funnel and its
own Lead Stage Automation data (the day-gap tracking most off-the-shelf
CRMs don't have at all).

This is a manager-facing screen, not a per-record tool like the AI
Assistant — restricted to Sales Manager / System Manager, same as the
analytic Script Reports it complements. It calls the same underlying ideas
as those reports (open pipeline by stage, win/loss, source performance) but
returns one combined JSON payload shaped for chart rendering, rather than a
flat table, since a dashboard page draws its own charts instead of using
the report list view.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, today


def _require_management():
    if not (frappe.has_role("Sales Manager") or frappe.has_role("System Manager")):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_dashboard_data(from_date=None, to_date=None, territory=None):
    _require_management()
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won_status = settings.won_status or "Converted"
    lost_status = settings.lost_status or "Lost"

    if not to_date:
        to_date = today()
    if not from_date:
        days = settings.dashboard_default_range_days or 30
        from_date = add_days(to_date, -days)

    date_range = ["between", [from_date, to_date]]
    opp_filters = {}
    if territory:
        opp_filters["territory"] = territory

    # --- funnel + volume in the selected period -----------------------
    preleads = frappe.get_all(
        "AlphaX PreLead", filters={"creation": date_range}, fields=["source", "converted"], limit_page_length=0
    )
    lead_filters = {"creation": date_range}
    leads = frappe.get_all("Lead", filters=lead_filters, fields=["source", "status"], limit_page_length=0)

    closed_filters = dict(opp_filters, **{"transaction_date": date_range, "status": ["in", [won_status, lost_status]]})
    closed_opps = frappe.get_all(
        "Opportunity",
        filters=closed_filters,
        fields=["status", "opportunity_amount", "transaction_date", "modified", "opportunity_owner"],
        limit_page_length=0,
    )
    won_opps = [o for o in closed_opps if o.status == won_status]
    lost_opps = [o for o in closed_opps if o.status == lost_status]

    # --- live snapshot (not bounded by the date range) -----------------
    open_filters = dict(opp_filters, **{"status": ["not in", [won_status, lost_status]]})
    open_opps = frappe.get_all(
        "Opportunity", filters=open_filters, fields=["sales_stage", "opportunity_amount"], limit_page_length=0
    )
    overdue_followups = frappe.db.count("AlphaX Follow-up", {"next_follow_up_date": ["<", today()]})

    # --- KPI tiles -------------------------------------------------------
    prelead_converted = sum(1 for p in preleads if p.converted)
    conversion_rate = round(prelead_converted / len(preleads) * 100, 1) if preleads else 0
    total_closed = len(won_opps) + len(lost_opps)
    win_rate = round(len(won_opps) / total_closed * 100, 1) if total_closed else 0
    won_value = sum(o.opportunity_amount or 0 for o in won_opps)
    open_pipeline_value = sum(o.opportunity_amount or 0 for o in open_opps)
    cycle_days = [
        date_diff(o.modified, o.transaction_date) for o in won_opps if o.transaction_date and o.modified
    ]
    avg_cycle_days = round(sum(cycle_days) / len(cycle_days), 1) if cycle_days else None

    kpis = [
        {"label": str(_("New PreLeads")), "value": len(preleads)},
        {"label": str(_("New Leads")), "value": len(leads)},
        {"label": str(_("PreLead Conversion")), "value": f"{conversion_rate}%"},
        {"label": str(_("Deals Won")), "value": len(won_opps)},
        {"label": str(_("Won Value")), "value": won_value, "is_currency": True},
        {"label": str(_("Win Rate")), "value": f"{win_rate}%"},
        {"label": str(_("Open Pipeline")), "value": open_pipeline_value, "is_currency": True},
        {"label": str(_("Avg Cycle (days)")), "value": avg_cycle_days if avg_cycle_days is not None else "—"},
        {"label": str(_("Overdue Follow-ups")), "value": overdue_followups, "alert": overdue_followups > 0},
    ]

    # --- pipeline by stage (live) -----------------------------------------
    stage_totals = {}
    for o in open_opps:
        stage = o.sales_stage or str(_("(not set)"))
        stage_totals[stage] = stage_totals.get(stage, 0) + (o.opportunity_amount or 0)
    pipeline_chart = {
        "labels": list(stage_totals.keys()),
        "values": [round(v, 2) for v in stage_totals.values()],
    }

    # --- source breakdown (period) ----------------------------------------
    source_totals = {}
    for p in preleads:
        s = p.source or str(_("(not set)"))
        source_totals[s] = source_totals.get(s, 0) + 1
    top_sources = sorted(source_totals.items(), key=lambda x: x[1], reverse=True)[:8]
    source_chart = {"labels": [s for s, _v in top_sources], "values": [v for _s, v in top_sources]}

    # --- monthly trend: new preleads vs won deals, last 6 months ----------
    months = []
    cursor = getdate(to_date)
    for _i in range(6):
        months.append((cursor.year, cursor.month))
        cursor = getdate(add_days(cursor.replace(day=1), -1))
    months.reverse()
    month_labels = [frappe.utils.formatdate(f"{y}-{m:02d}-01", "MMM yyyy") for y, m in months]

    all_preleads = frappe.get_all("AlphaX PreLead", fields=["creation"], limit_page_length=0)
    all_won = frappe.get_all(
        "Opportunity", filters={"status": won_status}, fields=["transaction_date"], limit_page_length=0
    )

    def month_bucket(dt):
        d = getdate(dt)
        return (d.year, d.month)

    prelead_by_month = {m: 0 for m in months}
    for p in all_preleads:
        key = month_bucket(p.creation)
        if key in prelead_by_month:
            prelead_by_month[key] += 1

    won_by_month = {m: 0 for m in months}
    for o in all_won:
        if not o.transaction_date:
            continue
        key = month_bucket(o.transaction_date)
        if key in won_by_month:
            won_by_month[key] += 1

    trend_chart = {
        "labels": month_labels,
        "preleads": [prelead_by_month[m] for m in months],
        "won": [won_by_month[m] for m in months],
    }

    # --- leaderboard top 5 (period) ---------------------------------------
    owner_won = {}
    for o in won_opps:
        owner = o.opportunity_owner or str(_("(not assigned)"))
        b = owner_won.setdefault(owner, {"count": 0, "value": 0.0})
        b["count"] += 1
        b["value"] += o.opportunity_amount or 0
    leaderboard = sorted(
        ({"owner": k, **v} for k, v in owner_won.items()), key=lambda x: x["value"], reverse=True
    )[:5]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "kpis": kpis,
        "pipeline_chart": pipeline_chart,
        "source_chart": source_chart,
        "trend_chart": trend_chart,
        "leaderboard": leaderboard,
    }
