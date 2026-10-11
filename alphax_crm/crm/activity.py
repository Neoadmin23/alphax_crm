"""Activity tracking — keeps follow-up SLAs and scores fresh as
Communications land against Leads / Opportunities."""

import frappe
from frappe.utils import now_datetime, cint

from alphax_crm.crm.utils import get_settings, log_error


# ---------------------------------------------------------------------------
# Call logging  (provider-independent; records a call as a phone Communication
# so it appears in the document's activity timeline as call history)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def log_call(reference_doctype, reference_name, call_type="Outgoing", status="Completed",
             duration=0, summary=None, follow_up_date=None):
    if not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(frappe._("{0} {1} not found.").format(reference_doctype, reference_name))

    doc = frappe.get_doc(reference_doctype, reference_name)
    phone = doc.get("mobile_no") or doc.get("phone") or doc.get("contact_mobile") or ""

    secs = cint(duration)
    dur_txt = ""
    if secs:
        m, s = divmod(secs, 60)
        dur_txt = f" · {m}m {s}s" if m else f" · {s}s"

    body = (summary or "").strip()
    content = f"<b>{call_type} call — {status}</b>{dur_txt}"
    if body:
        content += "<br>" + frappe.utils.escape_html(body)

    comm = frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Phone",
            "sent_or_received": "Sent" if call_type == "Outgoing" else "Received",
            "phone_no": phone,
            "subject": f"Call — {call_type} ({status})",
            "content": content,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Linked",
        }
    )
    comm.flags.ignore_permissions = True
    comm.insert(ignore_permissions=True)

    meta = frappe.get_meta(reference_doctype)
    updates = {}
    if meta.has_field("last_contacted_on"):
        updates["last_contacted_on"] = now_datetime()
    if follow_up_date and meta.has_field("follow_up_date"):
        updates["follow_up_date"] = follow_up_date
    if meta.has_field("alphax_last_activity"):
        updates["alphax_last_activity"] = now_datetime()
    if updates:
        frappe.db.set_value(reference_doctype, reference_name, updates, update_modified=False)

    return comm.name


def on_communication(doc, method=None):
    ref_dt = doc.get("reference_doctype")
    ref_name = doc.get("reference_name")
    if ref_dt not in ("Lead", "Opportunity", "AlphaX PreLead") or not ref_name:
        return
    if not frappe.db.exists(ref_dt, ref_name):
        return

    medium = doc.get("communication_medium")
    activity_type = {"Email": "Email", "Phone": "Call", "Chat": "WhatsApp / Chat", "SMS": "SMS"}.get(
        medium, medium or "Communication"
    )
    direction = doc.get("sent_or_received") or ""
    if direction:
        activity_type = f"{activity_type} ({direction})"

    # Who: the user who logged/sent it (external inbound has no internal user).
    by_user = doc.get("owner") if doc.get("sent_or_received") == "Sent" else None
    summary = (doc.get("subject") or frappe.utils.strip_html(doc.get("content") or ""))[:180]

    record_activity(ref_dt, ref_name, activity_type, by_user, summary)

    # Inbound message on a Lead -> recompute score so engagement counts.
    if ref_dt == "Lead" and doc.get("sent_or_received") == "Received":
        settings = get_settings()
        if settings.scoring_enabled:
            try:
                from alphax_crm.crm.lead import compute_score

                lead = frappe.get_doc("Lead", ref_name)
                score, breakdown = compute_score(lead, settings)
                frappe.db.set_value(
                    "Lead", ref_name,
                    {"alphax_lead_score": score, "alphax_score_breakdown": breakdown},
                    update_modified=False,
                )
            except Exception:
                log_error("rescore on communication")


def on_comment(doc, method=None):
    """A user comment on a Lead/PreLead counts as activity."""
    ref_dt = doc.get("reference_doctype")
    ref_name = doc.get("reference_name")
    if ref_dt not in ("Lead", "Opportunity", "AlphaX PreLead") or not ref_name:
        return
    if doc.get("comment_type") not in (None, "Comment"):
        return
    if not frappe.db.exists(ref_dt, ref_name):
        return
    summary = frappe.utils.strip_html(doc.get("content") or "")[:180]
    record_activity(ref_dt, ref_name, "Comment", doc.get("owner"), summary)


def record_activity(ref_dt, ref_name, activity_type, by_user, summary):
    """Stamp last-activity metadata on the record (no doc save -> no recursion)."""
    try:
        meta = frappe.get_meta(ref_dt)
        payload = {}
        if meta.has_field("alphax_last_activity"):
            payload["alphax_last_activity"] = now_datetime()
        if meta.has_field("alphax_last_activity_by"):
            payload["alphax_last_activity_by"] = by_user
        if meta.has_field("alphax_last_activity_type"):
            payload["alphax_last_activity_type"] = activity_type
        if meta.has_field("alphax_last_activity_summary"):
            payload["alphax_last_activity_summary"] = summary
        if meta.has_field("alphax_idle_days"):
            payload["alphax_idle_days"] = 0
        if meta.has_field("last_contacted_on") and ref_dt == "AlphaX PreLead":
            payload["last_contacted_on"] = now_datetime()
        if payload:
            frappe.db.set_value(ref_dt, ref_name, payload, update_modified=False)
    except Exception:
        log_error("record activity")


# ---------------------------------------------------------------------------
# Stage/status transition logging -> "day gap between actions"
# ---------------------------------------------------------------------------
def record_transition(ref_dt, ref_name, field_label, from_value, to_value, changed_by=None):
    """Log a pipeline transition (e.g. Lead Status, Lead Stage, Workflow State
    changing on a Lead/PreLead/Opportunity) and compute the day-gap since this
    same record's previous transition of the same tracked field.

    This is what powers the "day gap between actions" tracking: every time a
    key field changes, we know exactly how many days it sat since the last
    time that field changed, without needing a separate cron job.
    """
    settings = get_settings()
    if not settings.get("track_stage_durations", 1):
        return
    try:
        last_on = frappe.db.get_value(
            "AlphaX Stage Transition Log",
            {"reference_doctype": ref_dt, "reference_name": ref_name, "field_label": field_label},
            "changed_on",
            order_by="changed_on desc",
        )
        now = now_datetime()
        gap_days = None
        if last_on:
            delta = now - last_on
            gap_days = round(delta.total_seconds() / 86400.0, 2)

        log = frappe.new_doc("AlphaX Stage Transition Log")
        log.reference_doctype = ref_dt
        log.reference_name = ref_name
        log.field_label = field_label
        log.from_value = from_value or ""
        log.to_value = to_value or ""
        log.changed_by = changed_by or frappe.session.user
        log.changed_on = now
        if gap_days is not None:
            log.days_since_previous = gap_days
        log.flags.ignore_permissions = True
        log.insert(ignore_permissions=True)
    except Exception:
        log_error("record transition")
