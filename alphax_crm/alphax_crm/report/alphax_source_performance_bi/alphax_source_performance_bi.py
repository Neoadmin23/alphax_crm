"""AlphaX Source Performance (BI) — New Leads / Won / Lost / Quotation
Value / Conversion %, broken down one row per Lead Source, for the selected
period (with an optional comparison).

Thin wrapper around crm/bi_report.py's grouped_performance() -- the same
engine behind AlphaX Sales Person Performance BI, just grouped by "source"
instead of "lead_owner". See that helper's docstring for exactly what each
number does and doesn't mean (period-aligned, not lifetime-cohort, counts).
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import (
    get_closure_values,
    get_compare_window,
    get_period_window,
    grouped_performance,
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
    won, lost_list, _postponed = get_closure_values(settings)

    by_source = grouped_performance(filters, "source", cur_start, cur_end, cmp_start, cmp_end, won, lost_list)

    data = []
    for source, v in by_source.items():
        conversion = round((v["won_cur"] / v["new_cur"]) * 100.0, 1) if v["new_cur"] else None
        conversion_cmp = (
            round((v["won_cmp"] / v["new_cmp"]) * 100.0, 1) if (cmp_start and v["new_cmp"]) else None
        )
        data.append({
            "source": source,
            "new_leads": v["new_cur"],
            "new_leads_cmp": v["new_cmp"],
            "won": v["won_cur"],
            "won_cmp": v["won_cmp"],
            "lost": v["lost_cur"],
            "lost_cmp": v["lost_cmp"],
            "quotation_value": v["qv_cur"],
            "quotation_value_cmp": v["qv_cmp"],
            "conversion_pct": conversion,
            "conversion_pct_cmp": conversion_cmp,
        })
    data.sort(key=lambda r: r["new_leads"], reverse=True)

    columns = [
        {"label": _("Source"), "fieldname": "source", "fieldtype": "Link", "options": "Lead Source", "width": 160},
        {"label": _("New Leads"), "fieldname": "new_leads", "fieldtype": "Int", "width": 100},
        {"label": _("New Leads (Comparison)"), "fieldname": "new_leads_cmp", "fieldtype": "Int", "width": 150},
        {"label": _("Won"), "fieldname": "won", "fieldtype": "Int", "width": 80},
        {"label": _("Lost"), "fieldname": "lost", "fieldtype": "Int", "width": 80},
        {"label": _("Conversion %"), "fieldname": "conversion_pct", "fieldtype": "Percent", "width": 110},
        {"label": _("Conversion % (Comparison)"), "fieldname": "conversion_pct_cmp", "fieldtype": "Percent", "width": 170},
        {"label": _("Quotation Value"), "fieldname": "quotation_value", "fieldtype": "Currency", "width": 140},
        {"label": _("Quotation Value (Comparison)"), "fieldname": "quotation_value_cmp", "fieldtype": "Currency", "width": 180},
    ]

    total_new = sum(r["new_leads"] for r in data)
    total_won = sum(r["won"] for r in data)
    total_lost = sum(r["lost"] for r in data)
    total_qv = sum(r["quotation_value"] or 0 for r in data)

    report_summary = [
        {"label": _("Sources (Active This Period)"), "value": len(data), "indicator": "blue"},
        {"label": _("Total New Leads"), "value": total_new, "indicator": "blue"},
        {"label": _("Total Won"), "value": total_won, "indicator": "green"},
        {"label": _("Total Lost"), "value": total_lost, "indicator": "red"},
        {"label": _("Total Quotation Value"), "value": total_qv, "datatype": "Currency", "indicator": "blue"},
    ]

    chart = {
        "data": {
            "labels": [r["source"] for r in data],
            "datasets": [
                {"name": _("New Leads"), "values": [r["new_leads"] for r in data]},
                {"name": _("Won"), "values": [r["won"] for r in data]},
            ],
        },
        "type": "bar",
    }

    message = _("Current period: {0} – {1}.").format(cur_start, cur_end)
    if cmp_start:
        message += " " + _("Comparison period: {0} – {1}.").format(cmp_start, cmp_end)

    return columns, data, message, chart, report_summary
