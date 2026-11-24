"""Shared engine behind the "AlphaX ... (BI)" report family — the live,
database-backed equivalent of the Lead Tracker BI Excel workbook: one period
engine (Daily/Weekly/.../Yearly + an optional prior-year comparison), reused
by every report in the family instead of each one reinventing it.

Design notes (why this looks the way it does):

* Lead Stage values (the native ``status`` field) are NOT hardcoded here.
  They come from the Select field's own options on whichever site this runs
  on (``get_lead_stage_options``), because this app lets that list be
  extended per-customer (``ensure_select_option`` / Lead Status -> Lead
  Stage Mapping) — a hardcoded stage list would silently go stale the next
  time someone adds a stage.
* "Movement into a stage during a period" comes from AlphaX Stage Transition
  Log (crm/activity.py: record_transition), which already timestamps every
  Lead Stage change — this is the event log a BI report needs; nothing new
  had to be added to capture it.
* The Log only stores reference_name, not the Lead's own dimension fields
  (owner/source/city/business unit/stage), so filtering by those means a
  second, bulk lookup against Lead and an in-Python join — the same
  python-side-aggregation style already used by this app's other reports
  (alphax_sales_pipeline_forecast.py, alphax_stage_duration_report.py)
  rather than a hand-rolled SQL JOIN.
"""

import calendar
import datetime

import frappe


PERIOD_TYPES = ["Daily", "Weekly", "Monthly", "Quarterly", "Half-Yearly", "Yearly"]
COMPARE_MODES = ["None", "Same Period Last Year", "Same Quarter Last Year", "Full Last Year"]


def _to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return frappe.utils.getdate(v)


def get_period_window(period_type, as_of_date, from_date=None, to_date=None):
    """Mirrors the Excel workbook's Section 2 formulas exactly (same period
    boundaries, same period types) so the two stay comparable.

    An explicit From Date/To Date pair (added in 0.35.1, after a non-technical
    user found "Period Type" + "As Of Date" unintuitive -- they wanted a
    plain date range that defaults to something non-empty) wins outright
    over Period Type/As Of Date when both are given: it's taken as the
    window verbatim, no snapping to calendar boundaries. Leave either one
    blank to fall back to the original Period Type behavior unchanged --
    existing saved filters/links with no From/To Date keep working exactly
    as before."""
    if from_date and to_date:
        return _to_date(from_date), _to_date(to_date)

    d = _to_date(as_of_date or frappe.utils.today())
    period_type = period_type or "Monthly"

    if period_type == "Daily":
        return d, d
    if period_type == "Weekly":
        start = d - datetime.timedelta(days=d.weekday())  # Monday
        return start, start + datetime.timedelta(days=6)
    if period_type == "Monthly":
        start = d.replace(day=1)
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        return start, end
    if period_type == "Quarterly":
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        start = d.replace(month=q_start_month, day=1)
        end_month = q_start_month + 2
        end = start.replace(month=end_month, day=calendar.monthrange(d.year, end_month)[1])
        return start, end
    if period_type == "Half-Yearly":
        start_month = 1 if d.month <= 6 else 7
        start = d.replace(month=start_month, day=1)
        end_month = start_month + 5
        end = start.replace(month=end_month, day=calendar.monthrange(d.year, end_month)[1])
        return start, end
    # Yearly
    return d.replace(month=1, day=1), d.replace(month=12, day=31)


def _shift_years(d, years):
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Feb 29 on a non-leap target year
        return d.replace(month=2, day=28, year=d.year - years)


def get_compare_window(compare_mode, years_back, cur_start, cur_end, as_of_date):
    years_back = int(years_back or 1)
    if not compare_mode or compare_mode == "None":
        return None, None
    if compare_mode == "Same Period Last Year":
        return _shift_years(cur_start, years_back), _shift_years(cur_end, years_back)
    if compare_mode == "Same Quarter Last Year":
        d = _to_date(as_of_date)
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        ref = d.replace(month=q_start_month, day=1)
        start = _shift_years(ref, years_back)
        end_month = start.month + 2
        end = start.replace(month=end_month, day=calendar.monthrange(start.year, end_month)[1])
        return start, end
    if compare_mode == "Full Last Year":
        d = _to_date(as_of_date)
        year = d.year - years_back
        return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    return None, None


def get_lead_stage_options():
    """Every non-blank value configured on Lead's native status field, in
    the order they're defined there -- NOT a hardcoded guess at stage
    names, since this app lets that list be extended per customer."""
    meta = frappe.get_meta("Lead")
    field = meta.get_field("status")
    if not field or not field.options:
        return []
    return [o.strip() for o in field.options.split("\n") if o.strip()]


def get_closure_values(settings=None):
    settings = settings or frappe.get_cached_doc("AlphaX CRM Settings")
    won = (settings.get("won_stage_value") or "Won").strip()
    lost = [s.strip() for s in (settings.get("lost_stage_values") or "").split(",") if s.strip()]
    postponed = (settings.get("postponed_stage_value") or "Postponed").strip()
    return won, lost, postponed


_BUSINESS_UNIT_FIELD = "custom_business_line_"


def business_unit_field():
    """Returns "custom_business_line_" only if that field is both
    declared on Lead's metadata AND physically present as a column in the
    live `tabLead` table on THIS site, else None.

    That fieldname came from this app's own crm/smart_lead.py default
    field-mapping table -- but that mapping is only a fallback, overridden
    per-site by AlphaX CRM Settings > Smart Lead Field Mapping, and a site
    that has never run Smart Lead sync (or that remapped this field under a
    different name, or never added it via Customize Form at all) may not
    have this column.

    v0.34.2 only checked meta.has_field(), which reads the *declared*
    fields (DocType JSON + any `Custom Field` records) -- and a real site
    hit exactly the gap that leaves open: a `Custom Field` record for
    "custom_business_line_" existed (so has_field() said yes), but the
    matching `ALTER TABLE ... ADD COLUMN` never completed (a migration
    that aborts partway through -- e.g. over an unrelated broken DocType --
    can leave Custom Field metadata committed without its column), so the
    query still crashed with "(1054, \"Unknown column ...\")" straight
    through a check that was supposed to prevent exactly that. Checking
    the live table's own columns (frappe.db.get_table_columns(), itself
    cached by frappe -- cheap to call) is the only way to know what a
    `SELECT` against this table can actually touch; metadata alone isn't
    enough. If the column check itself can't run for some reason, this
    falls back to trusting the metadata rather than silently hiding the
    dimension everywhere -- the same choice this function already made
    before this fix, just as a last resort rather than the only check."""
    if not frappe.get_meta("Lead").has_field(_BUSINESS_UNIT_FIELD):
        return None
    try:
        columns = frappe.db.get_table_columns("Lead")
    except Exception:
        return _BUSINESS_UNIT_FIELD
    return _BUSINESS_UNIT_FIELD if _BUSINESS_UNIT_FIELD in columns else None


_SUB_SERVICE_FIELD = "custom_sub_service"

# Business Unit (custom_business_line_) -> Sub Service choices, mirroring the
# Lead form's own client script, so the filter offers the full list even
# before every sub service has been used on a lead.
SUB_SERVICES_BY_UNIT = {
    "ALPHA X": ["SAAS", "PAAS", "ERP"],
    "AGRC Services": ["Internal Audit", "Governance", "Risk Management", "Compliance", "IT Audit"],
    "Accounting & Financial Outsourcing Projects": [
        "Preparation of Financial Budgets", "Preparation of Draft Financial Statements",
        "Accumulated Work", "Other"],
    "HR Outsourcing Services": [
        "Payroll Management and Employee Relations. Management of Government Platforms for Employees."],
    "HR Outsourcing Projects": [
        "Accumulated Work", "Management of Government Platforms for company",
        "Writing Policies and Procedures", "Other"],
    "Accounting & Financial Outsourcing": [
        "Bookkeeping and Accounting",
        "Accounting Supervision (Monthly Closures and Reconciliations)",
        "Financial Supervision (Accounting Supervision, Reports, and Financial Analysis)"],
    "Tax and Zakat Consultations": [
        "Preparation of Value Added Tax (VAT) Returns.",
        "Preparation of Withholding Tax Returns", "Tax and Zakat Consultations"],
    "Fixed Assets Projects Services": [
        "Inventory and Preparation of Asset Register",
        "Inventory, Preparation of Asset Register, Tagging, and Labeling"],
}


def usable_lead_field(fieldname):
    """fieldname if declared on Lead AND physically a column of tabLead, else
    None (same two-step check business_unit_field() documents above)."""
    if not frappe.get_meta("Lead").has_field(fieldname):
        return None
    try:
        columns = frappe.db.get_table_columns("Lead")
    except Exception:
        return fieldname
    return fieldname if fieldname in columns else None


def sub_service_field():
    return usable_lead_field(_SUB_SERVICE_FIELD)


# The Lead form stores each lead's Business Unit / Sub Service pairs as ROWS
# of the "Lead Business Unit" child table (Lead.custom_business_lead_unit);
# the single-value Lead.custom_business_line_ / custom_sub_service fields are
# the older, flat version. A lead counts under a Business Unit / Sub Service
# if EITHER holds it -- these helpers read the child rows (tolerating a site
# where that child table doesn't exist) and merge them in.
_UNIT_CHILD = "Lead Business Unit"


def _unit_child_rows(extra_filters=None, fields=None):
    try:
        filters = {"parenttype": "Lead", "parentfield": "custom_business_lead_unit"}
        filters.update(extra_filters or {})
        return frappe.get_all(_UNIT_CHILD, filters=filters,
                              fields=fields or ["parent", "custom_business_line_", "custom_sub_service"],
                              order_by="idx asc", limit_page_length=0)
    except Exception:
        return []


def unit_filter_names(filters):
    """Lead names matching the Business Unit and/or Sub Service filter (on
    either the Lead's own field or any child row -- the same row must match
    both when both are chosen), or None when neither filter is set. Cached on
    the filters object so it is computed once per report run."""
    bu = filters.get("custom_business_line_")
    ss = filters.get("custom_sub_service")
    if not bu and not ss:
        return None
    cache = filters.get("_unit_names")
    if cache is not None:
        return cache
    names = set()
    child_filters = {}
    direct = {}
    if bu:
        child_filters["custom_business_line_"] = bu
        if business_unit_field():
            direct[business_unit_field()] = bu
    if ss:
        child_filters["custom_sub_service"] = ss
        if sub_service_field():
            direct[sub_service_field()] = ss
    names.update(r.get("parent") for r in _unit_child_rows(child_filters, ["parent"]))
    # Direct match only counts when every chosen filter has a usable Lead column.
    if len(direct) == len(child_filters) and direct:
        names.update(r.name for r in frappe.get_all("Lead", filters=direct, fields=["name"], limit_page_length=0))
    try:
        filters["_unit_names"] = names
    except Exception:
        pass
    return names


def unit_fallback_map(lead_names):
    """{lead: (business_unit, sub_service)} from each lead's first child row,
    to fill in leads whose flat fields are blank."""
    if not lead_names:
        return {}
    out = {}
    for r in _unit_child_rows({"parent": ["in", list(set(lead_names))]}):
        out.setdefault(r.get("parent"), (r.get("custom_business_line_"), r.get("custom_sub_service")))
    return out


def lead_dimension_filters(filters):
    """Direct frappe.get_all filter dict for querying Lead itself (used for
    the New Leads metric, and for Report 2's current-snapshot stage
    counts). Does not include the Lead Stage (status) filter -- callers
    that need to scope to one stage add "status" themselves."""
    conditions = {}
    for fieldname in ("lead_owner", "source", "city", "country"):
        if filters.get(fieldname):
            conditions[fieldname] = filters.get(fieldname)
    names = unit_filter_names(filters)
    if names is not None:
        conditions["name"] = ["in", list(names) or ["__no_match__"]]
    return conditions


def fetch_lead_dim_map(lead_names, extra_fields=None):
    """Bulk-fetch dimension fields for a batch of Lead names, for the
    in-Python join against AlphaX Stage Transition Log / Quotation rows
    (the Log and Quotation don't carry owner/source/city/country/business
    unit themselves). "country" is Lead's native field (standard ERPNext,
    Link to Country) -- a real master doctype, unlike Business Unit."""
    if not lead_names:
        return {}
    fields = ["name", "lead_owner", "source", "city", "country", "status",
              "custom_lead_status", "lost_reason", "detailed_reason"]
    bu_field = business_unit_field()
    if bu_field:
        fields.append(bu_field)
    ss_field = sub_service_field()
    if ss_field:
        fields.append(ss_field)
    if extra_fields:
        fields = list(dict.fromkeys(fields + extra_fields))
    rows = frappe.get_all(
        "Lead",
        filters={"name": ["in", list(set(lead_names))]},
        fields=fields,
        limit_page_length=0,
    )
    out = {r.name: r for r in rows}
    fallback = unit_fallback_map(list(out))
    for name, row in out.items():
        bu, ss = fallback.get(name, (None, None))
        if not row.get("custom_business_line_") and bu:
            row["custom_business_line_"] = bu
        if not row.get("custom_sub_service") and ss:
            row["custom_sub_service"] = ss
    return out


def passes_dimension_filters(lead_row, filters):
    """Python-side equivalent of lead_dimension_filters(), applied after the
    bulk Lead lookup above, for rows that originated from the Log/Quotation
    rather than from a direct Lead query."""
    if not lead_row:
        return False
    checks = [
        ("lead_owner", "lead_owner"),
        ("source", "source"),
        ("city", "city"),
        ("country", "country"),
    ]
    names = unit_filter_names(filters)
    if names is not None and lead_row.get("name") not in names:
        return False
    for filter_key, lead_key in checks:
        want = filters.get(filter_key)
        if want and (lead_row.get(lead_key) or "") != want:
            return False
    return True


@frappe.whitelist()
def get_business_unit_options():
    """Distinct, non-blank values of Lead.custom_business_line_ on this
    site, for populating the "Business Unit" filter as a dropdown of values
    actually in use -- there's no proper master doctype to search instead
    (see business_unit_field()'s docstring: that field's only plausible
    Link target, "AlphaX Business Unit", is a child table with no
    standalone list of its own). Returns [] whenever the field isn't
    usable (declared but no physical column, or not declared at all) --
    same "just show nothing to filter by" fallback every other BI report
    already uses for this field, rather than erroring the filter dropdown."""
    bu_field = business_unit_field()
    values = set()
    if bu_field:
        rows = frappe.get_all(
            "Lead",
            filters={bu_field: ["is", "set"]},
            fields=[bu_field],
            distinct=True,
            limit_page_length=0,
        )
        values.update(r.get(bu_field) for r in rows if r.get(bu_field))
        # custom_business_line_ is a Select ("Service Need"), so also offer its
        # declared options -- complete even before a value has been used.
        try:
            opts = frappe.get_meta("Lead").get_field(bu_field).options or ""
            values.update(o.strip() for o in opts.split("\n") if o.strip())
        except Exception:
            pass
    values.update(r.get("custom_business_line_") for r in
                  _unit_child_rows(fields=["custom_business_line_"]) if r.get("custom_business_line_"))
    return sorted(values)


@frappe.whitelist()
def get_sub_service_options(business_unit=None):
    """Sub Service choices for the filter dropdown: the known list for the
    selected Business Unit (or all of them), plus any values actually in use
    on Leads. [] if the field isn't usable on this site."""
    ss_field = sub_service_field()
    values = set()
    if business_unit:
        values.update(SUB_SERVICES_BY_UNIT.get(business_unit, []))
    elif ss_field or _unit_child_rows(fields=["parent"]):
        for opts in SUB_SERVICES_BY_UNIT.values():
            values.update(opts)
    if ss_field:
        conditions = {ss_field: ["is", "set"]}
        bu_field = business_unit_field()
        if business_unit and bu_field:
            conditions[bu_field] = business_unit
        rows = frappe.get_all("Lead", filters=conditions, fields=[ss_field],
                              distinct=True, limit_page_length=0)
        values.update(r.get(ss_field) for r in rows if r.get(ss_field))
    child_filters = {"custom_business_line_": business_unit} if business_unit else {}
    values.update(r.get("custom_sub_service") for r in
                  _unit_child_rows(child_filters, ["custom_sub_service"]) if r.get("custom_sub_service"))
    return sorted(values)


def period_label(period_type, cur_start, cur_end, compare_mode, cmp_start, cmp_end, years_back):
    cur = f"{period_type} ({cur_start} to {cur_end})"
    if not compare_mode or compare_mode == "None":
        return cur, None
    cmp_label = f"{compare_mode}, {years_back}y back ({cmp_start} to {cmp_end})"
    return cur, cmp_label


def delta_pct(current, comparison):
    if comparison in (None, 0):
        return None
    return round(((current - comparison) / comparison) * 100.0, 1)


def grouped_performance(filters, group_field, cur_start, cur_end, cmp_start, cmp_end, won, lost_list):
    """Shared engine behind the "... Performance (BI)" report family (Sales
    Person Performance, Source Performance): tallies New Leads / Won / Lost
    / Quotation Value for the current (and, if set, comparison) period,
    broken down by one Lead dimension field at a time (``group_field`` --
    e.g. "lead_owner" or "source") instead of collapsed into one grand
    total the way the other BI reports are.

    The report's own filter bar (Sales Person/Source/City/Business Unit)
    still narrows the underlying Leads/transitions/Quotations first via
    lead_dimension_filters()/passes_dimension_filters(); group_field is only
    which column the *results* get bucketed by, so filtering by Source while
    grouping by Sales Person (say) works exactly as expected.

    Returns {group_value: {"new_cur", "new_cmp", "won_cur", "won_cmp",
    "lost_cur", "lost_cmp", "qv_cur", "qv_cmp"}}; the _cmp keys are None
    throughout when no comparison period is set, same convention as the
    rest of this report family.
    """
    base_conditions = lead_dimension_filters(filters)

    def new_leads_by_group(start, end):
        if not start:
            return {}
        dt_start, dt_end = datetime_range(start, end)
        conditions = dict(base_conditions)
        conditions["creation"] = ["between", [dt_start, dt_end]]
        rows = frappe.get_all("Lead", filters=conditions, fields=[group_field], limit_page_length=0)
        counts = {}
        for r in rows:
            key = r.get(group_field) or "(not set)"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def stage_counts_by_group(start, end):
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
            fields=["reference_name", "to_value"],
            limit_page_length=0,
        )
        dim_map = fetch_lead_dim_map([r.reference_name for r in log_rows])
        won_counts, lost_counts = {}, {}
        for r in log_rows:
            lead_row = dim_map.get(r.reference_name)
            if not passes_dimension_filters(lead_row, filters):
                continue
            key = (lead_row.get(group_field) if lead_row else None) or "(not set)"
            if r.to_value == won:
                won_counts[key] = won_counts.get(key, 0) + 1
            elif r.to_value in lost_list:
                lost_counts[key] = lost_counts.get(key, 0) + 1
        return won_counts, lost_counts

    def quotation_value_by_group(start, end):
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
            key = (lead_row.get(group_field) if lead_row else None) or "(not set)"
            totals[key] = totals.get(key, 0) + (r.grand_total or 0)
        return totals

    new_cur = new_leads_by_group(cur_start, cur_end)
    new_cmp = new_leads_by_group(cmp_start, cmp_end) if cmp_start else {}
    won_cur, lost_cur = stage_counts_by_group(cur_start, cur_end)
    won_cmp, lost_cmp = stage_counts_by_group(cmp_start, cmp_end) if cmp_start else ({}, {})
    qv_cur = quotation_value_by_group(cur_start, cur_end)
    qv_cmp = quotation_value_by_group(cmp_start, cmp_end) if cmp_start else {}

    groups = set(new_cur) | set(won_cur) | set(lost_cur) | set(qv_cur)
    if cmp_start:
        groups |= set(new_cmp) | set(won_cmp) | set(lost_cmp) | set(qv_cmp)

    result = {}
    for key in groups:
        result[key] = {
            "new_cur": new_cur.get(key, 0),
            "new_cmp": new_cmp.get(key, 0) if cmp_start else None,
            "won_cur": won_cur.get(key, 0),
            "won_cmp": won_cmp.get(key, 0) if cmp_start else None,
            "lost_cur": lost_cur.get(key, 0),
            "lost_cmp": lost_cmp.get(key, 0) if cmp_start else None,
            "qv_cur": qv_cur.get(key, 0),
            "qv_cmp": qv_cmp.get(key, 0) if cmp_start else None,
        }
    return result


def datetime_range(start, end):
    """("between") bounds for a *Datetime* field (changed_on, creation) given
    plain period-window dates. A bare "2026-10-31" is read as midnight, which
    would silently drop every event later that day -- so the end bound is
    pushed to the last second of that day. Date-only fields (transaction_date,
    won_or_lost_date) don't need this; pass them straight to "between"."""
    if not start:
        return None, None
    return f"{start} 00:00:00", f"{end} 23:59:59"
