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
