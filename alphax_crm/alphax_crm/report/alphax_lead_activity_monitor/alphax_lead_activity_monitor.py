"""AlphaX Lead Activity Monitor — last activity (who/what/when) and idle time
on open leads. Status filter defaults to the configured default monitored
status; thresholds drive the red 'overdue' indicator."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, date_diff

from alphax_crm.crm.tasks import (
    get_monitored_statuses, get_default_monitored_status, get_monitor_fields,
    apply_dimension_filters,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    thresholds = get_monitored_statuses(settings)
    default_threshold = settings.get("default_idle_threshold_days") or 3

    # Which statuses to include.
    if filters.get("status"):
        statuses = filters.status if isinstance(filters.status, list) else [filters.status]
    elif filters.get("only_monitored", 1) and thresholds:
        statuses = list(thresholds.keys())
    else:
        statuses = None

    conditions = {}
    if statuses:
        conditions["status"] = ["in", statuses]
    if filters.get("lead_owner"):
        conditions["lead_owner"] = filters.lead_owner
    if filters.get("company"):
        conditions["company"] = filters.company

    # Configurable extra fields (columns + filters).
    extra = get_monitor_fields("Lead")
    lead_meta = frappe.get_meta("Lead")
    extra = [e for e in extra if lead_meta.has_field(e["fieldname"])]
    apply_dimension_filters("Lead", conditions, filters)

    base_fields = [
        "name", "lead_name", "company_name", "status", "lead_owner", "creation",
        "alphax_last_activity", "alphax_last_activity_by", "alphax_last_activity_type",
        "alphax_last_activity_summary",
    ]
    fetch_fields = base_fields + [e["fieldname"] for e in extra if e["fieldname"] not in base_fields]

    leads = frappe.get_all("Lead", filters=conditions, fields=fetch_fields, limit_page_length=0)

    today = getdate(nowdate())
    min_idle = int(filters.get("idle_over_days") or 0)
    data = []
    overdue = 0
    for l in leads:
        anchor = l.alphax_last_activity or l.creation
        try:
            idle = max(date_diff(today, getdate(anchor)), 0)
        except Exception:
            idle = 0
        if idle < min_idle:
            continue
        threshold = thresholds.get(l.status, default_threshold)
        is_overdue = idle > threshold
        if is_overdue:
            overdue += 1
        row = {
            "lead": l.name,
            "lead_name": l.lead_name,
            "company_name": l.company_name,
            "status": l.status,
            "lead_owner": l.lead_owner,
            "last_activity": l.alphax_last_activity,
            "last_activity_by": l.alphax_last_activity_by,
            "last_activity_type": l.alphax_last_activity_type or _("(no activity yet)"),
            "last_activity_summary": l.alphax_last_activity_summary,
            "idle_days": idle,
            "threshold_days": threshold,
            "overdue": _("Yes") if is_overdue else "",
        }
        for e in extra:
            row[e["fieldname"]] = l.get(e["fieldname"])
        data.append(row)

    data.sort(key=lambda r: r["idle_days"], reverse=True)

    columns = [
        {"label": _("Lead"), "fieldname": "lead", "fieldtype": "Link", "options": "Lead", "width": 130},
        {"label": _("Name"), "fieldname": "lead_name", "fieldtype": "Data", "width": 150},
        {"label": _("Company"), "fieldname": "company_name", "fieldtype": "Data", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
        {"label": _("Owner"), "fieldname": "lead_owner", "fieldtype": "Link", "options": "User", "width": 150},
        {"label": _("Last Activity"), "fieldname": "last_activity", "fieldtype": "Datetime", "width": 150},
        {"label": _("By"), "fieldname": "last_activity_by", "fieldtype": "Link", "options": "User", "width": 140},
        {"label": _("What"), "fieldname": "last_activity_type", "fieldtype": "Data", "width": 130},
        {"label": _("Summary"), "fieldname": "last_activity_summary", "fieldtype": "Data", "width": 220},
        {"label": _("Idle Days"), "fieldname": "idle_days", "fieldtype": "Int", "width": 90},
        {"label": _("Threshold"), "fieldname": "threshold_days", "fieldtype": "Int", "width": 90},
        {"label": _("Overdue"), "fieldname": "overdue", "fieldtype": "Data", "width": 80},
    ]
    for e in extra:
        if not e.get("as_column"):
            continue
        col = {"label": e["label"], "fieldname": e["fieldname"], "width": 130}
        if e["fieldtype"] == "Link":
            col["fieldtype"] = "Link"
            col["options"] = e["options"]
        else:
            col["fieldtype"] = "Data"
        columns.append(col)

    message = _("Showing {0} leads · {1} overdue (idle beyond threshold).").format(len(data), overdue)
    chart = None
    report_summary = [
        {"label": _("Leads"), "value": len(data)},
        {"label": _("Overdue"), "value": overdue, "indicator": "Red" if overdue else "Green"},
    ]
    return columns, data, message, chart, report_summary
