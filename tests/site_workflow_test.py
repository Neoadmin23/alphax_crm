"""Scenario tests for the approved Lead workflow (spec A, WF-01..07, C) on a real ERPNext site.
Needs tests/live_site_fields.py run first and tests/mock_ai.py on :8090.
Copy into the app as alphax_crm/zz_wf_test.py: bench --site SITE execute alphax_crm.zz_wf_test.run"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

results = []
RUN = frappe.generate_hash(length=4)


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""), flush=True)


def raises(fn, *a, **kw):
	frappe.db.savepoint("ax_test")
	try:
		fn(*a, **kw)
		return None
	except Exception as e:
		frappe.db.rollback(save_point="ax_test")
		frappe.set_user("Administrator")
		return e


def settings(**values):
	s = frappe.get_single("AlphaX CRM Settings")
	for k, v in values.items():
		s.set(k, v)
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")


def user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
	return email


REP = "rep.wf@test.local"
MGR = "manager.wf@test.local"


def new_lead(stage=None, **kw):
	values = {"doctype": "Lead", "first_name": "WF", "lead_name": f"WF {RUN} {frappe.generate_hash(length=3)}",
		"email_id": f"wf.{frappe.generate_hash(length=6)}@client.sa", "mobile_no": "+9665" + frappe.generate_hash(length=8)[:8].translate(str.maketrans("abcdef", "123456")),
		"source": "Website", "lead_owner": REP, "company_name": "Client Co"}
	values.update(kw)
	doc = frappe.get_doc(values)
	doc.flags.alphax_skip_ai = True
	doc.insert(ignore_permissions=True)
	if stage:
		move(doc.name, stage)
	return frappe.get_doc("Lead", doc.name)


def move(lead, *stages, as_user="Administrator", **extra):
	frappe.set_user(as_user)
	try:
		for st in stages:
			d = frappe.get_doc("Lead", lead)
			d.status = st
			for k, v in extra.items():
				d.set(k, v)
			d.save(ignore_permissions=as_user == "Administrator")
	finally:
		frappe.set_user("Administrator")


def backdate_stage(lead, stage, days=0, hours=0):
	when = now_datetime() - timedelta(days=days, hours=hours)
	name = frappe.db.get_value("AlphaX Stage Transition Log", {"reference_name": lead, "field_label": "Lead Stage", "to_value": stage},
		"name", order_by="changed_on desc")
	if name:
		frappe.db.set_value("AlphaX Stage Transition Log", name, "changed_on", when, update_modified=False)
	else:
		frappe.db.set_value("Lead", lead, "creation", when, update_modified=False)


def logs(lead=None, rule=None, ref=None):
	f = {}
	if lead:
		f["lead"] = lead
	if rule:
		f["rule"] = ["like", f"%{rule}%"]
	if ref:
		f["reference_name"] = ref
	return frappe.get_all("AlphaX Automation Log", filters=f, fields=["name", "rule", "status", "recipients", "subject",
		"send_after", "communication", "dedupe_key", "message"], order_by="creation asc")


def quotation(lead, valid_till=10, submit=True, owner=None, **kw):
	company = frappe.db.get_value("Company", {}, "name")
	item = frappe.db.get_value("Item", {"is_sales_item": 1, "disabled": 0}, "name")
	q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Lead", "party_name": lead, "company": company,
		"transaction_date": kw.pop("transaction_date", nowdate()),
		"valid_till": add_days(nowdate(), valid_till) if valid_till is not None else None,
		"contact_email": frappe.db.get_value("Lead", lead, "email_id"),
		"items": [{"item_code": item, "qty": 1, "rate": 1000}], **kw})
	if owner:
		frappe.set_user(owner)
	try:
		q.insert(ignore_permissions=True)
		if submit:
			q.submit()
	finally:
		frappe.set_user("Administrator")
	return q


def run():
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	from alphax_crm.crm import automation as auto
	from alphax_crm.crm import workflow as wf

	user(REP, ["Sales User"])
	user(MGR, ["Sales Manager", "Sales User"])
	for name in frappe.get_all("User", filters=[["name", "like", "%@test.local"], ["name", "not in", [REP, MGR]]], pluck="name"):
		frappe.db.set_value("User", name, "enabled", 0)  # keep the approver list to MGR
	for lr in ("Price too high", "Chose competitor"):
		if not frappe.db.exists("Quotation Lost Reason", lr):
			frappe.get_doc({"doctype": "Quotation Lost Reason", "order_lost_reason": lr}).insert(ignore_permissions=True)
	always = "Sunday\nMonday\nTuesday\nWednesday\nThursday\nFriday\nSaturday"
	settings(business_days=always, business_start="00:00:00", business_end="23:59:00", business_hours_only=1,
		notify_by_email=1, approver_role="Sales Manager", ai_enabled=1, ai_base_url="http://127.0.0.1:8090",
		ai_provider="Ollama", ai_chat_path="/api/chat", ai_next_action_todo=0, ai_intent_detection=1, wf04_ai_draft=1,
		stage_flow_bypass_roles="System Manager", auto_opportunity_enabled=0, dedup_enabled=0)
	frappe.db.commit()

	# ------------------------------------------------------------------ C: calendar
	cal = auto.calendar(frappe._dict(business_days="Sunday\nMonday\nTuesday\nWednesday\nThursday",
		business_start="08:00:00", business_end="17:00:00"))
	thu = datetime(2026, 10, 29, 10, 0)  # Thursday
	check("calendar: Friday/Saturday are not working days", not auto.is_working_day(getdate("2026-10-30"), cal)
		and not auto.is_working_day(getdate("2026-10-31"), cal) and auto.is_working_day(getdate("2026-11-01"), cal))
	check("calendar: next opening after Thursday 18:00 is Sunday 08:00",
		auto.next_business_start(datetime(2026, 10, 29, 18, 0), cal) == datetime(2026, 11, 1, 8, 0))
	check("calendar: Thu 10:00 -> Sun 10:00 = 24 working hours (weekend excluded)",
		auto.working_hours_between(thu, datetime(2026, 11, 1, 10, 0), cal) == 24.0,
		auto.working_hours_between(thu, datetime(2026, 11, 1, 10, 0), cal))
	cal.mode = "Business hours only"
	check("calendar: business-hours mode counts 7h + 2h", auto.working_hours_between(thu, datetime(2026, 11, 1, 10, 0), cal) == 9.0)
	cal.holidays = {getdate("2026-11-01")}
	check("calendar: holiday list respected", not auto.is_working_day(getdate("2026-11-01"), cal))

	# ------------------------------------------------------------------ A: mapping both ways
	lead = new_lead()
	check("A: new lead -> stage Lead / status Lead", (lead.status, lead.custom_lead_status) == ("Lead", "Lead"), (lead.status, lead.custom_lead_status))
	move(lead.name, "Interested", as_user=REP)
	check("A: Interested -> Lead status", frappe.db.get_value("Lead", lead.name, "custom_lead_status") == "Lead")
	move(lead.name, "Qualified lead", as_user=REP)
	move(lead.name, "Quotation", as_user=REP)
	check("A: Quotation -> Prospect", frappe.db.get_value("Lead", lead.name, "custom_lead_status") == "Prospect")
	d = frappe.get_doc("Lead", lead.name)
	d.custom_lead_status = "Cold Lead"
	e = raises(lambda: d.save(ignore_permissions=True))
	check("A+WF-05: status Cold Lead -> stage Postponed needs Next Contact Date", e and "Next Contact Date" in str(e), e)
	d = frappe.get_doc("Lead", lead.name)
	d.custom_lead_status = "Cold Lead"
	d.alphax_next_contact_date = add_days(nowdate(), 5)
	d.save(ignore_permissions=True)
	check("A: status Cold Lead -> stage Postponed", frappe.db.get_value("Lead", lead.name, "status") == "Postponed")
	check("A: transitions logged for direct stage changes", frappe.db.count("AlphaX Stage Transition Log",
		{"reference_name": lead.name, "field_label": "Lead Stage"}) >= 4)

	# ------------------------------------------------------------------ WF-01
	lead = new_lead()
	e = raises(move, lead.name, "Won", as_user=REP)
	check("WF-01: Lead -> Won blocked", e and "skips a step" in str(e), e)
	e = raises(move, lead.name, "Replied", as_user=REP)
	check("WF-01: non-approved stage blocked", e and "not a stage in the approved" in str(e), e)
	frappe.set_user(REP)
	d = frappe.get_doc({"doctype": "Lead", "first_name": "Imp", "lead_name": f"Imported {RUN}", "status": "Won", "lead_owner": REP,
		"email_id": f"imp.{RUN}@x.sa", "mobile_no": "+966500000001", "source": "Website"})
	d.flags.alphax_skip_ai = True
	d.insert()
	frappe.set_user("Administrator")
	check("WF-01: new lead created at Won starts at Lead", d.status == "Lead", d.status)
	legacy = new_lead()
	frappe.db.set_value("Lead", legacy.name, "status", "Replied")
	d = frappe.get_doc("Lead", legacy.name)
	d.company_name = "Edited"
	d.save(ignore_permissions=True)
	check("WF-01: legacy-stage lead can still be edited", frappe.db.get_value("Lead", legacy.name, "company_name") == "Edited")
	move(legacy.name, "Interested", as_user=REP)
	check("WF-01: legacy stage continues from the start", frappe.db.get_value("Lead", legacy.name, "status") == "Interested")
	frappe.set_user(REP)
	try:
		frappe.client.set_value("Lead", legacy.name, "status", "Contract Under Signing")
		check("WF-01: quick edit (list view) cannot skip", False)
	except Exception as e:
		check("WF-01: quick edit (list view) cannot skip", "skips a step" in str(e), e)
	frappe.set_user("Administrator")

	# ------------------------------------------------------------------ core protection
	lead = new_lead("Interested")
	move(lead.name, "Qualified lead", "Quotation", as_user=REP)
	q = quotation(lead.name, owner=REP)
	move(lead.name, "Contract Under Signing", as_user=REP)
	check("core: stage beyond Quotation is kept (ERPNext no longer forces 'Quotation')",
		frappe.db.get_value("Lead", lead.name, "status") == "Contract Under Signing", frappe.db.get_value("Lead", lead.name, "status"))
	from erpnext.crm.doctype.lead.lead import make_customer

	cust = make_customer(lead.name)
	cust.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	cust.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	cust.insert(ignore_permissions=True)
	check("core: creating the Customer does not push the Lead to 'Converted'",
		frappe.db.get_value("Lead", lead.name, "status") == "Contract Under Signing", frappe.db.get_value("Lead", lead.name, "status"))
	e = raises(move, lead.name, "Won", as_user=REP)
	check("WF-06: Won needs Contract Signed + Won date", e and "Contract" in str(e), e)
	move(lead.name, "Won", as_user=REP, custom_contract="Signed", won_or_lost_date=nowdate())
	check("WF-06: Won saved as Won (not Converted), status Customer",
		frappe.db.get_value("Lead", lead.name, ["status", "custom_lead_status"]) == ("Won", "Customer"),
		frappe.db.get_value("Lead", lead.name, ["status", "custom_lead_status"]))
	check("3-way link: quotation still found after ERPNext relinked it to the Customer",
		any(x.name == q.name for x in auto.quotations_for_lead(lead.name)), frappe.db.get_value("Quotation", q.name, ["quotation_to", "party_name"]))

	# ------------------------------------------------------------------ WF-02
	lead = new_lead("Interested")
	move(lead.name, "Qualified lead", "Quotation", as_user=REP)
	alert = logs(lead.name, "WF-02 No quotation (alert)")
	check("WF-02: immediate alert to Lead Owner when no quotation", len(alert) == 1 and REP in alert[0].recipients, alert)
	check("WF-02: alert emailed and logged on the Lead timeline", alert and alert[0].communication and
		frappe.db.get_value("Communication", alert[0].communication, ["communication_type", "reference_name"]) == ("Automated Message", lead.name))
	check("automated email does not count as sales activity", not frappe.db.get_value("Lead", lead.name, "alphax_last_activity")
		or frappe.db.get_value("Lead", lead.name, "alphax_last_activity_type") not in ("Email (Sent)",))
	backdate_stage(lead.name, "Quotation", days=1, hours=2)
	wf.wf02_hourly()
	check("WF-02: reminder after 24 working hours", len(logs(lead.name, "WF-02 No quotation (reminder)")) == 1)
	backdate_stage(lead.name, "Quotation", days=4)
	wf.wf02_hourly()
	esc = logs(lead.name, "WF-02 No quotation (escalation)")
	check("WF-02: escalation to Sales Manager after 72 working hours", len(esc) == 1 and MGR in esc[0].recipients, esc)
	wf.wf02_hourly()
	check("no duplicate reminders (unique key)", len(logs(lead.name, "WF-02")) == 3)
	q = quotation(lead.name, submit=False, owner=REP)
	created = logs(rule="WF-02 Quotation created", ref=q.name)
	check("WF-02: approvers notified when an agent creates a quotation", len(created) == 1 and MGR in created[0].recipients, created)

	# ------------------------------------------------------------------ WF-03
	lead = new_lead("Interested")
	e = raises(quotation, lead.name, valid_till=None)
	check("WF-03: Valid Till mandatory on Lead quotations", e and "Valid Till" in str(e), e)
	q = quotation(lead.name, owner=MGR)
	conf = logs(rule="WF-03 Quotation confirmation", ref=q.name)
	check("WF-03: confirmation to Lead Owner and creator", conf and {REP, MGR} <= set(conf[0].recipients.split("\n"))
		and conf[0].subject == "Your quotation has been created successfully", conf)
	check("WF-03: message has No., Date, Valid Till, Amount, Lead", conf and all(k in conf[0].message for k in
		("Quotation No.", "Valid Till", "Amount", "Lead / Company", q.name)), conf and conf[0].message)
	check("WF-03: earlier-stage Lead moved to Quotation", frappe.db.get_value("Lead", lead.name, ["status", "custom_lead_status"]) == ("Quotation", "Prospect"))
	check("WF-03: move logged on the Lead timeline", frappe.db.exists("Comment", {"reference_name": lead.name, "comment_type": "Info",
		"content": ["like", "%moved from%Interested%Quotation%"]}))

	# ------------------------------------------------------------------ WF-04
	l4 = new_lead("Interested")
	move(l4.name, "Qualified lead", "Quotation", as_user=REP)
	q1 = quotation(l4.name, valid_till=2, owner=REP, transaction_date=add_days(nowdate(), -10))
	wf.wf04_daily()
	t2 = logs(rule="WF-04 Expiring, no activity", ref=q1.name)
	check("WF-04 T-2: reminder to Lead Owner when no activity", len(t2) == 1 and t2[0].recipients == REP, t2)
	check("WF-04 T-2: AI-drafted client follow-up saved for review (not sent)",
		frappe.db.get_value("AlphaX Email Draft", {"reference_name": q1.name}, "status") == "Draft")
	wf.wf04_daily()
	check("WF-04: daily run does not repeat", len(logs(rule="WF-04", ref=q1.name)) == 1)
	l4b = new_lead("Interested")
	move(l4b.name, "Qualified lead", "Quotation", as_user=REP)
	q2 = quotation(l4b.name, valid_till=1, owner=REP, transaction_date=add_days(nowdate(), -5))
	frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Lead", "reference_name": l4b.name,
		"content": "Called the client, waiting for PO"}).insert(ignore_permissions=True)
	wf.wf04_daily()
	check("WF-04 T-2: activity -> validity notice only", len(logs(rule="WF-04 Validity notice", ref=q2.name)) == 1
		and not logs(rule="WF-04 Expiring", ref=q2.name))
	l4c = new_lead("Interested")
	move(l4c.name, "Qualified lead", "Quotation", as_user=REP)
	q3 = quotation(l4c.name, valid_till=0, owner=REP, transaction_date=add_days(nowdate(), -20))
	wf.wf04_daily()
	t0 = logs(rule="WF-04 Valid Till reached", ref=q3.name)
	check("WF-04 T0: owner + Sales Manager alerted", len(t0) == 1 and {REP, MGR} <= set(t0[0].recipients.split("\n")), t0)
	l4d = new_lead("Interested")
	move(l4d.name, "Qualified lead", "Quotation", as_user=REP)
	q4 = quotation(l4d.name, valid_till=10, owner=REP, transaction_date=add_days(nowdate(), -30))
	frappe.db.set_value("Quotation", q4.name, "valid_till", add_days(nowdate(), -3))
	wf.wf04_daily()
	tp = logs(rule="WF-04 Expired, no action", ref=q4.name)
	check("WF-04 T+3: escalation proposes Lost Quotation", len(tp) == 1 and "Lost Quotation" in tp[0].subject
		and "Confirm Lost Quotation" in (frappe.db.get_value("Lead", l4d.name, "alphax_proposed_action") or ""), tp)
	check("WF-04 T+3: stage NOT changed without the user", frappe.db.get_value("Lead", l4d.name, "status") == "Quotation")
	frappe.set_user(REP)
	wf.confirm_lost_quotation(q4.name, "Price too high", "Budget cut")
	frappe.set_user("Administrator")
	check("WF-04: user confirms -> quotation Lost with reason, Lead Lost Quotation",
		frappe.db.get_value("Quotation", q4.name, "status") == "Lost"
		and frappe.db.get_value("Lead", l4d.name, ["status", "custom_lead_status"]) == ("Lost Quotation", "Inactive Lead")
		and not frappe.db.get_value("Lead", l4d.name, "alphax_proposed_action"),
		(frappe.db.get_value("Quotation", q4.name, "status"), frappe.db.get_value("Lead", l4d.name, ["status", "custom_lead_status", "alphax_proposed_action"])))
	frappe.db.delete("AlphaX Automation Log", {"rule": "WF-04 Lost quotation digest"})
	wf.lost_quotation_digest()
	dg = logs(rule="WF-04 Lost quotation digest")
	check("WF-04: daily lost-quotation follow-up to Sales Manager", dg and MGR in dg[-1].recipients and l4d.name in dg[-1].message, dg[-1:] )
	settings(business_days="Monday")  # pretend today is not a working day unless it is Monday
	if getdate(nowdate()).weekday() != 0:
		n = len(logs(rule="WF-04"))
		q5 = quotation(new_lead("Interested").name, valid_till=0, owner=REP)
		wf.wf04_daily()
		check("WF-04: does not run on non-working days", len(logs(rule="WF-04")) == n)
	settings(business_days=always)

	# ------------------------------------------------------------------ WF-06 Lost Quotation control
	l6 = new_lead("Interested")
	move(l6.name, "Qualified lead", "Quotation", as_user=REP)
	quotation(l6.name, owner=REP)
	e = raises(move, l6.name, "Lost Quotation", as_user=REP)
	check("WF-06: Lost Quotation needs a quotation marked Lost with reason", e and "marked Lost" in str(e), e)
	l6b = new_lead("Interested")
	move(l6b.name, "Qualified lead", "Quotation", as_user=REP)
	qa = quotation(l6b.name, owner=REP)
	qb = quotation(l6b.name, owner=REP)
	frappe.get_doc("Quotation", qa.name).declare_enquiry_lost([{"lost_reason": "Price too high"}], [], "too expensive")
	check("Lost on one of two quotations keeps the Lead open", frappe.db.get_value("Lead", l6b.name, "status") == "Quotation",
		frappe.db.get_value("Lead", l6b.name, "status"))
	frappe.get_doc("Quotation", qb.name).declare_enquiry_lost([{"lost_reason": "Chose competitor"}], [], "went elsewhere")
	check("Lost on the last quotation -> Lead Lost Quotation", frappe.db.get_value("Lead", l6b.name, "status") == "Lost Quotation")
	l6c = new_lead("Interested")
	move(l6c.name, "Qualified lead", "Quotation", as_user=REP)
	qc = quotation(l6c.name, owner=REP)
	frappe.get_doc("Quotation", qc.name).cancel()
	check("cancelling a quotation (to amend) does not mark the Lead lost", frappe.db.get_value("Lead", l6c.name, "status") == "Quotation",
		frappe.db.get_value("Lead", l6c.name, "status"))

	# ------------------------------------------------------------------ review fixes (0.41 audit)
	lr = new_lead("Interested")
	move(lr.name, "Qualified lead", "Quotation", as_user=REP)
	qr = quotation(lr.name, owner=REP)
	move(lr.name, "Contract Under Signing", as_user=REP)
	frappe.get_doc({"doctype": "Opportunity", "opportunity_from": "Lead", "party_name": lr.name,
		"company": frappe.db.get_value("Company", {}, "name")}).insert(ignore_permissions=True)
	frappe.get_doc("Quotation", qr.name).cancel()
	check("cancel: core cannot push a Contract Under Signing Lead back to Opportunity",
		frappe.db.get_value("Lead", lr.name, "status") == "Contract Under Signing", frappe.db.get_value("Lead", lr.name, "status"))
	ls = new_lead("Interested")
	move(ls.name, "Qualified lead", "Quotation", as_user=REP)
	qs1 = quotation(ls.name, owner=REP)
	quotation(ls.name, owner=REP)
	move(ls.name, "Postponed", as_user=REP, alphax_next_contact_date=add_days(nowdate(), 5))
	frappe.get_doc("Quotation", qs1.name).declare_enquiry_lost([{"lost_reason": "Price too high"}], [], "x")
	check("Set as Lost (other quotation open): Postponed Lead stays Postponed",
		frappe.db.get_value("Lead", ls.name, ["status", "custom_lead_status"]) == ("Postponed", "Cold Lead"),
		frappe.db.get_value("Lead", ls.name, ["status", "custom_lead_status"]))
	n_tr = frappe.db.count("AlphaX Stage Transition Log", {"reference_name": l6b.name, "to_value": "Lost Quotation"})
	check("Set as Lost (last quotation): transition + automation log recorded", n_tr >= 1
		and frappe.db.exists("AlphaX Automation Log", {"lead": l6b.name, "rule": "WF-06 Quotation marked Lost"}))
	lm = new_lead("Interested")
	m0 = frappe.db.get_value("Lead", lm.name, "modified")
	wf.set_stage_system(lm.name, "Qualified lead", "test move")
	check("system stage moves update 'modified' (stale forms cannot write the old stage back)",
		frappe.db.get_value("Lead", lm.name, "modified") > m0)
	e = raises(wf.confirm_lost_quotation, qr.name, "Price too high")
	check("Confirm Lost Quotation refused on a cancelled quotation / closed lead", e is not None)
	lx = new_lead("Interested")
	move(lx.name, "Qualified lead", "Quotation", as_user=REP)
	qx = quotation(lx.name, valid_till=10, owner=REP, transaction_date=add_days(nowdate(), -20))
	frappe.db.set_value("Quotation", qx.name, {"valid_till": add_days(nowdate(), -1), "status": "Expired"})
	wf.wf04_daily()
	check("WF-04 T0: still alerted after ERPNext marked the quotation Expired (weekend expiry)",
		len(logs(rule="WF-04 Valid Till reached", ref=qx.name)) == 1)
	frappe.db.set_value("Quotation", qx.name, "valid_till", add_days(nowdate(), -3))
	frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Lead", "reference_name": lx.name,
		"content": "Client asked for a new version"}).insert(ignore_permissions=True)
	wf.wf04_daily()
	check("WF-04 T+3: no escalation when someone acted after expiry", not logs(rule="WF-04 Expired, no action", ref=qx.name))
	lg = new_lead("Interested")
	frappe.db.set_value("Lead", lg.name, "status", "Replied", update_modified=False)  # legacy value from before 0.41
	quotation(lg.name, owner=REP)
	d = frappe.get_doc("Lead", lg.name)
	d.city = "Jeddah"
	e = raises(d.save, ignore_permissions=True)
	check("legacy-stage Lead stays editable after a quotation is submitted", e is None, e)
	frappe.db.delete("AlphaX Automation Log", {"rule": "ZZ test skipped"})
	auto.notify("ZZ test skipped", [], "x", "y", key="ZZ-skip-key")
	auto.notify("ZZ test skipped", [REP], "x", "y", key="ZZ-skip-key")
	sk = logs(rule="ZZ test skipped")
	check("a Skipped notification (no recipients) does not block the retry", len(sk) == 2 and sk[-1].status != "Skipped", sk)
	from unittest.mock import patch

	with patch("frappe.enqueue") as enq:
		wf.daily_0800()
	check("08:00 rules run as separate long-queue jobs", enq.call_count == 4 and all(c.kwargs.get("queue") == "long"
		for c in enq.call_args_list), enq.call_args_list)

	# ------------------------------------------------------------------ WF-05
	go_live = frappe.db.get_default(auto.GO_LIVE_KEY)
	frappe.db.set_default(auto.GO_LIVE_KEY, now_datetime())
	old = new_lead()
	backdate_stage(old.name, "Lead", days=40)  # pipeline Lead from before go-live, no transition logged
	wf.sla_daily()
	check("go-live: old leads without a logged stage entry do not flood reminders on day one", not logs(old.name, "WF-05"))
	frappe.db.set_default(auto.GO_LIVE_KEY, "2000-01-01 00:00:00")
	l5 = new_lead()
	backdate_stage(l5.name, "Lead", days=3)
	wf.sla_daily()
	r1 = logs(l5.name, "WF-05 Lead")
	check("WF-05 Lead: first reminder on day 3", len(r1) == 1 and "First reminder" in r1[0].subject, r1)
	backdate_stage(l5.name, "Lead", days=7)
	wf.sla_daily()
	r2 = logs(l5.name, "WF-05 Lead")
	check("WF-05 Lead: second reminder 4 days later (system notes are not 'activity')", len(r2) == 2 and "Second reminder" in r2[1].subject, r2)
	l5b = new_lead("Interested")
	frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Lead", "reference_name": l5b.name,
		"content": "Meeting booked for Sunday"}).insert(ignore_permissions=True)
	backdate_stage(l5b.name, "Interested", days=3)
	frappe.db.sql("update `tabComment` set creation=%s where reference_name=%s and comment_type='Comment'", (now_datetime(), l5b.name))
	wf.sla_daily()
	check("WF-05: real activity suppresses the reminder", not logs(l5b.name, "WF-05"))
	l5c = new_lead("Interested")
	backdate_stage(l5c.name, "Interested", days=7)
	frappe.db.set_value("Lead", l5c.name, "workflow_state", "Returned for Correction") if frappe.get_meta("Lead").has_field("workflow_state") else None
	wf.sla_daily()
	check("WF-05: reminders paused while 'Returned for Correction'", not logs(l5c.name, "WF-05"))
	frappe.db.set_value("Lead", l5c.name, "workflow_state", "Draft") if frappe.get_meta("Lead").has_field("workflow_state") else None
	wf.sla_daily()
	esc = logs(l5c.name, "WF-05")
	check("WF-05 Interested: day 7 escalation to Sales Manager, missed day-3 reminder caught up (per-rule)",
		esc and MGR in esc[-1].recipients and len({x.dedupe_key for x in esc}) == len(esc), esc)
	n_esc = len(logs(l5c.name, "WF-05"))
	wf.sla_daily()
	check("WF-05: per-rule keys, no repeats on the next run", len(logs(l5c.name, "WF-05")) == n_esc)
	lp = new_lead("Interested")
	move(lp.name, "Qualified lead", "Quotation", as_user=REP)
	quotation(lp.name, owner=REP)
	move(lp.name, "Postponed", as_user=REP, alphax_next_contact_date=nowdate())
	fup = frappe.get_all("AlphaX Follow-up", filters={"reference_name": lp.name}, fields=["next_follow_up_date", "summary"])
	check("WF-05 Postponed: next follow-up created with the Next Contact Date", fup and str(fup[0].next_follow_up_date) == nowdate(), fup)
	check("WF-05 Postponed: placeholder is not logged as a client contact", not frappe.db.exists("Communication",
		{"reference_name": lp.name, "subject": ["like", "Follow-up%"]}))
	wf.sla_daily()
	check("WF-05 Postponed: reminder on the Next Contact Date", len(logs(lp.name, "WF-05 Postponed follow-up")) == 1)
	frappe.db.set_value("Lead", lp.name, "alphax_next_contact_date", add_days(nowdate(), -2))
	frappe.db.sql("""update `tabAlphaX Stage Transition Log` set changed_on=%s where reference_name=%s""",
		(now_datetime() - timedelta(days=25), lp.name))  # postponed weeks ago, date passed, nobody commented
	wf.sla_daily()
	ov = logs(lp.name, "WF-05 Postponed overdue")
	check("WF-05 Postponed: Sales Managers told when no comment was added", len(ov) == 1 and MGR in ov[0].recipients,
		(ov, auto.activity_since(lp.name, add_days(nowdate(), -2))))
	lc = new_lead("Interested")
	move(lc.name, "Qualified lead", "Quotation", as_user=REP)
	quotation(lc.name, owner=REP)
	move(lc.name, "Contract Under Signing", as_user=REP)
	backdate_stage(lc.name, "Contract Under Signing", days=4)
	wf.sla_daily()
	c4 = logs(lc.name, "WF-05 Contract Under Signing")
	check("WF-05 Contract: Sales Manager notified on day 4", c4 and MGR in c4[-1].recipients and "day 4" in c4[-1].subject, c4)
	backdate_stage(lc.name, "Contract Under Signing", days=6)
	wf.sla_daily()
	check("WF-05 Contract: follow-up repeats every 3 days (day 6)", any("Follow-up" in x.subject for x in logs(lc.name, "WF-05 Contract")))
	lc2 = new_lead("Interested")
	move(lc2.name, "Qualified lead", "Quotation", as_user=REP)
	quotation(lc2.name, owner=REP)
	move(lc2.name, "Contract Under Signing", as_user=REP)
	backdate_stage(lc2.name, "Contract Under Signing", days=6)  # day 4 and 5 were Friday/Saturday
	wf.sla_daily()
	c6 = logs(lc2.name, "WF-05 Contract Under Signing")
	check("WF-05: a missed day-4 approver notice is still sent on the next working day",
		any(MGR in x.recipients and "day 4" in x.subject for x in c6) and any("Follow-up" in x.subject for x in c6), c6)
	opp = frappe.get_doc({"doctype": "Opportunity", "opportunity_from": "Lead", "party_name": lc.name,
		"expected_closing": add_days(nowdate(), -1), "company": frappe.db.get_value("Company", {}, "name")})
	opp.insert(ignore_permissions=True)
	check("core: Opportunity does not reset the stage", frappe.db.get_value("Lead", lc.name, "status") == "Contract Under Signing")
	wf.sla_daily()
	check("WF-05 Contract: alert when Expected Closing Date passed", len(logs(lc.name, "Expected closing passed")) == 1)

	# ------------------------------------------------------------------ WF-07 AI
	from alphax_crm.ai import sales

	la = new_lead("Interested")
	move(la.name, "Qualified lead", "Quotation", as_user=REP)
	quotation(la.name, owner=REP)
	comm = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
		"sent_or_received": "Received", "subject": "Re: quotation", "content": "Thanks, but we need to postpone this to next quarter.",
		"reference_doctype": "Lead", "reference_name": la.name, "sender": "client@x.sa"}).insert(ignore_permissions=True)
	r = sales.detect_intent(comm.name, la.name)
	check("WF-07: intent detected with suggested stage", r and r["intent"] == "postpone" and r["suggested_stage"] == "Postponed", r)
	check("WF-07: AI did not change the stage", frappe.db.get_value("Lead", la.name, "status") == "Quotation")
	frappe.set_user(REP)
	e = raises(sales.apply_suggested_stage, la.name)
	check("WF-07: applying Postponed still needs a Next Contact Date", e and "Next Contact Date" in str(e), e)
	sales.apply_suggested_stage(la.name, next_contact_date=add_days(nowdate(), 60))
	frappe.set_user("Administrator")
	check("WF-07: user confirmation applies the stage", frappe.db.get_value("Lead", la.name, "status") == "Postponed")
	res = sales.lead_brief(la.name)
	check("WF-07: lead brief with last interaction and open items", "Last interaction" in res["brief"] and "Open items" in res["brief"], res)
	frappe.get_doc({"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
		"sent_or_received": "Received", "subject": "استفسار", "content": "نرغب في تأجيل المشروع إلى الربع القادم",
		"reference_doctype": "Lead", "reference_name": la.name, "sender": "client@x.sa"}).insert(ignore_permissions=True)
	check("WF-07: follow-up language matches the lead (Arabic)", sales.lead_language(la.name) == "Arabic")
	nba = sales.next_best_action(la.name)
	check("WF-07 + C: next best action notifies, writes no ToDo", not frappe.db.exists("ToDo", {"reference_name": la.name,
		"description": ["like", "[AlphaX AI]%"]}) and logs(la.name, "WF-07 AI next best action"))

	# ------------------------------------------------------------------ C: business hours, outbox, log
	settings(business_days="Sunday\nMonday\nTuesday\nWednesday\nThursday", business_start="08:00:00", business_end="08:01:00")
	lq = new_lead("Interested")
	move(lq.name, "Qualified lead", "Quotation", as_user=REP)
	queued = logs(lq.name, "WF-02 No quotation (alert)")
	check("C: outside business hours the alert is queued", queued and queued[0].status == "Queued" and queued[0].send_after, queued)
	settings(business_days=always, business_start="00:00:00", business_end="23:59:00")
	frappe.db.set_value("AlphaX Automation Log", queued[0].name, "send_after", add_days(now_datetime(), -1))
	auto.flush_outbox()
	check("C: queued alert sent at the next business opening", frappe.db.get_value("AlphaX Automation Log", queued[0].name, "status") == "Sent")
	row = frappe.get_doc("AlphaX Automation Log", queued[0].name)
	check("C: log has rule, lead, recipients, time, result", all([row.rule, row.lead, row.recipients, row.sent_on, row.result]), row.as_dict())
	check("C: unique key = rule + lead + reference + trigger date", row.dedupe_key.startswith("WF-02 alert|" + lq.name + "|"), row.dedupe_key)

	# ------------------------------------------------------------------ C: replaced Frappe notifications
	ln = new_lead()
	check("C: new-lead alert goes through the business-hours notifier", len(logs(ln.name, "New lead")) == 1)
	frappe.db.set_value("Lead", ln.name, "alphax_next_contact_date", nowdate())
	wf.followup_due_daily()
	check("C: follow-up due reminder on the Next Contact Date", len(logs(ln.name, "Follow-up due")) == 1)
	check("C: old always-on email notifications switched off", not frappe.db.get_value("Notification", "AlphaX New Lead Alert", "enabled")
		and not frappe.db.get_value("Notification", "AlphaX Follow-up Due", "enabled"))
	check("install: notification setup no longer fails (reviewer role)", frappe.db.exists("Role", "AlphaX Lead Reviewer")
		and frappe.db.exists("Notification", "AlphaX Lead Pending Review"))

	# ------------------------------------------------------------------ health check
	from alphax_crm.crm import health

	hc = health.run_health_check()
	check("health check runs", hc["summary"]["ok"] > 20, hc["summary"])
	s = frappe.get_single("AlphaX CRM Settings")
	s.lead_stage_map[0].lead_status = "Wrong"
	s.save(ignore_permissions=True)
	hc = health.run_health_check()
	check("health check spots a mapping that differs from the spec", any(c["fix"] == "stage_map" for c in hc["checks"]))
	health.apply_fix("stage_map")
	check("health check fix restores the spec mapping", not any(c["fix"] == "stage_map" for c in health.run_health_check()["checks"]))
	if go_live:
		frappe.db.set_default(auto.GO_LIVE_KEY, go_live)
	frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")
