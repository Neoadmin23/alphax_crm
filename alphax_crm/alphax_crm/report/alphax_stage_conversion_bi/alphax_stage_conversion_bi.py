"""AlphaX Stage Conversion (BI) — how much Lead Stage movement happened
during the selected period, stage by stage: how many Leads moved INTO each
stage ("Entered"), how many moved back OUT of it to any other stage
("Exited"), and what share of that stage's traffic moved on ("Exit Rate").

Both counts come straight from AlphaX Stage Transition Log's own
``from_value``/``to_value`` columns (the same event log the rest of the BI
report family is built on) -- no new tracking needed, and no guess at which
order the configured stages represent a "pipeline" in, since this app lets
Postponed/Lost/Won sit as side-branches rather than a strict linear funnel
(see AlphaX CRM Settings > Stage Transitions for the actual configured
from-stage/to-stage edges, which this report does not need to read because
the Log already records which edge each individual move took).

"Exit Rate" divides Exited by Entered **within the same period** -- a
period-aligned activity ratio (consistent with how New Leads vs Won/Lost are
already compared elsewhere in this report family), not a same-cohort,
lifetime-true conversion rate: a Lead that entered a stage near the end of
the period may not yet have had time to exit it, and a Lead exiting during
the period may have entered it in an earlier period. The report says so in
its message rather than overstating what a period-bound count can prove.

The headline "Lead-to-Won %" / "Lead-to-Lost %" summary cards use the same
period-aligned convention as AlphaX Lead Stage Tracker BI (Won/Lost counts
against New Leads in the same period), so the two reports' top-line
percentages stay directly comparable.
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

    def movement(start, end):
        """Returns (entered_counts, exited_counts), both keyed by stage
        name, from the Log's to_value/from_value respectively, filtered to
        Leads matching the report's own dimension filters."""
        if not start:
            return {}, {}
        dt_start, dt_end = datetime_range(start, end)
        log_rows = frappe.get_all(
            "AlphaX Stage Transition Log",
            filters={
                "reference_doctype": "Lead",
                "field_label": "Lead Stage",
                "changed_on": ["between", [dt_start, dt_end]],
            },
            fields=["reference_name", "from_value", "to_value"],
            limit_page_length=0,
        )
        dim_map = fetch_lead_dim_map([r.reference_name for r in log_rows])
        entered, exited = {}, {}
        for r in log_rows:
            if not passes_dimension_filters(dim_map.get(r.reference_name), filters):
                continue
            if r.to_value:
                entered[r.to_value] = entered.get(r.to_value, 0) + 1
            if r.from_value:
                exited[r.from_value] = exited.get(r.from_value, 0) + 1
        return entered, exited

    def new_lead_count(start, end):
        if not start:
            return None
        dt_start, dt_end = datetime_range(start, end)
        conditions = lead_dimension_filters(filters)
        conditions["creation"] = ["between", [dt_start, dt_end]]
        return frappe.db.count("Lead", conditions)

    entered_cur, exited_cur = movement(cur_start, cur_end)
    entered_cmp, exited_cmp = movement(cmp_start, cmp_end) if cmp_start else ({}, {})

    data = []
    for stage in stages:
        e_cur = entered_cur.get(stage, 0)
        x_cur = exited_cur.get(stage, 0)
        e_cmp = entered_cmp.get(stage, 0) if cmp_start else None
        x_cmp = exited_cmp.get(stage, 0) if cmp_start else None
        rate_cur = round((x_cur / e_cur) * 100.0, 1) if e_cur else None
        rate_cmp = (round((x_cmp / e_cmp) * 100.0, 1) if e_cmp else None) if cmp_start else None
        data.append({
            "stage": stage,
            "entered": e_cur,
            "entered_cmp": e_cmp,
            "exited": x_cur,
            "exited_cmp": x_cmp,
            "exit_rate": rate_cur,
            "exit_rate_cmp": rate_cmp,
            "exit_rate_delta_pct": delta_pct(rate_cur, rate_cmp) if (cmp_start and rate_cur is not None and rate_cmp) else None,
        })
    # Only show stages with some traffic in either window, to keep a
    # customer's inactive/retired stage values from cluttering the report.
    data = [row for row in data if row["entered"] or row["exited"] or (row["entered_cmp"] or row["exited_cmp"])]

    columns = [
        {"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 200},
        {"label": _("Entered"), "fieldname": "entered", "fieldtype": "Int", "width": 100},
        {"label": _("Entered (Comparison)"), "fieldname": "entered_cmp", "fieldtype": "Int", "width": 150},
        {"label": _("Exited"), "fieldname": "exited", "fieldtype": "Int", "width": 100},
        {"label": _("Exited (Comparison)"), "fieldname": "exited_cmp", "fieldtype": "Int", "width": 150},
        {"label": _("Exit Rate %"), "fieldname": "exit_rate", "fieldtype": "Percent", "width": 110},
        {"label": _("Exit Rate % (Comparison)"), "fieldname": "exit_rate_cmp", "fieldtype": "Percent", "width": 170},
    ]

    cur_new = new_lead_count(cur_start, cur_end) or 0
    cmp_new = new_lead_count(cmp_start, cmp_end) if cmp_start else None
    won_cur = entered_cur.get(won, 0)
    lost_cur = sum(entered_cur.get(s, 0) for s in lost_list)
    won_cmp = entered_cmp.get(won, 0) if cmp_start else None
    lost_cmp = sum(entered_cmp.get(s, 0) for s in lost_list) if cmp_start else None

    report_summary = [
        {"label": _("New Leads"), "value": cur_new, "indicator": "blue"},
        {
            "label": _("Lead-to-Won %"),
            "value": round((won_cur / cur_new) * 100.0, 1) if cur_new else 0,
            "indicator": "green",
        },
        {
            "label": _("Lead-to-Lost %"),
            "value": round((lost_cur / cur_new) * 100.0, 1) if cur_new else 0,
            "indicator": "red",
        },
    ]
    if cmp_start:
        report_summary.append({
            "label": _("Lead-to-Won % (Comparison)"),
            "value": round((won_cmp / cmp_new) * 100.0, 1) if cmp_new else 0,
        })

    chart = {
        "data": {
            "labels": [r["stage"] for r in data],
            "datasets": [
                {"name": _("Entered"), "values": [r["entered"] for r in data]},
                {"name": _("Exited"), "values": [r["exited"] for r in data]},
            ],
        },
        "type": "bar",
    }

    message = _("Current period: {0} – {1}.").format(cur_start, cur_end)
    if cmp_start:
        message += " " + _("Comparison period: {0} – {1}.").format(cmp_start, cmp_end)
    message += " " + _(
        "Exit Rate compares moves out of a stage to moves into it within the same period -- a "
        "period-aligned activity ratio, not a same-cohort lifetime conversion rate."
    )

    return columns, data, message, chart, report_summary
