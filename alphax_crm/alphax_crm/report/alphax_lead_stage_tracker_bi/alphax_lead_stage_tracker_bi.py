"""AlphaX Lead Stage Tracker (BI) — the live, database-backed equivalent of
the "Lead Tracker BI Report" Excel workbook's Report tab: one Period Type
selector (Daily/Weekly/Monthly/Quarterly/Half-Yearly/Yearly), an optional
comparison (Same Period Last Year / Same Quarter Last Year / Full Last
Year, 1-3 years back), and a stage-by-stage funnel for the selected window.

Data sources (see crm/bi_report.py for why):
  * Movement into each Lead Stage during the period -> AlphaX Stage
    Transition Log (already populated by crm.activity.record_transition
    every time Lead Stage changes).
  * New Leads -> Lead.creation falling inside the period.
  * Quotation Value -> submitted Quotation documents (quotation_to="Lead")
    whose transaction_date falls inside the period.
Every count respects the Sales Person / Source / City / Business Unit
filters, resolved via an in-Python join since the Log and Quotation don't
carry those dimension fields themselves.
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import (
    datetime_range,
    delta_pct,
    fetch_lead_dim_map,
    get_closure_values,
    get_compare_window,
    get_lead_stage_options,
    get_period_window,
    lead_dimension_filters,
    passes_dimension_filters,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    as_of_date = filters.get("as_of_date") or frappe.utils.today()
    period_type = filters.get("period_type") or "Monthly"
    compare_mode = filters.get("compare_mode") or "None"
    years_back = filters.get("years_back") or "1"

    cur_start, cur_end = get_period_window(period_type, as_of_date, filters.get("from_date"), filters.get("to_date"))
    cmp_start, cmp_end = get_compare_window(compare_mode, years_back, cur_start, cur_end, as_of_date)

    stages = get_lead_stage_options()
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    won, lost_list, _postponed = get_closure_values(settings)

    def movement_counts(start, end):
        if not start:
            return {}
        dt_start, dt_end = datetime_range(start, end)
        log_rows = frappe.get_all(
            "AlphaX Stage Transition Log",
            filters={
                "reference_doctype": "Lead",
                "field_label": "Lead Stage",
                "changed_on": ["between", [dt_start, dt_end]],
            },
            fields=["reference_name", "to_value"],
            limit_page_length=0,
        )
        dim_map = fetch_lead_dim_map([r.reference_name for r in log_rows])
        counts = {}
        for r in log_rows:
            if not passes_dimension_filters(dim_map.get(r.reference_name), filters):
                continue
            counts[r.to_value] = counts.get(r.to_value, 0) + 1
        return counts

    def new_lead_count(start, end):
        if not start:
            return 0
        dt_start, dt_end = datetime_range(start, end)
        conditions = lead_dimension_filters(filters)
        conditions["creation"] = ["between", [dt_start, dt_end]]
        return frappe.db.count("Lead", conditions)

    def quotation_value(start, end):
        if not start:
            return 0.0
        q_rows = frappe.get_all(
            "Quotation",
            filters={
                "quotation_to": "Lead",
                "transaction_date": ["between", [start, end]],
                "docstatus": 1,
            },
            fields=["party_name", "grand_total"],
            limit_page_length=0,
        )
        dim_map = fetch_lead_dim_map([r.party_name for r in q_rows if r.party_name])
        total = 0.0
        for r in q_rows:
            if not r.party_name or not passes_dimension_filters(dim_map.get(r.party_name), filters):
                continue
            total += r.grand_total or 0
        return total

    cur_counts = movement_counts(cur_start, cur_end)
    cmp_counts = movement_counts(cmp_start, cmp_end) if cmp_start else {}
    cur_new = new_lead_count(cur_start, cur_end)
    cmp_new = new_lead_count(cmp_start, cmp_end) if cmp_start else None
    cur_qv = quotation_value(cur_start, cur_end)
    cmp_qv = quotation_value(cmp_start, cmp_end) if cmp_start else None

    data = [{
        "stage": _("New Leads"),
        "current": cur_new,
        "comparison": cmp_new,
        "delta": (cur_new - cmp_new) if cmp_new is not None else None,
        "delta_pct": delta_pct(cur_new, cmp_new) if cmp_new is not None else None,
    }]
    for stage in stages:
        cur_v = cur_counts.get(stage, 0)
        cmp_v = cmp_counts.get(stage, 0) if cmp_start else None
        data.append({
            "stage": stage,
            "current": cur_v,
            "comparison": cmp_v,
            "delta": (cur_v - cmp_v) if cmp_v is not None else None,
            "delta_pct": delta_pct(cur_v, cmp_v) if cmp_v is not None else None,
        })

    columns = [
        {"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 220},
        {"label": _("Current Period"), "fieldname": "current", "fieldtype": "Int", "width": 130},
        {"label": _("Comparison Period"), "fieldname": "comparison", "fieldtype": "Int", "width": 150},
        {"label": _("Δ"), "fieldname": "delta", "fieldtype": "Int", "width": 90},
        {"label": _("Δ%"), "fieldname": "delta_pct", "fieldtype": "Percent", "width": 90},
    ]

    won_cur = cur_counts.get(won, 0)
    won_cmp = cmp_counts.get(won, 0) if cmp_start else None
    lost_cur = sum(cur_counts.get(s, 0) for s in lost_list)
    lost_cmp = sum(cmp_counts.get(s, 0) for s in lost_list) if cmp_start else None

    report_summary = [
        {"label": _("New Leads"), "value": cur_new, "indicator": "blue"},
        {"label": _("Won"), "value": won_cur, "indicator": "green"},
        {"label": _("Lost"), "value": lost_cur, "indicator": "red"},
        {"label": _("Quotation Value"), "value": cur_qv, "datatype": "Currency", "indicator": "blue"},
    ]
    if cmp_start:
        report_summary.extend([
            {"label": _("New Leads (Comparison)"), "value": cmp_new},
            {"label": _("Won (Comparison)"), "value": won_cmp},
            {"label": _("Lost (Comparison)"), "value": lost_cmp},
            {"label": _("Quotation Value (Comparison)"), "value": cmp_qv, "datatype": "Currency"},
        ])

    chart_datasets = [{"name": _("Current"), "values": [r["current"] for r in data]}]
    if cmp_start:
        chart_datasets.append({"name": _("Comparison"), "values": [r["comparison"] or 0 for r in data]})
    chart = {
        "data": {"labels": [r["stage"] for r in data], "datasets": chart_datasets},
        "type": "bar",
    }

    message = _("Current period: {0} – {1}.").format(cur_start, cur_end)
    if cmp_start:
        message += " " + _("Comparison period: {0} – {1}.").format(cmp_start, cmp_end)

    return columns, data, message, chart, report_summary
