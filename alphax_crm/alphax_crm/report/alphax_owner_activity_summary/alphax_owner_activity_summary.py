"""AlphaX Owner Activity Summary — per salesperson: open records, average idle,
max idle, and overdue count. Works across Lead, Opportunity and PreLead."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, date_diff, flt

from alphax_crm.crm.tasks import (
    get_owner_field, get_open_records, get_monitored_statuses, threshold_for,
    get_monitor_fields,
)

TARGET_MAP = {"Lead": "Lead", "Opportunity": "Opportunity", "PreLead": "AlphaX PreLead"}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    label = filters.get("document_type") or "Lead"
    target = TARGET_MAP.get(label, "Lead")

    owner_field = get_owner_field(target)
    thresholds = get_monitored_statuses(settings) if target == "Lead" else {}

    # Configurable dimension filters (e.g. Cost Center / Business Unit).
    extra = get_monitor_fields(target)
    tmeta = frappe.get_meta(target)
    extra_filters = {}
    for e in extra:
        if e.get("as_filter") and tmeta.has_field(e["fieldname"]) and filters.get(e["fieldname"]):
            extra_filters[e["fieldname"]] = filters.get(e["fieldname"])

    records = get_open_records(
        target, settings,
        fields=["name", "status", "creation", "alphax_last_activity", owner_field],
        extra_filters=extra_filters,
    )

    today = getdate(nowdate())
    agg = {}
    for r in records:
        owner = r.get(owner_field) or _("(unassigned)")
        anchor = r.get("alphax_last_activity") or r.get("creation")
        try:
            idle = max(date_diff(today, getdate(anchor)), 0)
        except Exception:
            idle = 0
        threshold = threshold_for(target, r.get("status"), settings, thresholds)
        overdue = idle > threshold

        a = agg.setdefault(owner, {"total": 0, "idle_sum": 0, "max_idle": 0, "overdue": 0})
        a["total"] += 1
        a["idle_sum"] += idle
        a["max_idle"] = max(a["max_idle"], idle)
        if overdue:
            a["overdue"] += 1

    only_overdue = filters.get("only_overdue")
    data = []
    for owner, a in agg.items():
        if only_overdue and not a["overdue"]:
            continue
        avg_idle = flt(a["idle_sum"] / a["total"], 1) if a["total"] else 0
        data.append({
            "owner": owner,
            "total": a["total"],
            "avg_idle": avg_idle,
            "max_idle": a["max_idle"],
            "overdue": a["overdue"],
            "overdue_pct": flt(a["overdue"] * 100.0 / a["total"], 1) if a["total"] else 0,
        })
    data.sort(key=lambda x: (x["overdue"], x["avg_idle"]), reverse=True)

    columns = [
        {"label": _("Owner"), "fieldname": "owner", "fieldtype": "Link", "options": "User", "width": 220},
        {"label": _("Open {0}").format(label), "fieldname": "total", "fieldtype": "Int", "width": 120},
        {"label": _("Avg Idle (days)"), "fieldname": "avg_idle", "fieldtype": "Float", "precision": 1, "width": 130},
        {"label": _("Max Idle"), "fieldname": "max_idle", "fieldtype": "Int", "width": 100},
        {"label": _("Overdue"), "fieldname": "overdue", "fieldtype": "Int", "width": 100},
        {"label": _("Overdue %"), "fieldname": "overdue_pct", "fieldtype": "Percent", "width": 110},
    ]

    total_open = sum(a["total"] for a in agg.values())
    total_overdue = sum(a["overdue"] for a in agg.values())
    report_summary = [
        {"label": _("Salespeople"), "value": len(data)},
        {"label": _("Open {0}").format(label), "value": total_open},
        {"label": _("Overdue"), "value": total_overdue, "indicator": "Red" if total_overdue else "Green"},
    ]
    message = _("Open {0} grouped by owner. Overdue = idle beyond the status threshold.").format(label)
    return columns, data, message, None, report_summary
