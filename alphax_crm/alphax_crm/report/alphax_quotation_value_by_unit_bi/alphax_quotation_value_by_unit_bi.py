"""AlphaX Quotation Value by Business Unit (BI) — live equivalent of the
Excel workbook's "Quotation Value by Payment Type" section. Grouped by
Business Unit (custom_business_lead_unit) instead of payment type: this app
has no payment-type field on Quotation, and this is the real, confirmed
dimension that exists on Lead instead -- an honest substitute rather than a
breakdown by a field that doesn't actually exist on this site.

Only submitted Quotations count (docstatus=1) -- a draft total isn't a
real committed value yet.
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import (
    delta_pct,
    fetch_lead_dim_map,
    get_compare_window,
    get_period_window,
    passes_dimension_filters,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    as_of_date = filters.get("as_of_date") or frappe.utils.today()
    period_type = filters.get("period_type") or "Monthly"
    compare_mode = filters.get("compare_mode") or "None"
    years_back = filters.get("years_back") or "1"

    cur_start, cur_end = get_period_window(period_type, as_of_date)
    cmp_start, cmp_end = get_compare_window(compare_mode, years_back, cur_start, cur_end, as_of_date)

    def value_by_unit(start, end):
        if not start:
            return {}
        q_rows = frappe.get_all(
            "Quotation",
            filters={"quotation_to": "Lead", "transaction_date": ["between", [start, end]], "docstatus": 1},
            fields=["party_name", "grand_total"],
            limit_page_length=0,
        )
        dim_map = fetch_lead_dim_map([r.party_name for r in q_rows if r.party_name])
        totals = {}
        for r in q_rows:
            if not r.party_name:
                continue
            lead_row = dim_map.get(r.party_name)
            if not passes_dimension_filters(lead_row, filters):
                continue
            unit = (lead_row.get("custom_business_lead_unit") if lead_row else None) or _("(not set)")
            totals[unit] = totals.get(unit, 0) + (r.grand_total or 0)
        return totals

    cur_totals = value_by_unit(cur_start, cur_end)
    cmp_totals = value_by_unit(cmp_start, cmp_end) if cmp_start else {}
    units = sorted(set(cur_totals) | set(cmp_totals), key=lambda u: cur_totals.get(u, 0), reverse=True)

    data = []
    for unit in units:
        cur_v = cur_totals.get(unit, 0.0)
        cmp_v = cmp_totals.get(unit, 0.0) if cmp_start else None
        data.append({
            "business_unit": unit,
            "current": cur_v,
            "comparison": cmp_v,
            "delta": (cur_v - cmp_v) if cmp_v is not None else None,
            "delta_pct": delta_pct(cur_v, cmp_v) if cmp_v is not None else None,
        })

    columns = [
        {"label": _("Business Unit"), "fieldname": "business_unit", "fieldtype": "Data", "width": 220},
        {"label": _("Current Period"), "fieldname": "current", "fieldtype": "Currency", "width": 150},
        {"label": _("Comparison Period"), "fieldname": "comparison", "fieldtype": "Currency", "width": 160},
        {"label": _("Δ"), "fieldname": "delta", "fieldtype": "Currency", "width": 120},
        {"label": _("Δ%"), "fieldname": "delta_pct", "fieldtype": "Percent", "width": 90},
    ]

    total_cur = sum(cur_totals.values())
    report_summary = [{"label": _("Total Quotation Value (Current)"), "value": total_cur, "datatype": "Currency", "indicator": "blue"}]
    if cmp_start:
        report_summary.append({"label": _("Total Quotation Value (Comparison)"), "value": sum(cmp_totals.values()), "datatype": "Currency"})

    chart_datasets = [{"name": _("Current"), "values": [r["current"] for r in data]}]
    if cmp_start:
        chart_datasets.append({"name": _("Comparison"), "values": [r["comparison"] or 0 for r in data]})
    chart = {
        "data": {"labels": [r["business_unit"] for r in data], "datasets": chart_datasets},
        "type": "bar",
    }

    message = _("Current period: {0} – {1}. Submitted Quotations only.").format(cur_start, cur_end)
    if cmp_start:
        message += " " + _("Comparison period: {0} – {1}.").format(cmp_start, cmp_end)

    return columns, data, message, chart, report_summary
