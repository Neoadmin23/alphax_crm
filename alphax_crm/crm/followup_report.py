"""Daily follow-up report logic (pure: no database access, so it can be tested on its own).

A *commitment* is a real follow-up (not an "AlphaX:" placeholder) that set a Next Follow-up Date. It is
*Completed* once the next real follow-up on the same record has been logged, *Pending* if it is due on the
report date and still open, and *Overdue* if it was due before the report date and is still open.
"""
from datetime import date, datetime

from frappe.utils import get_datetime, getdate

PLACEHOLDER_PREFIX = "AlphaX:"


def is_real(follow_up) -> bool:
    return not (follow_up.get("summary") or "").startswith(PLACEHOLDER_PREFIX)


def classify(follow_ups, as_of) -> list[dict]:
    """follow_ups: dicts with reference_doctype, reference_name, follow_up_datetime, next_follow_up_date,
    summary (+ any display fields, which are passed through). as_of: the report date.
    Returns one dict per commitment that matters on `as_of`, with status Completed / Pending / Overdue."""
    as_of = getdate(as_of)
    groups = {}
    for f in follow_ups:
        if is_real(f):
            groups.setdefault((f["reference_doctype"], f["reference_name"]), []).append(f)
    rows = []
    for items in groups.values():
        items.sort(key=lambda f: get_datetime(f["follow_up_datetime"]))
        for i, f in enumerate(items):
            if not f.get("next_follow_up_date"):
                continue
            due = getdate(f["next_follow_up_date"])
            done_at = None
            if i + 1 < len(items):
                nxt = get_datetime(items[i + 1]["follow_up_datetime"])
                if nxt.date() <= as_of:  # as-of the report date: later work is not counted
                    done_at = nxt
            if done_at:
                if due != as_of and done_at.date() != as_of:
                    continue  # finished before the report date, nothing to report
                status = "Completed"
            elif due == as_of:
                status = "Pending"
            elif due < as_of:
                status = "Overdue"
            else:
                continue  # due after the report date: upcoming, not part of today's report
            rows.append({**f, "scheduled_for": due, "status": status,
                         "completed_on": done_at.date() if done_at else None,
                         "overdue_days": (as_of - due).days if status == "Overdue" else 0})
    order = {"Overdue": 0, "Pending": 1, "Completed": 2}
    rows.sort(key=lambda r: (order[r["status"]], r["scheduled_for"], str(r["reference_name"])))
    return rows


def summary_counts(rows, as_of) -> dict:
    as_of = getdate(as_of)
    return {
        "scheduled": sum(1 for r in rows if r["scheduled_for"] == as_of),
        "completed": sum(1 for r in rows if r["status"] == "Completed"),
        "pending": sum(1 for r in rows if r["status"] == "Pending"),
        "overdue": sum(1 for r in rows if r["status"] == "Overdue"),
    }
