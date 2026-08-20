"""Follow-up mechanism for AlphaX CRM.

A complete, history-keeping follow-up loop for Lead / Prospect / Opportunity:

  * Each AlphaX Follow-up records one touch (channel, direction, outcome,
    duration, summary) and the next step (next action + next follow-up date).
  * On save it threads a phone/chat/email Communication onto the parent so the
    whole history shows in the activity timeline,
  * stamps last-activity (who / what / when) and resets idle,
  * pushes the next follow-up date onto the parent, and
  * raises a reminder (ToDo) for the agent on that date.

`log_followup` is the whitelisted entry point used by the "Log Follow-up"
button on each form.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, cint

MEDIUM = {"Call": "Phone", "Email": "Email", "WhatsApp": "Chat", "SMS": "SMS",
          "Meeting": "Event", "Visit": "Visit", "Other": "Other"}
NEXT_DATE_FIELD = {"Lead": "alphax_next_contact_date", "AlphaX Prospect": "follow_up_date",
                   "Opportunity": "alphax_next_activity_date"}


def process_followup(doc):
    ref_dt, ref_name = doc.reference_doctype, doc.reference_name
    if not frappe.db.exists(ref_dt, ref_name):
        return

    # 1) Thread a Communication so the touch shows in the timeline history.
    _log_communication(doc)

    # 2) Stamp last activity (who/what/when) + reset idle.
    try:
        from alphax_crm.crm.activity import record_activity

        atype = f"{doc.channel} ({doc.direction})" if doc.direction else doc.channel
        if doc.meeting_type:
            atype = f"{atype} · {doc.meeting_type}"
        if doc.outcome:
            atype = f"{atype} · {doc.outcome}"
        record_activity(ref_dt, ref_name, atype, doc.agent, (doc.summary or "")[:180])
    except Exception:
        frappe.log_error(title="AlphaX CRM: followup activity", message=frappe.get_traceback())

    # 3) Push the next follow-up date onto the parent record.
    if doc.next_follow_up_date:
        field = NEXT_DATE_FIELD.get(ref_dt)
        if field and frappe.get_meta(ref_dt).has_field(field):
            frappe.db.set_value(ref_dt, ref_name, field, doc.next_follow_up_date, update_modified=False)
        _create_reminder(doc)


def _log_communication(doc):
    secs = cint(doc.duration)
    dur = ""
    if secs:
        m, s = divmod(secs, 60)
        dur = f" · {m}m {s}s" if m else f" · {s}s"
    content = f"<b>{doc.channel}"
    if doc.meeting_type:
        content += f" — {doc.meeting_type}"
    content += f" — {doc.outcome or 'logged'}</b>{dur}"
    if doc.summary:
        content += "<br>" + frappe.utils.escape_html(doc.summary)
    if doc.next_action:
        content += "<br><i>Next: " + frappe.utils.escape_html(doc.next_action) + "</i>"

    phone = frappe.db.get_value(doc.reference_doctype, doc.reference_name, "mobile_no") \
        if frappe.get_meta(doc.reference_doctype).has_field("mobile_no") else None

    comm = frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "communication_medium": MEDIUM.get(doc.channel, "Other"),
        "sent_or_received": "Sent" if doc.direction == "Outgoing" else "Received",
        "subject": f"Follow-up — {doc.channel} ({doc.outcome or ''})".strip(" ()"),
        "content": content,
        "reference_doctype": doc.reference_doctype,
        "reference_name": doc.reference_name,
        "phone_no": phone,
        "communication_date": doc.follow_up_datetime,
        "status": "Linked",
    })
    comm.flags.ignore_permissions = True
    comm.insert(ignore_permissions=True)


def _create_reminder(doc):
    if not doc.agent:
        return
    if frappe.db.exists("ToDo", {"reference_type": "AlphaX Follow-up", "reference_name": doc.name, "status": "Open"}):
        return
    todo = frappe.get_doc({
        "doctype": "ToDo",
        "allocated_to": doc.agent,
        "date": doc.next_follow_up_date,
        "reference_type": doc.reference_doctype,
        "reference_name": doc.reference_name,
        "priority": "Medium",
        "description": _("Follow up ({0}) — {1}: {2}").format(
            doc.channel, doc.reference_name, doc.next_action or doc.summary or ""),
    })
    todo.flags.ignore_permissions = True
    todo.insert(ignore_permissions=True)


@frappe.whitelist()
def log_followup(reference_doctype, reference_name, channel="Call", direction="Outgoing",
                 outcome="Connected", duration=0, summary=None, next_action=None,
                 next_follow_up_date=None, follow_up_datetime=None, meeting_type=None):
    doc = frappe.get_doc({
        "doctype": "AlphaX Follow-up",
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "channel": channel,
        "meeting_type": meeting_type if channel == "Meeting" else None,
        "direction": direction,
        "outcome": outcome,
        "duration": cint(duration),
        "summary": summary or "",
        "next_action": next_action or "",
        "next_follow_up_date": next_follow_up_date or None,
        "follow_up_datetime": follow_up_datetime or now_datetime(),
        "agent": frappe.session.user,
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


@frappe.whitelist()
def get_history(reference_doctype, reference_name):
    """Return the follow-up history for a record (newest first)."""
    return frappe.get_all(
        "AlphaX Follow-up",
        filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
        fields=["name", "follow_up_datetime", "channel", "meeting_type", "direction", "outcome",
                "agent", "summary", "next_action", "next_follow_up_date"],
        order_by="follow_up_datetime desc",
    )
