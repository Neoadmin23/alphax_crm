"""Follow-ups due — the latest follow-up per record whose Next Follow-up Date is
due, so nothing is dropped. Overdue rows are flagged."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, date_diff


def execute(filters=None):
    filters = frappe._dict(filters or {})
    conditions = {}
    if filters.get("reference_doctype"):
        conditions["reference_doctype"] = filters.reference_doctype

    rows = frappe.get_list(
        "AlphaX Follow-up", filters=conditions,
        fields=["name", "reference_doctype", "reference_name", "agent", "channel",
                "outcome", "next_action", "next_follow_up_date", "follow_up_datetime"],
        order_by="next_follow_up_date asc", limit_page_length=0,
    )
    # keep only the most recent follow-up per record (the live next step)
    seen, latest = set(), []
    for r in sorted(rows, key=lambda x: x["follow_up_datetime"] or "", reverse=True):
        key = (r["reference_doctype"], r["reference_name"])
        if key in seen:
            continue
        seen.add(key)
        latest.append(r)

    # The Lead owns the agreed postponement date, including legacy records
    # whose most recent follow-up has a blank next date.
    if filters.get("reference_doctype") in (None, "", "Lead"):
        from alphax_crm.crm.sales_desk import postponed_date
        from alphax_crm.crm.utils import get_settings
        from alphax_crm.crm.automation import is_paused
        postponed = frappe.get_list("Lead", filters={"status":"Postponed"},
            fields=["name","owner","lead_owner","alphax_next_contact_date"],limit_page_length=0)
        names = {lead.name for lead in postponed}
        latest = [r for r in latest if not (r.reference_doctype=="Lead" and r.reference_name in names)]
        fallback = int(get_settings().get("postponed_default_revisit_days") or 30)
        for lead in postponed:
            if not is_paused(lead.name):
                latest.append(frappe._dict(reference_doctype="Lead", reference_name=lead.name,
                    agent=lead.lead_owner or lead.owner, channel=None, outcome=None, next_action=_("Contact postponed Lead"),
                    next_follow_up_date=postponed_date(lead,fallback)))
    today = getdate(nowdate())
    horizon = int(filters.get("within_days") or 0)
    data = []
    for r in latest:
        if not r.get("next_follow_up_date") or (filters.get("agent") and r.agent != filters.agent):
            continue
        if not frappe.has_permission(r.reference_doctype, "read", r.reference_name):
            continue
        due = getdate(r["next_follow_up_date"])
        overdue_by = date_diff(today, due)
        if horizon and overdue_by < -horizon:
            continue
        data.append({
            "reference_doctype": r["reference_doctype"],
            "reference_name": r["reference_name"],
            "agent": r["agent"],
            "last_channel": r["channel"],
            "last_outcome": r["outcome"],
            "next_action": r["next_action"],
            "next_follow_up_date": due,
            "overdue_days": overdue_by if overdue_by > 0 else 0,
            "state": _("Overdue") if overdue_by > 0 else (_("Due today") if overdue_by == 0 else _("Upcoming")),
        })
    data.sort(key=lambda x: x["next_follow_up_date"])

    columns = [
        {"label": _("Type"), "fieldname": "reference_doctype", "fieldtype": "Data", "width": 110},
        {"label": _("Record"), "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 150},
        {"label": _("Agent"), "fieldname": "agent", "fieldtype": "Link", "options": "User", "width": 160},
        {"label": _("Last Channel"), "fieldname": "last_channel", "fieldtype": "Data", "width": 100},
        {"label": _("Last Outcome"), "fieldname": "last_outcome", "fieldtype": "Data", "width": 120},
        {"label": _("Next Action"), "fieldname": "next_action", "fieldtype": "Data", "width": 240},
        {"label": _("Next Follow-up"), "fieldname": "next_follow_up_date", "fieldtype": "Date", "width": 120},
        {"label": _("Overdue (days)"), "fieldname": "overdue_days", "fieldtype": "Int", "width": 110},
        {"label": _("State"), "fieldname": "state", "fieldtype": "Data", "width": 100},
    ]
    overdue = sum(1 for d in data if d["overdue_days"] > 0)
    return columns, data, _("{0} follow-ups tracked · {1} overdue.").format(len(data), overdue), None, [
        {"label": _("Open follow-ups"), "value": len(data)},
        {"label": _("Overdue"), "value": overdue, "indicator": "Red" if overdue else "Green"},
    ]
