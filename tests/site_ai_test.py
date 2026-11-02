"""AlphaX CRM 0.40 AI integration tests against tests/mock_ai.py.
Copy into the app as alphax_crm/zz_ai_test.py and run: bench --site SITE execute alphax_crm.zz_ai_test.run"""

import glob
import json
import os

import frappe
from frappe.utils import add_days, nowdate

MOCK = "http://127.0.0.1:8090"
results = []


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


def requests_since(n):
	files = sorted(glob.glob("/srv/mock/ax/*.json"))
	return [json.load(open(f)) for f in files[n:]]


def mark():
	return len(glob.glob("/srv/mock/ax/*.json"))


def settings(**values):
	s = frappe.get_single("AlphaX CRM Settings")
	for k, v in values.items():
		s.set(k, v)
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")
	return s


def ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
	return email


def new_lead(**kw):
	if not frappe.db.exists("Lead Source", "Website"):
		frappe.get_doc({"doctype": "Lead Source", "source_name": "Website"}).insert(ignore_permissions=True)
	values = {"doctype": "Lead", "lead_name": "Sara Test " + frappe.generate_hash(length=4),
		"company_name": "Acme Retail", "email_id": f"sara.{frappe.generate_hash(length=5)}@acme.sa",
		"mobile_no": "+966551234567", "source": "Website", "website": "https://acme.example"}
	values.update(kw)
	doc = frappe.get_doc(values)
	doc.flags.alphax_skip_ai = True
	doc.insert(ignore_permissions=True)
	return doc


def run():
	frappe.set_user("Administrator")
	frappe.flags.in_test = True  # write failed/blocked AI logs inline (no worker in this test)
	for f in glob.glob("/srv/mock/ax/*.json"):
		os.remove(f)
	if frappe.db.exists("DocType", "NeotecAI Intake Settings"):
		frappe.db.set_single_value("NeotecAI Intake Settings", "spellcheck_enabled", 0)
	for key in frappe.cache.get_keys("alphax_"):
		frappe.cache.delete(key)

	# ---------------------------------------------------------------- upgrade from 0.39
	s = frappe.get_single("AlphaX CRM Settings")
	check("upgrade: provider detected from chat path", s.ai_provider == "Ollama", s.ai_provider)
	check("upgrade: governance defaults set", s.ai_mask_pii == 1 and s.ai_log_enabled == 1 and s.ai_log_retention_days == 90)
	check("upgrade: writing tools defaults", s.ai_writing_enabled == 1 and s.ai_spellcheck_mode == "Suggest"
		and "AlphaX Follow-up" in (s.ai_writing_doctypes or ""), s.ai_writing_doctypes)
	check("upgrade: Lead AI fields created", all(frappe.get_meta("Lead").has_field(f) for f in
		("alphax_ai_next_action", "alphax_ai_next_action_date", "alphax_ai_company_brief", "alphax_ai_last_run")))
	check("upgrade: new doctypes", all(frappe.db.exists("DocType", d) for d in ("AlphaX AI Log", "AlphaX AI Term", "AlphaX Email Draft")))

	settings(ai_enabled=1, ai_base_url=MOCK, ai_chat_path="/api/chat", ai_provider="Ollama", ai_model="llama3.1",
		ai_fast_model="qwen3.5-9b", ai_mask_pii=1, ai_log_enabled=1, ai_log_excerpts=1, ai_residency_mode=0,
		ai_daily_token_budget=0, ai_writing_enabled=1, ai_classify_leads=1, ai_draft_reply=1, ai_summarize_opportunity=1,
		ai_company_profile="We sell ZATCA-ready POS systems.", ai_next_action_todo=1, ai_followup_cadence="2,5,10")
	frappe.db.delete("AlphaX AI Log")
	frappe.db.delete("AlphaX AI Term")
	frappe.db.commit()

	from alphax_crm.ai import engine, sales, writing

	# ---------------------------------------------------------------- engine (Ollama)
	m = mark()
	out = engine.complete("You are a connection test.", "Reply OK. Contact ops@acme.sa or +966 55 123 4567",
		feature="t_ollama")
	req = requests_since(m)[0]
	check("Ollama: /api/chat used", req["path"] == "/api/chat")
	sent = req["req"]["messages"][1]["content"]
	check("PII masked before sending", "ops@acme.sa" not in sent and "[EMAIL_1]" in sent and "[PHONE_1]" in sent, sent)
	log = frappe.get_last_doc("AlphaX AI Log")
	check("AI log row: success + tokens + feature", log.status == "Success" and log.input_tokens == 100
		and log.output_tokens == 50 and log.feature == "t_ollama", log.as_dict())
	check("log excerpt stores masked text", "ops@acme.sa" not in (log.request_excerpt or ""))

	# ---------------------------------------------------------------- engine (OpenAI compatible)
	settings(ai_provider="OpenAI Compatible", ai_chat_path="/api/chat", ai_disable_thinking=1)
	check("OpenAI: chat URL derived", engine.chat_url() == MOCK + "/v1/chat/completions", engine.chat_url())
	m = mark()
	res = engine.complete_json("You are a careful spelling corrector", "Text to check:\n<<<\nteh\n>>>",
		schema=writing.SPELL_SCHEMA, feature="t_openai")
	req = requests_since(m)[0]
	check("OpenAI: json_schema + reasoning_effort sent", req["req"]["response_format"]["type"] == "json_schema"
		and req["req"].get("reasoning_effort") == "none", req["req"].get("response_format"))
	check("OpenAI: tokens logged", frappe.get_last_doc("AlphaX AI Log").input_tokens == 120)
	check("OpenAI: JSON parsed", res == {"changes": [{"original": "teh", "corrected": "the"}, {"original": "ghostword", "corrected": "ghost word"}]}, res)

	# ---------------------------------------------------------------- governance
	settings(ai_residency_mode=1, ai_allowed_hosts="")
	engine.complete("You are a connection test.", "hi", feature="t_private")  # 127.0.0.1 is private: allowed
	check("residency: private host allowed", frappe.get_last_doc("AlphaX AI Log").status == "Success")
	settings(ai_base_url="http://ai.example.com:8090")
	try:
		engine.complete("You are a connection test.", "hi", feature="t_blocked")
		check("residency: public host blocked", False)
	except engine.AIBlocked:
		check("residency: public host blocked", frappe.get_last_doc("AlphaX AI Log").status == "Blocked")
	settings(ai_allowed_hosts="*.example.com")
	try:
		engine._check_governance(frappe.get_single("AlphaX CRM Settings"))
		check("residency: allowed host passes", True)
	except engine.AIBlocked as e:
		check("residency: allowed host passes", False, e)
	settings(ai_base_url=MOCK, ai_residency_mode=0, ai_daily_token_budget=200)
	try:
		engine.complete("You are a connection test.", "hi", feature="t_budget")
		engine.complete("You are a connection test.", "hi", feature="t_budget")
		check("daily token budget enforced", False)
	except engine.AIBlocked as e:
		check("daily token budget enforced", "usage limit" in str(e), e)
	settings(ai_daily_token_budget=0)
	try:
		engine.complete("You are a connection test.", "FAIL500", feature="t_fail")
		check("server error -> AIError + Failed log", False)
	except engine.AIError:
		check("server error -> AIError + Failed log", frappe.get_last_doc("AlphaX AI Log").status == "Failed")
	settings(ai_enabled=0)
	try:
		engine.complete("x", "y")
		check("AI disabled blocks calls", False)
	except engine.AIBlocked:
		check("AI disabled blocks calls", True)
	settings(ai_enabled=1, ai_provider="Ollama", ai_chat_path="/api/chat")
	usage = engine.get_usage()
	check("usage today", usage["calls"] >= 5 and usage["failed"] >= 1 and usage["blocked"] >= 2, usage)

	# ---------------------------------------------------------------- existing AI features via the engine
	from alphax_crm.api import ai as legacy
	from alphax_crm.api import ai_query

	lead = new_lead(alphax_inbound_message="Need POS for 12 branches")
	legacy.process_lead(lead.name)
	lead.reload()
	check("lead classification still works", "Fit: High" in (lead.alphax_ai_brief or ""), lead.alphax_ai_brief)
	check("first reply draft still works", "Thank you" in (lead.alphax_ai_draft_reply or ""))
	check("legacy calls logged", frappe.db.exists("AlphaX AI Log", {"feature": "lead_classify", "reference_name": lead.name}))

	r = ai_query.ask("How many leads by source?", language=None)
	check("Ask AI (English): data query + answer", r.get("table") and r["language"] == "English"
		and r["answer"] == "There are leads by source.", r)
	r = ai_query.ask("كم عدد العملاء المحتملين حسب المصدر؟")
	check("Ask AI auto-detects Arabic question", r["language"] == "Arabic" and "حسب المصدر" in r["answer"], r)
	r = ai_query.ask("What is a lead?", language="Arabic")
	check("Ask AI answer forced to Arabic", r["language"] == "Arabic" and r["answer"].startswith("مرحبا"), r)

	# ---------------------------------------------------------------- writing tools
	writing.add_term("Neotek")
	m = mark()
	r = writing.spell_check("Please recieve teh maintainance order from Neotek, HP 26A, please deliver today ops@acme.sa")
	got = {c["original"]: c["corrected"] for c in r["changes"]}
	check("spell check (EN) safe fixes only", got == {"recieve": "receive", "teh": "the", "maintainance": "maintenance"}, got)
	check("spell check keeps email", r["corrected"].endswith("ops@acme.sa"), r["corrected"])
	req = requests_since(m)[0]
	check("spell check uses fast model", req["req"]["model"] == "qwen3.5-9b", req["req"]["model"])
	r = writing.spell_check("تم استلام اسعار الشركه من المورد المسؤل")
	check("spell check (AR)", r["corrected"] == "تم استلام أسعار الشركة من المورد المسؤل", r["corrected"])
	writing.add_term("maintainance")
	r = writing.spell_check("Our maintainance team will recieve it tomorrow")
	check("+ dictionary respected", {c["original"] for c in r["changes"]} == {"recieve"}, r["changes"])
	html = '<div class="ql-editor read-mode"><p>We recieve <a href="https://x.sa/recieve">teh link</a></p></div>'
	r = writing.spell_check(html, is_html=1)
	check("spell check HTML keeps tags/links", r["corrected"] == '<div class="ql-editor read-mode"><p>We receive <a href="https://x.sa/recieve">the link</a></p></div>', r["corrected"])

	frappe.get_doc({"doctype": "AlphaX AI Term", "term": "Quotation", "english": "Quotation", "arabic": "عرض سعر"}).insert()
	frappe.get_doc({"doctype": "AlphaX AI Term", "term": "AlphaX", "keep_as_is": 1}).insert()
	m = mark()
	text = "Please send the Quotation CRM-LEAD-2026-00042 from AlphaX to ops@acme.sa, total 500 SAR."
	r = writing.transform(text, "translate")
	req = requests_since(m)[0]
	sent = req["req"]["messages"][1]["content"]
	check("translate: auto target Arabic", r["target_language"] == "Arabic")
	check("translate: codes/terms/emails protected in prompt",
		all(v not in sent for v in ("CRM-LEAD-2026-00042", "AlphaX", "ops@acme.sa")) and "⟦" in sent, sent)
	check("translate: glossary sent", "Quotation => عرض سعر" in req["req"]["messages"][0]["content"])
	check("translate: values restored", r["result"].startswith("ترجمة: ") and "CRM-LEAD-2026-00042" in r["result"]
		and "AlphaX" in r["result"] and "ops@acme.sa" in r["result"] and not r["warnings"], r)
	r = writing.transform("مرحبا، نرسل لكم عرض السعر", "translate")
	check("translate: Arabic -> English auto", r["target_language"] == "English" and r["result"].startswith("Translation: "), r)
	r = writing.transform("DROPTOKEN send to ops@acme.sa", "translate", target_language="Arabic")
	check("translate: dropped value warns", any("missing" in w for w in r["warnings"]), r["warnings"])
	r = writing.transform("CHANGENUM total 500 SAR", "translate", target_language="Arabic")
	check("translate: changed number warns", any("numbers" in w for w in r["warnings"]), r["warnings"])
	r = writing.transform('<p>Hello <b>team</b></p><p>See ops@acme.sa</p>', "translate", target_language="Arabic", is_html=1)
	check("translate HTML keeps structure", r["result"] == "<p>ترجمة: Hello <b>ترجمة: team</b></p><p>ترجمة: See ops@acme.sa</p>", r["result"])
	for action, tag in (("improve", "Improved"), ("formal", "Formal"), ("shorten", "Short")):
		r = writing.transform("we will send it tmrw to ops@acme.sa", action)
		check(f"rewrite: {action}", r["result"] == f"{tag}: we will send it tmrw to ops@acme.sa", r)
	r = writing.transform("<p>we send it</p>", "improve", is_html=1)
	check("rewrite HTML returns paragraphs", r["result"] == "<p>Improved: we send it</p>", r["result"])
	boot = frappe._dict()
	writing.boot_session(boot)
	check("boot config", boot.alphax_ai == {"enabled": 1} and "Lead" in boot.alphax_ai_writing["doctypes"], boot)

	# ---------------------------------------------------------------- sales AI
	owner = ensure_user("sales.rep@test.local", ["Sales User"])
	lead = new_lead(lead_owner=owner)
	frappe.get_doc({"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
		"sent_or_received": "Received", "subject": "Pricing", "content": "Please share POS pricing",
		"reference_doctype": "Lead", "reference_name": lead.name, "sender": lead.email_id}).insert(ignore_permissions=True)
	res = sales.next_best_action(lead.name)
	lead.reload()
	check("next best action saved", lead.alphax_ai_next_action.startswith("[Call] Call Sara")
		and str(lead.alphax_ai_next_action_date) == add_days(nowdate(), 1), lead.alphax_ai_next_action)
	check("AlphaX lead score untouched", (lead.alphax_lead_score or 0) == (frappe.db.get_value("Lead", lead.name, "alphax_lead_score") or 0))
	todos = frappe.get_all("ToDo", filters={"reference_name": lead.name, "status": "Open", "description": ("like", "[AlphaX AI]%")},
		fields=["allocated_to"])
	check("ToDo for lead owner", len(todos) == 1 and todos[0].allocated_to == owner, todos)
	sales.next_best_action(lead.name)
	check("re-run replaces ToDo", frappe.db.count("ToDo", {"reference_name": lead.name, "status": "Open",
		"description": ("like", "[AlphaX AI]%")}) == 1)

	import alphax_crm.ai.sources as sources

	orig_fetch = sources.fetch_page_text
	sources.fetch_page_text = lambda url, max_chars=12000: "Acme Retail - 12 stores in Riyadh"
	try:
		r = sales.research_website(lead.name)
	finally:
		sources.fetch_page_text = orig_fetch
	check("website research brief", "12 retail stores" in r["brief"] and "Relevance" in r["brief"]
		and "Size" not in r["brief"], r)
	for bad in ("http://127.0.0.1:8000", "http://localhost/admin", "ftp://acme.sa"):
		try:
			sources._assert_public(bad)
			check(f"SSRF guard blocks {bad}", False)
		except frappe.ValidationError:
			check(f"SSRF guard blocks {bad}", True)

	names = sales.draft_followups(lead.name, steps=3, language="Arabic", instruction="mention the demo")
	drafts = [frappe.get_doc("AlphaX Email Draft", n) for n in names]
	check("3 follow-up drafts (not sent)", len(drafts) == 3 and all(d.status == "Draft" for d in drafts))
	check("drafts in Arabic, distinct steps", [d.subject for d in drafts] == ["Step 1 (Arabic)", "Step 2 (Arabic)", "Step 3 (Arabic)"],
		[d.subject for d in drafts])
	days = [(frappe.utils.get_datetime(d.send_after) - frappe.utils.now_datetime()).days for d in drafts]
	check("cadence 2,5,10 days", days == [1, 4, 9] or days == [2, 5, 10], days)
	if not frappe.db.exists("Email Account", "AX Test Outgoing"):
		frappe.get_doc({"doctype": "Email Account", "email_account_name": "AX Test Outgoing", "email_id": "crm@test.local",
			"enable_outgoing": 1, "default_outgoing": 1, "smtp_server": "localhost", "smtp_port": 25,
			"awaiting_password": 0, "no_smtp_authentication": 1, "enable_incoming": 0}).insert(ignore_permissions=True)
	drafts[0].approve()
	frappe.db.set_value("AlphaX Email Draft", drafts[0].name, "send_after", add_days(nowdate(), -1))
	sales.send_due_drafts()
	d0 = frappe.get_doc("AlphaX Email Draft", drafts[0].name)
	check("approved + due draft is sent", d0.status == "Sent" and d0.communication, (d0.status, d0.error))
	check("sent email is on the Lead timeline", frappe.db.get_value("Communication", d0.communication,
		["reference_doctype", "reference_name", "sent_or_received"]) == ("Lead", lead.name, "Sent"))
	check("email queued for delivery", frappe.db.exists("Email Queue", {"communication": d0.communication}))
	check("unapproved drafts not sent", frappe.db.get_value("AlphaX Email Draft", drafts[1].name, "status") == "Draft")
	frappe.get_doc({"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
		"sent_or_received": "Received", "subject": "Re: pricing", "content": "Thanks, let's talk",
		"reference_doctype": "Lead", "reference_name": lead.name, "sender": lead.email_id}).insert(ignore_permissions=True)
	check("lead reply cancels pending follow-ups", all(frappe.db.get_value("AlphaX Email Draft", d.name, "status") == "Cancelled"
		for d in drafts[1:]))

	# quotation watch
	settings(ai_quotation_watch=1, ai_quotation_reminder_days=3, ai_draft_quotation_reminders=1)
	company = frappe.db.get_value("Company", {}, "name")
	item = frappe.db.get_value("Item", {"is_sales_item": 1, "disabled": 0}, "name") or frappe.db.get_value("Item", {}, "name")
	q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Lead", "party_name": lead.name, "company": company,
		"transaction_date": nowdate(), "valid_till": add_days(nowdate(), 1), "contact_email": lead.email_id,
		"items": [{"item_code": item, "qty": 2, "rate": 500}]})
	q.insert(ignore_permissions=True)
	q.submit()
	sales.daily_quotation_watch()
	check("quotation watch ToDo", frappe.db.exists("ToDo", {"reference_type": "Quotation", "reference_name": q.name,
		"description": ("like", "[AlphaX AI]%")}))
	check("quotation reminder draft", frappe.db.exists("AlphaX Email Draft", {"reference_name": q.name, "purpose": "Quotation Reminder"}))
	sales.daily_quotation_watch()
	check("watch is idempotent", frappe.db.count("AlphaX Email Draft", {"reference_name": q.name}) == 1
		and frappe.db.count("ToDo", {"reference_name": q.name, "status": "Open"}) == 1)

	# permissions: a Sales User can use the tools on their own lead
	frappe.set_user(owner)
	try:
		r = writing.spell_check("Please recieve the goods")
		check("Sales User: writing tools", r["changes"] == [{"original": "recieve", "corrected": "receive"}])
		r = sales.api_next_action(lead.name)
		check("Sales User: next action on own lead", bool(r.get("alphax_ai_next_action")))
	finally:
		frappe.set_user("Administrator")
	engine.purge_old_logs()
	check("log purge keeps recent rows", frappe.db.count("AlphaX AI Log") > 0)
	frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")
