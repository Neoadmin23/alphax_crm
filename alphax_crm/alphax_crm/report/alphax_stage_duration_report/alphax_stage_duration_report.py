"""How long records actually sit before moving between pipeline stages —
the "day gap between actions" the AI-automation pass was asked to expose.

Aggregates AlphaX Stage Transition Log (populated automatically by
crm.activity.record_transition whenever Lead Status, Lead Stage or the
approval Workflow State changes) into an average/min/max day-gap per
transition, so a stalled step in the pipeline shows up as a number
instead of staying invisible until someone happens to notice.
"""

import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    conditions = {"days_since_previous": ["is", "set"]}
    if filters.get("reference_doctype"):
        conditions["reference_doctype"] = filters.reference_doctype
    if filters.get("field_label"):
        conditions["field_label"] = filters.field_label
    if filters.get("from_date"):
        conditions["changed_on"] = [">=", filters.from_date]
    if filters.get("to_date"):
        conditions.setdefault("changed_on", ["<=", filters.to_date])
        if isinstance(conditions["changed_on"], list) and conditions["changed_on"][0] == ">=":
            conditions["changed_on"] = ["between", [filters.get("from_date"), filters.get("to_date")]]

    rows = frappe.get_all(
        "AlphaX Stage Transition Log",
        filters=conditions,
        fields=["reference_doctype", "field_label", "from_value", "to_value", "days_since_previous"],
        limit_page_length=0,
    )

    groups = {}
    for r in rows:
        key = (r.reference_doctype, r.field_label, r.from_value or "", r.to_value or "")
        groups.setdefault(key, []).append(r.days_since_previous or 0)

    data = []
    for (ref_dt, field_label, from_value, to_value), gaps in groups.items():
        n = len(gaps)
        avg = sum(gaps) / n if n else 0
        data.append({
            "reference_doctype": ref_dt,
            "field_label": field_label,
            "from_value": from_value,
            "to_value": to_value,
            "transitions": n,
            "avg_days": round(avg, 2),
            "min_days": round(min(gaps), 2),
            "max_days": round(max(gaps), 2),
        })

    data.sort(key=lambda x: x["avg_days"], reverse=True)

    columns = [
        {"label": _("Record Type"), "fieldname": "reference_doctype", "fieldtype": "Data", "width": 110},
        {"label": _("Tracked Field"), "fieldname": "field_label", "fieldtype": "Data", "width": 110},
        {"label": _("From"), "fieldname": "from_value", "fieldtype": "Data", "width": 150},
        {"label": _("To"), "fieldname": "to_value", "fieldtype": "Data", "width": 150},
        {"label": _("Transitions"), "fieldname": "transitions", "fieldtype": "Int", "width": 100},
        {"label": _("Avg Days"), "fieldname": "avg_days", "fieldtype": "Float", "precision": 2, "width": 100},
        {"label": _("Min Days"), "fieldname": "min_days", "fieldtype": "Float", "precision": 2, "width": 100},
        {"label": _("Max Days"), "fieldname": "max_days", "fieldtype": "Float", "precision": 2, "width": 100},
    ]

    total_transitions = sum(d["transitions"] for d in data)
    overall_avg = round(sum(r.days_since_previous or 0 for r in rows) / len(rows), 2) if rows else 0

    return columns, data, _("{0} logged transitions across {1} transition types.").format(
        total_transitions, len(data)
    ), None, [
        {"label": _("Logged Transitions"), "value": total_transitions},
        {"label": _("Overall Avg Day-Gap"), "value": overall_avg},
    ]
