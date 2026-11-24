"""Recipient-level delivery receipts. The parent workflow row serializes attempts."""
import frappe
from frappe import _
from frappe.utils import now_datetime


def latest_attempts(rows):
    return {(row.recipient, row.channel): row for row in rows}


def deliver_channels(log, only=None):
    from alphax_crm.crm import automation as auto
    recipients = list(dict.fromkeys((log.recipients or "").splitlines()))
    channels = ["In-app", "Email"] if log.send_email else ["In-app"]
    prior = latest_attempts(log.delivery_attempts or [])
    for user in recipients:
        for channel in channels:
            pair = (user, channel)
            if only and pair != only:
                continue
            if pair in prior and prior[pair].result != "Failed":
                continue
            values = dict(recipient=user, channel=channel, attempted_on=now_datetime(), executed_by=frappe.session.user)
            frappe.db.savepoint("ax_delivery_channel")
            try:
                if channel == "Email":
                    address = auto.user_emails([user]).get(user)
                    if not address:
                        frappe.throw(_("Recipient has no enabled email address"))
                    communication = auto._send_email(log, [address])
                    values.update(result="Queued", communication=communication)
                    values["email_queue"] = frappe.db.get_value("Email Queue", {"communication":communication}, "name") if communication else None
                    if communication:
                        log.communication = communication
                else:
                    frappe.get_doc(dict(doctype="Notification Log",subject=log.subject,for_user=user,type="Alert",
                        email_content=frappe.utils.markdown(log.message or ""),document_type=log.reference_doctype or ("Lead" if log.lead else None),
                        document_name=log.reference_name or log.lead,from_user=log.actor_user or frappe.session.user)).insert(ignore_permissions=True)
                    values["result"] = "Sent"
            except Exception as exc:
                frappe.db.rollback(save_point="ax_delivery_channel")
                values.update(result="Failed", error_detail=str(exc)[:450], communication=None, email_queue=None)
            log.append("delivery_attempts",values)
    latest = latest_attempts(log.delivery_attempts)
    failures = sum(row.result == "Failed" for row in latest.values())
    log.status = "Partly Sent" if failures else "Sent"
    log.result = _("Channels processed: {0}. Failed: {1}. Email delivery is tracked in Email Queue.").format(len(latest), failures)
    if not only:
        log.sent_on = now_datetime()
        if log.lead and log.log_on_timeline:
            auto.system_comment("Lead", log.lead, f"AlphaX [{log.rule}]: {log.subject} → {', '.join(recipients)}")
    log.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def retry_channel(log_name, recipient, channel):
    from alphax_crm.crm import automation as auto
    from alphax_crm.crm.action_history import record
    frappe.only_for("System Manager")
    frappe.db.sql("select name from `tabAlphaX Automation Log` where name=%s for update", (log_name,))
    log = frappe.get_doc(auto.LOG_DT,log_name)
    log.check_permission("write")
    row = latest_attempts(log.delivery_attempts or []).get((recipient,channel))
    if not row or row.result != "Failed":
        frappe.throw(_("Select a failed recipient and channel."))
    if not auto.is_business_time() or (log.lead and auto.is_paused(log.lead)):
        frappe.throw(_("Retry during business hours after any correction hold has ended."))
    if log.rule.startswith("WF-02 No quotation") and (frappe.db.get_value("Lead",log.lead,"status") != "Quotation" or auto.quotations_for_lead(log.lead, {"docstatus":["<",2]})):
        frappe.throw(_("The quotation requirement has already been resolved."))
    deliver_channels(log, (recipient,channel))
    record("Delivery retry",log.doctype,log.name,log.lead,detail=f"{recipient} · {channel} · {log.delivery_attempts[-1].result}")
    return log.status


@frappe.whitelist()
def transport_status(log_name):
    """Read live ERPNext queue results separately from the workflow's queue hand-off."""
    frappe.only_for(["Sales Manager","System Manager"])
    log=frappe.get_doc("AlphaX Automation Log",log_name)
    log.check_permission("read")
    rows=[]
    for a in latest_attempts(log.delivery_attempts or []).values():
        queue=a.email_queue
        if not queue and a.communication:
            queue=frappe.db.get_value("Email Queue",{"communication":a.communication},"name")
        if queue and frappe.has_permission("Email Queue","read",queue):
            rows.append(dict(recipient=a.recipient,queue=queue,status=frappe.db.get_value("Email Queue",queue,"status")))
    return rows
