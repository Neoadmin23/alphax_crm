"""AlphaX Pipeline Aging (BI) — live equivalent of the Excel workbook's
"Current Pipeline Aging" section: how many Leads were sitting in each Lead
Stage as of a chosen date, and how long they'd been there.

"As Of Date" (defaults to today) reconstructs each Lead's stage AT THAT
DATE from its full "Lead Stage" transition history in AlphaX Stage
Transition Log — not just the single latest-ever entry — by taking the
latest transition with changed_on <= As Of Date. A Lead created after the
As Of Date is excluded outright (it didn't exist yet). A Lead that existed
by the As Of Date but has no logged transition at or before it (created
before this app started tracking transitions, or never had its Lead
Status/Stage touched since) is assumed to have still been on its
as-shipped default stage ("Lead", ERPNext's own default for a new Lead) —
an honest estimate, not a logged fact, and the report says so.

Day-count is time between that reconstructed stage's start (the matching
transition's changed_on, or the Lead's creation when no transition
applies) and the As Of Date itself (or the live current moment, if As Of
Date is today, for second-level precision rather than rounding to
midnight).
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import get_lead_stage_options, lead_dimension_filters


def execute(filters=None):
    filters = frappe._dict(filters or {})
    as_of_date = frappe.utils.getdate(filters.get("as_of_date") or frappe.utils.today())
    today = frappe.utils.getdate(frappe.utils.today())
    if as_of_date == today:
        as_of_dt = frappe.utils.now_datetime()
    else:
        as_of_dt = frappe.utils.get_datetime(f"{as_of_date} 23:59:59")

    stages = get_lead_stage_options()

    conditions = lead_dimension_filters(filters)
    conditions["creation"] = ["<=", as_of_dt]
    leads = frappe.get_all("Lead", filters=conditions, fields=["name", "status", "creation"],
                            limit_page_length=0)
    lead_names = [l.name for l in leads]

    # Latest "Lead Stage" transition on or before As Of Date, per Lead.
    # order_by changed_on desc + setdefault = first row kept per lead is the
    # latest one that still qualifies (<= As Of Date).
    as_of_state = {}
    if lead_names:
        log_rows = frappe.get_all(
            "AlphaX Stage Transition Log",
            filters={
                "reference_doctype": "Lead",
                "field_label": "Lead Stage",
                "reference_name": ["in", lead_names],
                "changed_on": ["<=", as_of_dt],
            },
            fields=["reference_name", "to_value", "changed_on"],
            order_by="changed_on desc",
            limit_page_length=0,
        )
        for r in log_rows:
            as_of_state.setdefault(r.reference_name, (r.to_value, r.changed_on))

    assumed_count = 0
    by_stage = {}
    for l in leads:
        hist = as_of_state.get(l.name)
        if hist:
            stage_as_of, ref_dt = hist
        else:
            stage_as_of, ref_dt = "Lead", l.creation
            assumed_count += 1
        if not ref_dt:
            continue
        days = (as_of_dt - frappe.utils.get_datetime(ref_dt)).total_seconds() / 86400.0
        by_stage.setdefault(stage_as_of or _("(not set)"), []).append(max(days, 0.0))

    data = []
    for stage in stages:
        days_list = by_stage.pop(stage, [])
        n = len(days_list)
        data.append({
            "stage": stage,
            "leads_in_stage": n,
            "avg_days": round(sum(days_list) / n, 1) if n else 0,
            "oldest_days": round(max(days_list), 1) if n else 0,
        })
    # any stage value present on live Leads but no longer in the field's
    # option list (e.g. retired/renamed since) -- still show it rather than
    # silently dropping those leads from the report.
    for stage, days_list in by_stage.items():
        n = len(days_list)
        data.append({
            "stage": f"{stage} " + str(_("(not in current stage list)")),
            "leads_in_stage": n,
            "avg_days": round(sum(days_list) / n, 1) if n else 0,
            "oldest_days": round(max(days_list), 1) if n else 0,
        })

    data.sort(key=lambda r: r["leads_in_stage"], reverse=True)

    columns = [
        {"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 220},
        {"label": _("Leads In Stage"), "fieldname": "leads_in_stage", "fieldtype": "Int", "width": 140},
        {"label": _("Avg Days In Stage"), "fieldname": "avg_days", "fieldtype": "Float", "precision": 1, "width": 150},
        {"label": _("Oldest (Days)"), "fieldname": "oldest_days", "fieldtype": "Float", "precision": 1, "width": 130},
    ]

    total_leads = sum(r["leads_in_stage"] for r in data)
    report_summary = [
        {"label": _("Total Leads (Filtered)"), "value": total_leads, "indicator": "blue"},
    ]
    if assumed_count:
        report_summary.append({
            "label": _("Assumed stage (no transition on record)"),
            "value": assumed_count,
        })

    chart = {
        "data": {
            "labels": [r["stage"] for r in data],
            "datasets": [{"name": _("Leads In Stage"), "values": [r["leads_in_stage"] for r in data]}],
        },
        "type": "bar",
    }

    is_today = as_of_date == today
    message = _("Snapshot as of now.") if is_today else _("Reconstructed snapshot as of {0} (end of day).").format(as_of_date)
    if assumed_count:
        message += " " + _(
            "{0} lead(s) had no logged Lead Stage transition on or before this date, so their stage "
            "is assumed to have still been “Lead” (the default for a new Lead) since creation."
        ).format(assumed_count)

    return columns, data, message, chart, report_summary
