"""AlphaX BI Dashboard — the master screen unifying the whole "AlphaX ...
(BI)" report family (crm/bi_report.py) into one tabbed page, instead of
leaving each report only reachable one at a time from the Report List.

This module does not recompute anything: it is a thin dispatcher that
calls each report's own, already-tested execute() function server-side
with one shared filter payload (As Of Date / Period Type / Compare Mode /
Years Back / Sales Person / Source / City / Business Unit) and returns
every report's (columns, data, message, chart, report_summary) tuple in
one combined JSON response, keyed by a short id the page's JS uses to pick
which tab to render it into. Keeping all the real logic in the reports
themselves means this dashboard can never drift out of sync with what
running the report directly would show -- there is exactly one
implementation of each metric, not two.
"""

import frappe
from frappe import _

from alphax_crm.alphax_crm.report.alphax_lead_stage_tracker_bi import (
    alphax_lead_stage_tracker_bi,
)
from alphax_crm.alphax_crm.report.alphax_pipeline_aging_bi import alphax_pipeline_aging_bi
from alphax_crm.alphax_crm.report.alphax_lost_reason_breakdown_bi import (
    alphax_lost_reason_breakdown_bi,
)
from alphax_crm.alphax_crm.report.alphax_quotation_value_by_business_unit_bi import (
    alphax_quotation_value_by_business_unit_bi,
)
from alphax_crm.alphax_crm.report.alphax_stage_conversion_bi import alphax_stage_conversion_bi
from alphax_crm.alphax_crm.report.alphax_sales_person_performance_bi import (
    alphax_sales_person_performance_bi,
)
from alphax_crm.alphax_crm.report.alphax_source_performance_bi import (
    alphax_source_performance_bi,
)

# id -> (report module, report_name as it appears in the Report list, needs
# the period/compare filters or just as_of_date + dimensions).
_REPORTS = [
    ("lead_stage_tracker", _("Lead Stage Tracker"), alphax_lead_stage_tracker_bi, True),
    ("pipeline_aging", _("Pipeline Aging"), alphax_pipeline_aging_bi, False),
    ("lost_reason_breakdown", _("Lost Reason Breakdown"), alphax_lost_reason_breakdown_bi, True),
    ("quotation_value_by_bu", _("Quotation Value by Business Unit"), alphax_quotation_value_by_business_unit_bi, True),
    ("stage_conversion", _("Stage Conversion"), alphax_stage_conversion_bi, True),
    ("sales_person_performance", _("Sales Person Performance"), alphax_sales_person_performance_bi, True),
    ("source_performance", _("Source Performance"), alphax_source_performance_bi, True),
]


def _require_management():
    roles = frappe.get_roles()
    if not ({"Sales User", "Sales Manager", "System Manager"} & set(roles)):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_bi_dashboard_data(
    from_date=None,
    to_date=None,
    as_of_date=None,
    period_type=None,
    compare_mode=None,
    years_back=None,
    lead_owner=None,
    source=None,
    city=None,
    country=None,
    custom_business_line_=None,
    custom_sub_service=None,
):
    """One combined payload for every report in the family, built from a
    single shared filter bar on the dashboard page. Pipeline Aging ignores
    from_date/to_date/period_type/compare_mode/years_back (it only ever
    reads as of a single date), same as it does when run as a standalone
    report. from_date/to_date, when both given, win outright over
    period_type/as_of_date in every other report -- see
    bi_report.get_period_window()."""
    _require_management()

    filters = frappe._dict({
        "from_date": from_date,
        "to_date": to_date,
        "as_of_date": as_of_date or frappe.utils.today(),
        "period_type": period_type or "Monthly",
        "compare_mode": compare_mode or "None",
        "years_back": years_back or "1",
        "lead_owner": lead_owner,
        "source": source,
        "city": city,
        "country": country,
        "custom_business_line_": custom_business_line_,
        "custom_sub_service": custom_sub_service,
    })

    out = {}
    for report_id, label, module, _uses_period in _REPORTS:
        try:
            columns, data, message, chart, report_summary = module.execute(filters)
            out[report_id] = {
                "label": label,
                "columns": columns,
                "data": data,
                "message": message,
                "chart": chart,
                "summary": report_summary,
                "error": None,
            }
        except Exception:
            # One report failing (e.g. a site-specific field/customization
            # issue) should not blank out the other six tabs -- show that
            # tab's own error instead of the whole dashboard breaking.
            frappe.log_error(title=f"AlphaX BI Dashboard: {label} failed")
            out[report_id] = {
                "label": label,
                "columns": [],
                "data": [],
                "message": None,
                "chart": None,
                "summary": [],
                "error": _("This report could not be loaded. Check the Error Log for details."),
            }

    return out


# ---------------------------------------------------------------------------
# Pivot Explorer -- Power-BI-style "pick rows / columns / measure" analysis
# ---------------------------------------------------------------------------
# Dimension id -> Lead fieldname. Only dimensions that are real columns on
# this site's tabLead are offered (checked at call time).
_PIVOT_DIMENSIONS = {
    "lead_owner": ("Sales Person", "lead_owner"),
    "source": ("Source", "source"),
    "city": ("City", "city"),
    "country": ("Country", "country"),
    "custom_business_line_": ("Business Unit", "custom_business_line_"),
    "custom_sub_service": ("Sub Service", "custom_sub_service"),
    "status": ("Lead Stage", "status"),
    "custom_lead_status": ("Lead Status", "custom_lead_status"),
    "custom_company_type": ("Company Type", "custom_company_type"),
    "industry": ("Industry", "industry"),
    "month": ("Created Month", "creation"),
    "year": ("Created Year", "creation"),
}
_PIVOT_MEASURES = {
    "leads": _("Leads"),
    "won": _("Won"),
    "lost": _("Lost"),
    "win_rate": _("Win Rate %"),
}


@frappe.whitelist()
def get_pivot_options():
    _require_management()
    columns = set(frappe.db.get_table_columns("Lead"))
    dims = [
        {"id": k, "label": _(v[0])}
        for k, v in _PIVOT_DIMENSIONS.items()
        if v[1] in columns
    ]
    return {
        "dimensions": dims,
        "measures": [{"id": k, "label": v} for k, v in _PIVOT_MEASURES.items()],
    }


def _dim_value(row, dim_id, fieldname):
    val = row.get(fieldname)
    if dim_id == "month":
        return str(val)[:7] if val else _("(not set)")
    if dim_id == "year":
        return str(val)[:4] if val else _("(not set)")
    return val or _("(not set)")


@frappe.whitelist()
def get_pivot_data(
    rows_dim="source",
    cols_dim=None,
    measure="leads",
    from_date=None,
    to_date=None,
    lead_owner=None,
    source=None,
    city=None,
    country=None,
    custom_business_line_=None,
    custom_sub_service=None,
):
    """Cross-tab of Leads: `rows_dim` down the side, optional `cols_dim`
    across the top, one `measure` in the cells. Filtered by the same shared
    filter bar as the other tabs (Leads created between from_date/to_date)."""
    _require_management()
    if rows_dim not in _PIVOT_DIMENSIONS:
        frappe.throw(_("Unknown row dimension"))
    if cols_dim and cols_dim not in _PIVOT_DIMENSIONS:
        frappe.throw(_("Unknown column dimension"))
    if measure not in _PIVOT_MEASURES:
        frappe.throw(_("Unknown measure"))

    from alphax_crm.crm.bi_report import get_closure_values

    table_cols = set(frappe.db.get_table_columns("Lead"))
    needed = {"name", "status", _PIVOT_DIMENSIONS[rows_dim][1]}
    if cols_dim:
        needed.add(_PIVOT_DIMENSIONS[cols_dim][1])
    fields = sorted(f for f in needed if f in table_cols)

    conditions = {}
    if from_date and to_date:
        conditions["creation"] = ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]
    elif from_date:
        conditions["creation"] = [">=", f"{from_date} 00:00:00"]
    elif to_date:
        conditions["creation"] = ["<=", f"{to_date} 23:59:59"]
    for fieldname, value in (
        ("lead_owner", lead_owner), ("source", source), ("city", city), ("country", country),
        ("custom_business_line_", custom_business_line_),
        ("custom_sub_service", custom_sub_service),
    ):
        if value and fieldname in table_cols:
            conditions[fieldname] = value

    leads = frappe.get_all("Lead", filters=conditions, fields=fields, limit_page_length=0)
    won_stage, lost_stages, _postponed = get_closure_values()
    lost_set = set(lost_stages)

    r_name, r_field = _PIVOT_DIMENSIONS[rows_dim]
    cells = {}
    row_keys, col_keys = set(), set()
    for lead in leads:
        rk = _dim_value(lead, rows_dim, r_field)
        ck = _dim_value(lead, cols_dim, _PIVOT_DIMENSIONS[cols_dim][1]) if cols_dim else "_"
        row_keys.add(rk)
        col_keys.add(ck)
        bucket = cells.setdefault((rk, ck), {"leads": 0, "won": 0, "lost": 0})
        bucket["leads"] += 1
        if lead.get("status") == won_stage:
            bucket["won"] += 1
        elif lead.get("status") in lost_set:
            bucket["lost"] += 1

    def value(bucket):
        if not bucket:
            return 0
        if measure == "win_rate":
            return round(bucket["won"] * 100.0 / bucket["leads"], 1) if bucket["leads"] else 0
        return bucket[measure]

    row_list = sorted(row_keys)
    col_list = sorted(col_keys)
    matrix = [[value(cells.get((r, c))) for c in col_list] for r in row_list]
    # Row totals ordering (biggest first) reads better in a chart.
    totals = [sum(v for v in line) for line in matrix]
    order = sorted(range(len(row_list)), key=lambda i: -totals[i])
    return {
        "row_label": _(r_name),
        "col_label": _(_PIVOT_DIMENSIONS[cols_dim][0]) if cols_dim else None,
        "measure_label": _PIVOT_MEASURES[measure],
        "rows": [row_list[i] for i in order],
        "cols": [] if not cols_dim else col_list,
        "matrix": [matrix[i] if cols_dim else [matrix[i][0]] for i in order],
        "total_leads": len(leads),
    }
