"""Emails & Notifications from the front end (0.43.0).
Copy to alphax_crm/zz_emails_test.py: bench --site SITE execute alphax_crm.zz_emails_test.run"""
import frappe
from frappe.utils import nowdate

results = []


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""), flush=True)


def _row(key):
	s = frappe.get_single("AlphaX CRM Settings")
	return s, next(r for r in s.email_rules if r.rule == key)


def _log(key):
	return frappe.get_doc("AlphaX Automation Log", {"dedupe_key": key})


def run():
	from alphax_crm.crm import automation as auto
	from alphax_crm.crm import emails

	frappe.set_user("Administrator")
	lead = frappe.get_all("Lead", pluck="name", order_by="creation desc", limit=1)[0]
	owner = frappe.db.get_value("Lead", lead, "lead_owner") or "Administrator"
	keep_bh = frappe.db.get_single_value("AlphaX CRM Settings", "business_hours_only")
	frappe.db.set_single_value("AlphaX CRM Settings", "business_hours_only", 0)
	tpl = emails.template_name("Follow-up due")
	keep_tpl = frappe.db.get_value("Email Template", tpl, ["subject", "response"], as_dict=True)
	keys = []
	try:
		emails.seed()
		s = frappe.get_single("AlphaX CRM Settings")
		have = {r.rule for r in s.email_rules}
		check("every notification has a settings row", have >= set(emails.RULE_MAP), set(emails.RULE_MAP) - have)
		check("every row links an existing Email Template", all(r.email_template and frappe.db.exists("Email Template",
			r.email_template) for r in s.email_rules))
		check("AI notifications default to in-app only", not _row("WF-07 AI intent detected")[1].send_email)

		# built-in wording renders like before
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		auto.notify("Follow-up due", [owner], lead=lead, key=key, context={"due": "05-11-2026"})
		log = _log(key)
		check("default template: subject and body rendered with the Lead", log.subject.startswith("Follow-up due for")
			and lead in log.message and "05-11-2026" in log.message and "/app/lead/" in log.message, (log.subject, log.message))

		# edit the wording in the front end -> used
		frappe.db.set_value("Email Template", tpl, {"subject": "متابعة {{ lead_name }} اليوم",
			"response": "<p>Call {{ lead.name }} on {{ due }}.</p>"})
		frappe.clear_document_cache("Email Template", tpl)
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		auto.notify("Follow-up due", [owner], lead=lead, key=key, context={"due": "06-11-2026"})
		log = _log(key)
		check("edited Email Template is used (Arabic subject too)", log.subject.startswith("متابعة")
			and f"Call {lead} on 06-11-2026" in log.message, (log.subject, log.message))

		# broken template -> built-in wording, error logged, still sent
		frappe.db.set_value("Email Template", tpl, "response", "<p>{{ lead.name </p>")
		frappe.clear_document_cache("Email Template", tpl)
		errors = frappe.db.count("Error Log")
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		auto.notify("Follow-up due", [owner], lead=lead, key=key, context={"due": "07-11-2026"})
		log = _log(key)
		check("broken template: falls back to the built-in wording and logs the error",
			"Next Contact Date" in log.message and frappe.db.count("Error Log") > errors and log.status != "Skipped", log.message)

		# in-app only
		s, row = _row("Follow-up due")
		row.send_email = 0
		s.flags.ignore_mandatory = True
		s.save()
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		auto.notify("Follow-up due", [owner], lead=lead, key=key, context={"due": "08-11-2026"})
		check("Email unticked: in-app only (no email)", not _log(key).send_email)

		# switched off
		s, row = _row("Follow-up due")
		row.enabled = 0
		s.save()
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		out = auto.notify("Follow-up due", [owner], lead=lead, key=key, context={"due": "09-11-2026"})
		log = _log(key)
		check("On unticked: not sent, logged as Skipped once", out is None and log.status == "Skipped"
			and "Turned off" in (log.result or ""), log.as_dict())
		check("…and not tried again", auto.notify("Follow-up due", [owner], lead=lead, key=key) is None)

		# migrate keeps admin edits
		frappe.db.set_value("Email Template", tpl, {"subject": "Kept {{ lead_name }}", "response": "<p>kept</p>"})
		emails.seed()
		s, row = _row("Follow-up due")
		check("migrate keeps edited wording and the On/Email choices", frappe.db.get_value("Email Template", tpl, "subject")
			== "Kept {{ lead_name }}" and not row.enabled and not row.send_email)

		# rules without a template (e.g. custom code) still work
		key = f"ZZ-emails|{frappe.generate_hash(length=6)}"; keys.append(key)
		auto.notify("ZZ custom rule", [owner], "Plain subject", "Plain body", lead=lead, key=key)
		check("notification without a template keeps its own text", _log(key).subject == "Plain subject")

		# every built-in template renders with sample data
		bad = []
		for rule in emails.RULES:
			try:
				out = emails.preview(rule["key"])
				if out.get("enabled") and not out.get("subject"):
					bad.append(rule["key"])
			except Exception as e:
				bad.append(f"{rule['key']}: {e}")
		check("Preview works for every notification", not bad, bad)
		s, row = _row("New lead")
		check("preview of New lead shows lead data", emails.preview("New lead")["subject"].startswith("New lead"))
	finally:
		frappe.db.set_value("Email Template", tpl, keep_tpl)
		s, row = _row("Follow-up due")
		row.enabled, row.send_email = 1, 1
		s.flags.ignore_mandatory = True
		s.save()
		frappe.db.set_single_value("AlphaX CRM Settings", "business_hours_only", keep_bh)
		frappe.db.delete("AlphaX Automation Log", {"dedupe_key": ("like", "ZZ-emails|%")})
		frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")
