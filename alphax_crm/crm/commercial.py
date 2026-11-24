"""Commercial analysis with one current amount per quotation revision family."""
import hashlib
import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate
from alphax_crm.crm.sales_desk import col, managers, period, visible
from alphax_crm.crm.utils import get_settings

SNAPSHOT = "AlphaX Forecast Snapshot"


def validate_replacement(doc, method=None):
    previous = doc.get("alphax_replaces_quotation")
    if not previous:
        return
    if doc.get("amended_from") and doc.amended_from != previous:
        frappe.throw(_("Choose the ERPNext amendment parent as the replaced quotation."))
    prior = frappe.get_doc("Quotation",previous)
    prior.check_permission("read")
    if (prior.company,prior.quotation_to,prior.party_name,prior.currency) != (doc.company,doc.quotation_to,doc.party_name,doc.currency):
        frappe.throw(_("The replacement must belong to the same company, party and currency."))
    seen = {doc.name}
    while previous:
        if previous in seen:
            frappe.throw(_("A quotation revision cannot refer back to itself."))
        seen.add(previous)
        parent = frappe.db.get_value("Quotation",previous,["alphax_replaces_quotation","amended_from"],as_dict=True)
        previous = (parent.alphax_replaces_quotation or parent.amended_from) if parent else None


def families(quotes):
    index = {q.name:q for q in quotes}
    groups = {}
    for q in quotes:
        root=q.name
        visited={root}
        while True:
            parent=index[root].get("alphax_replaces_quotation") or index[root].get("amended_from")
            if parent not in index or parent in visited:
                break
            visited.add(parent)
            root=parent
        groups.setdefault(root,[]).append(q)
    return groups


def revisions(filters):
    managers()
    start,end=period(filters)
    rows=visible("Quotation",["name","owner","creation","transaction_date","currency","grand_total","docstatus","status","party_name",
            "amended_from","alphax_replaces_quotation","order_lost_reason","quotation_to","opportunity"])
    from alphax_crm.crm.automation import lead_for_quotation
    from alphax_crm.crm.bi_report import fetch_lead_dim_map
    lead_by_quote = {q.name:lead_for_quotation(q) for q in rows}
    linked = {lead for lead in lead_by_quote.values() if lead}
    permitted = [r.name for r in visible("Lead", ["name"], {"name": ["in", list(linked)]})] if linked else []
    dims = fetch_lead_dim_map(list(permitted))
    output=[]
    for root,chain in families(rows).items():
        chain.sort(key=lambda q:(q.creation,q.name))
        current=next((q for q in reversed(chain) if q.docstatus==1),None)
        latest=chain[-1]
        if not start<=getdate(latest.transaction_date)<=end:
            continue
        if filters.get("executive") and latest.owner!=filters.executive:
            continue
        amount=flt(current.grand_total) if current else 0
        reason=current.order_lost_reason if current and current.status=="Lost" else None
        if current and current.status=="Lost" and not reason:
            reason=", ".join(frappe.get_all("Quotation Lost Reason Detail",filters={"parent":current.name,"parenttype":"Quotation"},pluck="lost_reason"))
        unit = (dims.get(lead_by_quote.get(latest.name)) or {}).get("custom_business_line_")
        output.append(dict(business_unit=unit,root=root,latest=latest.name,current=current.name if current else None,versions=len(chain),party=latest.party_name,
             executive=latest.owner,currency=latest.currency,initial=chain[0].grand_total,amount=amount,change=amount-flt(chain[0].grand_total) if current else None,
             status=current.status if current else latest.status,reason=reason))
    return [col("root","Original","Link",150,"Quotation"),col("latest","Latest version","Link",145,"Quotation"),col("current","Latest submitted","Link",145,"Quotation"),
            col("versions","Versions","Int",80),col("executive","Latest creator","Link",155,"User"),col("party","Party"),col("business_unit","Business unit"),col("status","Status"),
            col("currency","Currency","Data",85),col("initial","Original value","Currency",120,"currency"),col("amount","Submitted value","Currency",120,"currency"),
            col("change","Change","Currency",105,"currency"),col("reason","Loss reason",width=190)],output


def closed_states():
    settings=get_settings()
    return list({"Converted","Closed","Lost",settings.get("won_status") or "Converted",settings.get("lost_status") or "Lost"})


def snapshot_week(day):
    day=getdate(day)
    return getdate(add_days(day,-((day.weekday()+1)%7)))


def snapshot_forecast():
    """Weekly Sunday baseline. A missed Sunday is captured on the next daily run."""
    week=snapshot_week(getdate())
    if frappe.db.get_default("alphax_forecast_snapshot_week")==str(week):
        return
    rows=frappe.get_all("Opportunity",filters={"status":["not in",closed_states()],"expected_closing":["is","set"]},
        fields=["name","opportunity_owner","owner","currency","opportunity_amount","expected_closing","probability"])
    for r in rows:
        key=hashlib.sha256(f"{week}|{r.name}".encode()).hexdigest()
        if frappe.db.exists(SNAPSHOT,{"snapshot_key":key}):
            continue
        frappe.get_doc(dict(doctype=SNAPSHOT,snapshot_key=key,week_start=week,opportunity=r.name,
            executive=r.opportunity_owner or r.owner,expected_close=r.expected_closing,currency=r.currency,
            amount=r.opportunity_amount,probability=r.probability,executed_by=frappe.session.user)).insert(ignore_permissions=True)
    frappe.db.set_default("alphax_forecast_snapshot_week",str(week))


def movements(filters):
    managers()
    week=snapshot_week(filters.get("week_start") or getdate())
    historic=frappe.get_all(SNAPSHOT,fields=["opportunity","executive","currency","amount","probability","expected_close","creation"],filters={"week_start":week})
    current={r.name:r for r in visible("Opportunity",["name","expected_closing","status","opportunity_amount","currency","probability"])}
    rows=[]
    for h in historic:
        r=current.get(h.opportunity)
        if not r or (filters.get("executive") and filters.executive!=h.executive):
            continue
        slip=date_diff(r.expected_closing,h.expected_close) if r.expected_closing else None
        rows.append(dict(h,current_date=r.expected_closing,slip=slip,current_status=r.status,
            baseline_weighted=flt(h.amount)*flt(h.probability)/100))
    return [col("executive","Executive at snapshot","Link",165,"User"),col("opportunity","Opportunity","Link",145,"Opportunity"),
            col("creation","Captured","Datetime"),col("expected_close","Original close","Date",115),col("current_date","Current close","Date",115),
            col("slip","Days moved","Int",105),col("current_status","Now"),col("currency","Currency",width=80),
            col("baseline_weighted","Baseline weighted","Currency",140,"currency")],rows
