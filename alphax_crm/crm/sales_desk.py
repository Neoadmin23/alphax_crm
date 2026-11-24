"""Sales worklists and executive reports built from records visible to the caller."""
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, now_datetime, nowdate

from alphax_crm.crm import automation as auto
from alphax_crm.crm.workflow import CLOSING_FIELDS, SPEC_FLOW, validity_notice_date
from alphax_crm.crm.utils import get_settings


def col(key, label, kind="Data", width=150, options=None):
    return dict(fieldname=key, label=_(label), fieldtype=kind, width=width, options=options)


def visible(dt, fields, filters=None, **kwargs):
    if not frappe.has_permission(dt, "read"):
        return []
    return frappe.get_list(dt, fields=fields, filters=filters or {}, limit_page_length=0, **kwargs)


def can_manage():
    return bool(set(frappe.get_roles()) & {"Sales Manager","System Manager"})


def managers():
    frappe.only_for(["Sales Manager","System Manager"])


def period(filters):
    start = getdate(filters.get("from_date") or getdate().replace(day=1))
    end = getdate(filters.get("to_date") or nowdate())
    if end < start:
        frappe.throw(_("End date must be on or after start date."))
    return start, end


def postponed_date(lead, fallback):
    return getdate(lead.alphax_next_contact_date or add_days(auto.stage_entry_datetime(lead.name,"Postponed"),fallback))


def visible_leads(executive=None, mine=False):
    columns = ["name","lead_name","lead_owner","owner","status","creation","alphax_next_contact_date","alphax_proposed_action"]
    columns += [f for f in CLOSING_FIELDS if frappe.get_meta("Lead").has_field(f)]
    filters = {"status":["in",SPEC_FLOW[:6]]}
    if mine:
        assigned = {r.reference_name for r in visible("ToDo",["reference_name"],dict(
            allocated_to=frappe.session.user, reference_type="Lead",status="Open"))}
        owned = visible("Lead",columns,filters,or_filters={"lead_owner":frappe.session.user,"owner":frappe.session.user})
        linked = visible("Lead",columns,{**filters,"name":["in",list(assigned)]}) if assigned else []
        rows = {r.name:r for r in owned+linked}
        return [r for r in rows.values() if (r.lead_owner or r.owner)==frappe.session.user or r.name in assigned]
    rows = visible("Lead",columns,filters)
    return [r for r in rows if not executive or (r.lead_owner or r.owner)==executive]


def lead_tasks(lead, today, settings):
    stage = lead.status
    entry = auto.stage_entry_datetime(lead.name, stage)
    if stage == "Postponed":
        yield "Contact postponed Lead", postponed_date(lead,cint(settings.get("postponed_default_revisit_days") or 30)), "Lead", lead.name
    elif stage == "Lead":
        contacted = frappe.db.exists("Communication",{"reference_doctype":"Lead","reference_name":lead.name,"communication_type":"Communication","creation":[">=",entry]})
        if not contacted and not {"meeting","follow-up"}.intersection(auto.activity_since(lead.name,entry)):
            yield "Make first contact", add_days(lead.creation,1), "Lead", lead.name
    elif stage == "Interested":
        if "meeting" not in auto.activity_since(lead.name,entry):
            yield "Schedule meeting", add_days(entry,3), "Lead", lead.name
    elif stage in ("Qualified lead","Quotation"):
        quotes = auto.quotations_for_lead(lead.name,{"docstatus":["<",2]},("name","docstatus","status","valid_till"))
        if not quotes:
            yield "Prepare quotation", add_days(entry,5 if stage=="Qualified lead" else 0), "Lead", lead.name
        for q in quotes:
            if not frappe.has_permission("Quotation","read",q.name):
                continue
            if q.docstatus == 0:
                yield "Review draft quotation", getdate(entry), "Quotation", q.name
            elif q.valid_till and q.status in ("Open","Replied","Expired"):
                due = getdate(q.valid_till)
                deadline = due if due <= today else validity_notice_date(due,cint(settings.get("wf04_days_before") or 2),settings)
                yield ("Review expired quotation" if due < today else "Follow up quotation"), deadline, "Quotation", q.name
    elif stage == "Contract Under Signing":
        elapsed = max(0,date_diff(today,getdate(entry)))
        due = add_days(entry,max(3,3*(elapsed//3)))
        if auto.activity_since(lead.name,due):
            due = add_days(due,3)
        yield "Follow up contract", due, "Lead", lead.name
        close = next((lead.get(f) for f in CLOSING_FIELDS if lead.get(f)), None)
        if close:
            yield "Review expected closing", close, "Lead", lead.name


def worklist(filters):
    today = getdate()
    horizon = getdate(add_days(today,max(0,cint(filters.get("days") or 0))))
    rows = []
    settings = get_settings()
    leads = visible_leads(mine=True)
    active = set()
    for lead in leads:
        if auto.is_paused(lead.name):
            continue
        active.add(lead.name)
        for task, due, dt, name in lead_tasks(lead,today,settings):
            due = getdate(due)
            if due <= horizon:
                rows.append(dict(lead=lead.name,customer=lead.lead_name,stage=lead.status,task=task,due=due,
                        reference_doctype=dt,reference_name=name,executive=lead.lead_owner or lead.owner))
        if frappe.has_permission("AlphaX Email Draft","read"):
            for draft in visible("AlphaX Email Draft",["name","creation"],{"reference_doctype":"Lead","reference_name":lead.name,"status":"Draft"}):
                rows.append(dict(lead=lead.name,customer=lead.lead_name,stage=lead.status,task="Review email draft",
                        due=getdate(draft.creation),reference_doctype="AlphaX Email Draft",reference_name=draft.name,executive=lead.lead_owner or lead.owner))
    # Quotation drafts have their own reference, including customer/opportunity-linked quotes.
    owned_leads = {row.name: row for row in leads if row.name in active}
    if owned_leads:
        for draft in visible("AlphaX Email Draft", ["name","creation","reference_name"],
                             {"reference_doctype":"Quotation","status":"Draft"}):
            if not frappe.has_permission("Quotation","read",draft.reference_name):
                continue
            parent = owned_leads.get(auto.lead_for_quotation(draft.reference_name))
            if parent:
                rows.append(dict(lead=parent.name,customer=parent.lead_name,stage=parent.status,task="Review email draft",
                    due=getdate(draft.creation),reference_doctype="AlphaX Email Draft",reference_name=draft.name,
                    executive=parent.lead_owner or parent.owner))
    rows.sort(key=lambda r:(r["due"],r["lead"],r["task"]))
    return [col("due","Due","Date",100),col("task","Next action",width=200),col("customer","Lead name",width=160),
            col("reference_name","Open record","Dynamic Link",170,"reference_doctype"),col("lead","Lead","Link",135,"Lead"),
            col("stage","Stage"),col("executive","Lead owner","Link",160,"User")],rows,None,None,[
                {"label":_("Overdue"),"value":sum(r["due"]<today for r in rows),"datatype":"Int","indicator":"Orange"},
                {"label":_("Due today"),"value":sum(r["due"]==today for r in rows),"datatype":"Int","indicator":"Blue"},
                {"label":_("Upcoming"),"value":sum(r["due"]>today for r in rows),"datatype":"Int","indicator":"Grey"}]


def is_exception(row):
    rule = row.rule or ""
    return ("escalation" in rule.lower() or "(approvers)" in rule or rule in (
        "WF-05 Expected closing passed","WF-04 Daily lost quotation","WF-04 Valid Till reached, no activity")
        or (rule.startswith("WF-05 ") and any(s in (row.subject or "").lower() for s in ("escalation","approver"))))


def exceptions(filters):
    managers()
    closed = filters.get("state") == "Resolved"
    rows = []
    accessible = {l.name:l for l in visible("Lead",["name","lead_owner","owner","status"])}
    seen = set()
    for r in visible(auto.LOG_DT,["name","rule","subject","lead","creation","resolution","resolution_reference","assigned_executive","recipients","reference_doctype","reference_name","trigger_date","status"],
                     {"lead":["is","set"]},order_by="creation desc"):
        lead=accessible.get(r.lead)
        if not lead or not is_exception(r) or (r.status=="Skipped" and not r.resolution):
            continue
        executive = lead.lead_owner or lead.owner
        if filters.get("executive") and filters.executive != executive:
            continue
        state = r.resolution or "Open"
        evidence = r.resolution_reference
        if state == "Open" and r.rule.startswith("WF-02 No quotation"):
            quotes = auto.quotations_for_lead(r.lead,{"docstatus":["<",2]})
            if quotes or lead.status!="Quotation":
                state = "Resolved"
                evidence = "Quotation linked" if quotes else "Lead stage changed"
                if quotes and frappe.has_permission("Quotation","read",quotes[0].name):
                    evidence = quotes[0].name
        elif state=="Open" and r.rule.startswith("WF-05 ") and lead.status in SPEC_FLOW[6:]:
            state,evidence="Resolved",lead.status
        group = (r.lead,r.rule,r.reference_doctype,r.reference_name)
        if not closed and group in seen:
            continue
        seen.add(group)
        if (state=="Resolved") != closed:
            continue
        response = None
        if frappe.has_permission("Comment","read"):
            comments = frappe.get_list("Comment",filters={"reference_doctype":"Lead","reference_name":r.lead,
                "comment_type":"Comment","creation":[">=",r.creation]},
                fields=["owner","creation","content"],order_by="creation desc",limit_page_length=1)
            response = comments[0] if comments else None
        amount, currency = None, None
        if r.reference_doctype=="Quotation" and r.reference_name and frappe.has_permission("Quotation","read",r.reference_name):
            amount, currency = frappe.db.get_value("Quotation",r.reference_name,["grand_total","currency"]) or (None,None)
        rows.append(dict(r,executive=executive,state=state,evidence=evidence,amount=amount,currency=currency,
                last_response=frappe.utils.strip_html(response.content or "")[:180] if response else None,
                response_by=response.owner if response else None))
    return [col("lead","Lead","Link",145,"Lead"),col("subject","Exception",width=290),col("executive","Sales executive","Link",150,"User"),
            col("assigned_executive","Assigned to","Link",145,"User"),col("creation","Raised","Datetime",145),
            col("recipients","Notified users",width=200),col("last_response","Latest comment",width=200),col("response_by","Comment by","Link",150,"User"),
            col("amount","Quotation value","Currency",130,"currency"),col("currency","Currency",width=80),col("evidence","Resolution evidence",width=170),col("name","Action record","Link",145,auto.LOG_DT)],rows


@frappe.whitelist(methods=["POST"])
def manage_exception(log_name, decision, note, assignee=None):
    managers()
    frappe.db.sql("select name from `tabAlphaX Automation Log` where name=%s for update",(log_name,))
    log = frappe.get_doc(auto.LOG_DT,log_name)
    log.check_permission("read")
    if not log.lead or not is_exception(log) or not (note or "").strip():
        frappe.throw(_("Choose an exception and enter an action note."))
    lead=frappe.get_doc("Lead",log.lead)
    lead.check_permission("write")
    if log.resolution=="Resolved":
        frappe.throw(_("This exception has already been resolved."))
    if decision=="Assign":
        if not assignee or not frappe.db.exists("User",{"name":assignee,"enabled":1}):
            frappe.throw(_("Select an enabled assignee."))
        from frappe.desk.form.assign_to import add
        add(dict(doctype="Lead",name=lead.name,assign_to=[assignee],description=note))
        values={"assigned_executive":assignee}
    elif decision=="Resolve":
        values=dict(resolution="Resolved",resolution_reference=note[:140],resolved_on=now_datetime())
    else:
        frappe.throw(_("Invalid action"))
    frappe.db.set_value(auto.LOG_DT,log.name,values)
    lead.add_comment("Comment",frappe.utils.escape_html(f"{decision} · {log.name} · {assignee or ''} {note}"))
    from alphax_crm.crm.action_history import record
    record("Exception "+decision,log.doctype,log.name,log.lead,detail=note)


def action_report(filters):
    managers()
    start,end=period(filters)
    conditions={"occurred_on":["between",[str(start)+" 00:00:00",str(end)+" 23:59:59.999999"]]}
    if filters.get("executive"):
        conditions["executive"]=filters.executive
    if filters.get("actor"):
        conditions["actor_user"]=filters.actor
    rows=frappe.get_all("AlphaX CRM Action",fields=["occurred_on","action","actor_user","actor_name","action_source","initiated_by","executive","lead","reference_doctype","reference_name","detail"],filters=conditions,order_by="occurred_on desc")
    rows=[r for r in rows if getdate(r.occurred_on)<=end and (not r.lead or frappe.has_permission("Lead","read",r.lead))
          and frappe.has_permission(r.reference_doctype,"read",r.reference_name)]
    return [col("occurred_on","Time","Datetime"),col("action","Action",width=195),col("actor_name","Executed by"),col("actor_user","User ID","Link",165,"User"),
            col("action_source","Source"),col("initiated_by","Request user","Link",150,"User"),col("executive","Executive at action","Link",160,"User"),
            col("lead","Lead","Link",140,"Lead"),col("reference_name","Evidence","Dynamic Link",160,"reference_doctype"),col("detail","Detail",width=240)],rows


def scorecard(filters):
    managers()
    start,end=period(filters)
    totals=defaultdict(Counter)
    for lead in visible("Lead",["lead_owner","owner","status","creation","won_or_lost_date"]):
        user=lead.lead_owner or lead.owner
        if filters.get("executive") and filters.executive!=user:
            continue
        counts=totals[user]
        if start<=getdate(lead.creation)<=end:
            counts["new"]+=1
        if lead.status in SPEC_FLOW[:6]:
            counts["open"]+=1
        if lead.won_or_lost_date and start<=getdate(lead.won_or_lost_date)<=end:
            if lead.status=="Won":
                counts["won"]+=1
            elif lead.status in ("Lost with reason","Lost Quotation"):
                counts["lost"]+=1
    actions=action_report(frappe._dict(from_date=start,to_date=end))[1]
    for a in actions:
        if a.action_source=="User" and (not filters.get("executive") or a.actor_user==filters.executive):
            counts = totals[a.actor_user]
            counts["actions"] += 1
            if a.action == "AlphaX Follow-up Created":
                counts["followups"] += 1
            elif a.action == "Quotation Submitted":
                counts["quotations"] += 1
            elif a.action == "Communication Sent" and a.detail == "Email":
                counts["emails"] += 1
    data=[]
    for user,c in sorted(totals.items()):
        n=c["won"]+c["lost"]
        data.append(dict(c,executive=user,full_name=frappe.utils.get_fullname(user),win_rate=round(100*c["won"]/n,1) if n else None))
    return [col("full_name","Sales executive"),col("executive","User ID","Link",165,"User"),col("new","New leads","Int",100),
            col("open","Open today","Int",100),col("won","Won","Int",85),col("lost","Lost","Int",85),col("win_rate","Win rate","Percent",100),
            col("actions","User actions","Int",115),col("followups","Follow-ups logged","Int",120),
            col("emails","Emails logged","Int",115),col("quotations","Quotes submitted","Int",120)],data, None, {
                "data":{"labels":[r["full_name"] for r in data[:12]],"datasets":[
                    {"name":_("Won"),"values":[r.get("won",0) for r in data[:12]]},
                    {"name":_("Lost"),"values":[r.get("lost",0) for r in data[:12]]}]},
                "type":"bar","colors":["#237c72","#af6657"]} if data else None


def forecast(filters):
    managers()
    start,end=period(filters)
    fields=["name","opportunity_owner","owner","expected_closing","opportunity_amount","currency","probability","status"]
    from alphax_crm.crm.commercial import closed_states
    rows=visible("Opportunity",fields,{"expected_closing":["between",[start,end]],"status":["not in",closed_states()]})
    data=[]
    for r in rows:
        r.executive=r.opportunity_owner or r.owner
        if filters.get("executive") and r.executive!=filters.executive:
            continue
        r.weighted=flt(r.opportunity_amount)*min(100,max(0,flt(r.probability)))/100
        data.append(r)
    data.sort(key=lambda r:(r.expected_closing,r.executive,r.name))
    return [col("executive","Sales executive","Link",155,"User"),col("name","Opportunity","Link",155,"Opportunity"),col("expected_closing","Expected close","Date",125),
            col("currency","Currency","Link",90,"Currency"),col("opportunity_amount","Open value","Currency",145,"currency"),
            col("probability","Probability","Percent",115),col("weighted","Weighted value","Currency",145,"currency")],data


def resolve_missing_quote(doc, method=None):
    """Persist resolution evidence while the quotation and its creator are known."""
    lead = auto.lead_for_quotation(doc)
    if not lead or doc.docstatus == 2:
        return
    rows = frappe.get_all(auto.LOG_DT,filters={"lead":lead,"rule":["like","WF-02 No quotation%"],
                             "resolution":["is","not set"]},pluck="name")
    from alphax_crm.crm.action_history import record
    for name in rows:
        frappe.db.set_value(auto.LOG_DT,name,dict(resolution="Resolved",resolution_reference=doc.name,resolved_on=now_datetime()))
        record("Missing quotation resolved", "Quotation", doc.name, lead, True, detail=name)


def reconcile_cancelled_quote(doc, method=None):
    lead = auto.lead_for_quotation(doc)
    if not lead:
        return
    replacements = auto.quotations_for_lead(lead, {"docstatus":["<",2]})
    records = frappe.get_all(auto.LOG_DT, filters={"lead":lead,"rule":["like","WF-02 No quotation%"],
                         "resolution":"Resolved","resolution_reference":doc.name}, pluck="name")
    for name in records:
        if replacements:
            values = {"resolution_reference":replacements[0].name}
        elif frappe.db.get_value("Lead",lead,"status")=="Quotation":
            values = dict(resolution=None,resolution_reference=None,resolved_on=None)
        else:
            values = {"resolution_reference":"Lead stage changed"}
        frappe.db.set_value(auto.LOG_DT,name,values)
