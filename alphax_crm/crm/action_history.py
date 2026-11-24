"""Append-only CRM action evidence. The responsible executive and executor are separate."""
import frappe
from frappe.utils import now_datetime


def identity(automated=False):
    user = frappe.session.user or "Guest"
    request = getattr(frappe.local, "request", None)
    source = "Automation" if automated or not request else "User"
    return dict(actor_user=user, actor_name=frappe.utils.get_fullname(user) or user,
                action_source=source, initiated_by=user if request else None)


def lead_for_reference(dt, name):
    if not name:
        return None
    if dt == "Lead":
        return name
    if dt == "Quotation":
        from alphax_crm.crm.automation import lead_for_quotation
        return lead_for_quotation(name)
    if dt in ("AlphaX PreLead","AlphaX Smart Lead"):
        return frappe.db.get_value(dt,name,"lead")
    if dt == "Customer":
        return frappe.db.get_value(dt,name,"lead_name")
    if dt == "Opportunity":
        origin, party = frappe.db.get_value(dt, name, ["opportunity_from", "party_name"]) or (None, None)
        if origin == "Lead":
            return party
        if origin == "Customer":
            return frappe.db.get_value("Customer", party, "lead_name")
    return None


def record(action, dt, name, lead=None, automated=False, detail=None, context=None):
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return
    fields = context or identity(automated)
    executive = None
    if lead:
        owner = frappe.db.get_value("Lead", lead, ["lead_owner", "owner"], as_dict=True)
        executive = owner and (owner.lead_owner or owner.owner)
    frappe.get_doc(dict(doctype="AlphaX CRM Action", action=action, reference_doctype=dt,
                        reference_name=name, lead=lead, executive=executive, occurred_on=now_datetime(),
                        detail=(detail or "")[:450], **fields)).insert(ignore_permissions=True)


def capture(doc, method):
    """Log one business event per hook. Inserts/submits also fire on_update."""
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return
    prior = doc.get_doc_before_save()
    if method == "on_update" and (not prior or prior.docstatus != doc.docstatus):
        return
    dt = doc.doctype
    label = {"on_trash": "Deleted", "after_insert": "Created", "on_update": "Updated", "on_submit": "Submitted",
             "on_cancel": "Cancelled", "on_update_after_submit": "Updated after submission"}[method]
    link_dt, link_name = dt, doc.name
    detail = None
    system = bool(doc.flags.get("alphax_system") or doc.flags.get("alphax_generated") or
                  (dt == "AlphaX Email Draft" and method=="after_insert" and doc.get("generated_by_ai")))
    if dt in ("Event", "ToDo"):
        if dt == "Event":
            leads = {p.reference_docname for p in doc.get("event_participants") or [] if p.reference_doctype == "Lead"}
            for lead in leads:
                record("Event " + label, dt, doc.name, lead, system)
            return
        link_dt, link_name = doc.reference_type, doc.reference_name
    elif dt in ("AlphaX Follow-up", "AlphaX Email Draft", "Communication", "Comment"):
        link_dt, link_name = doc.reference_doctype, doc.reference_name
        if dt == "Comment" and doc.comment_type != "Comment":
            return
        if dt == "Communication":
            if doc.communication_type != "Communication":
                return
            label = doc.sent_or_received or label
            system = system or label == "Received" or bool(doc.flags.get("alphax_generated"))
            detail = doc.communication_medium
    if method != "on_trash" and prior and doc.get("status") != prior.get("status"):
        detail = f"{prior.get('status') or '—'} → {doc.get('status') or '—'}"
    lead = lead_for_reference(link_dt, link_name)
    if dt == "AlphaX Email Draft" and method != "on_trash" and prior and prior.status != doc.status:
        label = doc.status
    if dt in ("Comment", "Communication", "ToDo", "Customer") and not lead:
        return
    record(f"{dt} {label}", dt, doc.name, lead, system, detail)
