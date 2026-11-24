"""AlphaX Lost Reason Breakdown (BI) — live equivalent of the Excel
workbook's "Lost Reason Breakdown" section, with the same period/compare
engine as AlphaX Lead Stage Tracker (BI).

Anchored on Lead.won_or_lost_date (the native WF-06 closure field this app
sets the moment a Lead is marked Won/Lost -- see crm/stage_flow.py), not on
the Stage Transition Log, since that date is exactly "when this lead's
outcome was decided" and is already a plain Date field, no log-scanning
needed. lost_reason falls back to detailed_reason when the reason picked
was "Other" (see WF-06 Closure Controls on the Lead form).
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import (
    delta_pct,
    get_closure_values,
    get_compare_window,
    get_period_window,
    lead_dimension_filters,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    as_of_date = filters.get("as_of_date") or frappe.utils.today()
    period_type = filters.get("period_type") or "Monthly"
    compare_mode = filters.get("compare_mode") or "None"
    years_back = filters.get("years_back") or "1"

    cur_start, cur_end = get_period_window(period_type, as_of_date, filters.get("from_date"), filters.get("to_date"))
    cmp_start, cmp_end = get_compare_window(compare_mode, years_back, cur_start, cur_end, as_of_date)

    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    _won, lost_list, _postponed = get_closure_values(settings)
    if not lost_list:
        frappe.throw(_("No Lost Lead Stage values are configured in AlphaX CRM Settings → Closure Controls (WF-06)."))

    def reason_counts(start, end):
        if not start:
            return {}
        conditions = lead_dimension_filters(filters)
        conditions["status"] = ["in", lost_list]
        conditions["won_or_lost_date"] = ["between", [start, end]]
        rows = frappe.get_all("Lead", filters=conditions, fields=["lost_reason", "detailed_reason"],
                               limit_page_length=0)
        counts = {}
        for r in rows:
            reason = r.lost_reason or r.detailed_reason or _("(not set)")
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    cur_counts = reason_counts(cur_start, cur_end)
    cmp_counts = reason_counts(cmp_start, cmp_end) if cmp_start else {}
    reasons = sorted(set(cur_counts) | set(cmp_counts), key=lambda r: cur_counts.get(r, 0), reverse=True)

    data = []
    for reason in reasons:
        cur_v = cur_counts.get(reason, 0)
        cmp_v = cmp_counts.get(reason, 0) if cmp_start else None
        data.append({
            "lost_reason": reason,
            "current": cur_v,
            "comparison": cmp_v,
            "delta": (cur_v - cmp_v) if cmp_v is not None else None,
            "delta_pct": delta_pct(cur_v, cmp_v) if cmp_v is not None else None,
        })

    columns = [
        {"label": _("Lost Reason"), "fieldname": "lost_reason", "fieldtype": "Data", "width": 220},
        {"label": _("Current Period"), "fieldname": "current", "fieldtype": "Int", "width": 130},
        {"label": _("Comparison Period"), "fieldname": "comparison", "fieldtype": "Int", "width": 150},
        {"label": _("Δ"), "fieldname": "delta", "fieldtype": "Int", "width": 90},
        {"label": _("Δ%"), "fieldname": "delta_pct", "fieldtype": "Percent", "width": 90},
    ]

    total_cur = sum(cur_counts.values())
    report_summary = [{"label": _("Total Lost (Current)"), "value": total_cur, "indicator": "red"}]
    if cmp_start:
        report_summary.append({"label": _("Total Lost (Comparison)"), "value": sum(cmp_counts.values())})

    chart_datasets = [{"name": _("Current"), "values": [r["current"] for r in data]}]
    if cmp_start:
        chart_datasets.append({"name": _("Comparison"), "values": [r["comparison"] or 0 for r in data]})
    chart = {
        "data": {"labels": [r["lost_reason"] for r in data], "datasets": chart_datasets},
        "type": "pie" if not cmp_start else "bar",
    }

    message = _("Current period: {0} – {1}.").format(cur_start, cur_end)
    if cmp_start:
        message += " " + _("Comparison period: {0} – {1}.").format(cmp_start, cmp_end)

    return columns, data, message, chart, report_summary
