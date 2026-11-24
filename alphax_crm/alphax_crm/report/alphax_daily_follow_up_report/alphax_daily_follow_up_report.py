"""Daily follow-up report: what was scheduled for the chosen day, what got done, what is still open or overdue.
Definitions live in alphax_crm.crm.followup_report."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from alphax_crm.crm.followup_report import classify, summary_counts


def execute(filters=None):
    filters = frappe._dict(filters or {})
    as_of = getdate(filters.get("date") or nowdate())
    ref_dt = filters.get("reference_doctype") or "Lead"
    conditions = {"reference_doctype": ref_dt}
    if filters.get("agent"):
        conditions["agent"] = filters.agent

    raw = frappe.get_list(
        "AlphaX Follow-up", filters=conditions,
        fields=["name", "reference_doctype", "reference_name", "agent", "channel", "outcome", "summary",
                "next_action", "next_follow_up_date", "follow_up_datetime"],
        limit_page_length=0,
    )
    rows = classify(raw, as_of)
    rows = [r for r in rows if frappe.has_permission(r["reference_doctype"], "read", r["reference_name"])]

    names = list({r["reference_name"] for r in rows})
    info = {}
    if ref_dt == "Lead" and names:
        info = {l.name: l for l in frappe.get_all("Lead", filters={"name": ["in", names]},
                fields=["name", "lead_name", "company_name", "status", "lead_owner"])}
    counts = summary_counts(rows, as_of)
    if filters.get("status"):
        rows = [r for r in rows if r["status"] == filters.status]

    data = []
    for r in rows:
        lead = info.get(r["reference_name"]) or {}
        data.append({
            "reference_doctype": r["reference_doctype"], "reference_name": r["reference_name"],
            "lead_name": lead.get("lead_name") or lead.get("company_name"), "stage": lead.get("status"),
            "agent": r.get("agent"), "scheduled_for": r["scheduled_for"], "status": r["status"],
            "overdue_days": r["overdue_days"], "completed_on": r["completed_on"],
            "next_action": r.get("next_action"), "last_channel": r.get("channel"), "last_outcome": r.get("outcome"),
        })

    columns = [
        {"label": _("Record"), "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 150},
        {"label": _("Type"), "fieldname": "reference_doctype", "fieldtype": "Data", "width": 90},
        {"label": _("Lead Name"), "fieldname": "lead_name", "fieldtype": "Data", "width": 170},
        {"label": _("Lead Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 120},
        {"label": _("Agent"), "fieldname": "agent", "fieldtype": "Link", "options": "User", "width": 160},
        {"label": _("Scheduled For"), "fieldname": "scheduled_for", "fieldtype": "Date", "width": 110},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Days Overdue"), "fieldname": "overdue_days", "fieldtype": "Int", "width": 100},
        {"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Date", "width": 110},
        {"label": _("Next Action"), "fieldname": "next_action", "fieldtype": "Data", "width": 240},
        {"label": _("Last Channel"), "fieldname": "last_channel", "fieldtype": "Data", "width": 100},
        {"label": _("Last Outcome"), "fieldname": "last_outcome", "fieldtype": "Data", "width": 120},
    ]
    message = _("Scheduled for the day: {0}. Completed also includes overdue follow-ups cleared that day. "
                "A follow-up counts as completed once the next one is logged on the same record.").format(counts["scheduled"])
    summary = [
        {"label": _("Scheduled for the day"), "value": counts["scheduled"], "datatype": "Int"},
        {"label": _("Completed"), "value": counts["completed"], "datatype": "Int", "indicator": "Green"},
        {"label": _("Pending"), "value": counts["pending"], "datatype": "Int", "indicator": "Orange" if counts["pending"] else "Green"},
        {"label": _("Overdue"), "value": counts["overdue"], "datatype": "Int", "indicator": "Red" if counts["overdue"] else "Green"},
    ]
    return columns, data, message, None, summary
