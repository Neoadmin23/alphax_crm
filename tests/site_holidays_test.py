"""Holiday lists (0.42.2/0.42.4) and browser-autofill detection (0.42.4).
Copy to alphax_crm/zz_holidays_test.py: bench --site SITE execute alphax_crm.zz_holidays_test.run"""
from datetime import date

import frappe
from frappe.utils import add_days, getdate, nowdate

results = []
SETTINGS_KEYS = ("holiday_list", "business_days", "whatsapp_phone_number_id", "na_api_url", "ai_cf_access_client_id")


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""), flush=True)


def _drop(name):
	if frappe.db.exists("Holiday List", name):
		frappe.db.set_value("Company", {"default_holiday_list": name}, "default_holiday_list", None)
		if frappe.db.get_single_value("AlphaX CRM Settings", "holiday_list") == name:
			frappe.db.set_single_value("AlphaX CRM Settings", "holiday_list", None)
		frappe.delete_doc("Holiday List", name, force=1, ignore_permissions=True)


def _list(name, start, end, public=()):
	_drop(name)
	skip = {getdate(day) for day, _ in public}
	doc = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name, "from_date": start, "to_date": end})
	d = getdate(start)
	while d <= getdate(end):
		if d.weekday() in (4, 5) and d not in skip:
			doc.append("holidays", {"holiday_date": d, "description": d.strftime("%A"), "weekly_off": 1})
		d = add_days(d, 1)
	for day, desc in public:
		doc.append("holidays", {"holiday_date": day, "description": desc, "weekly_off": 0})
	doc.insert(ignore_permissions=True)
	return name


def _settings(**values):
	for k, v in values.items():
		frappe.db.set_single_value("AlphaX CRM Settings", k, v)
	frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")
	return frappe.get_single("AlphaX CRM Settings")


def run():
	from alphax_crm.crm import automation, health, holidays

	frappe.set_user("Administrator")
	company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
	keep_company = frappe.db.get_value("Company", company, "default_holiday_list")
	s0 = frappe.get_single("AlphaX CRM Settings")
	keep = {k: s0.get(k) for k in SETTINGS_KEYS}
	keep_secret = {f: s0.get_password(f, raise_exception=False) for f in ("na_api_key", "ai_api_key")}
	today = getdate(nowdate())
	created = []
	try:
		_holiday_tests(automation, health, holidays, company, today, created)
		_autofill_tests(health)
	finally:
		frappe.db.set_value("Company", company, "default_holiday_list", keep_company)
		if keep["holiday_list"] and not frappe.db.exists("Holiday List", keep["holiday_list"]):
			keep["holiday_list"] = None
		s = _settings(**keep)
		s = frappe.get_single("AlphaX CRM Settings")
		for f, v in keep_secret.items():
			s.set(f, v)
		s.flags.ignore_mandatory = True
		s.save(ignore_permissions=True)
		for n in ["ZZ Weekends Only", "ZZ Full", "ZZ Ending", "ZZ Ended", *created]:
			_drop(n)
		frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")


def _holiday_tests(automation, health, holidays, company, today, created):
	for n in (str(today.year), str(today.year + 1)):  # test site only: start without year lists
		_drop(n)
	# estimated Eid dates are close to the real ones
	ph = dict(holidays.public_holidays(2026))
	check("2026: Founding Day, National Day and Eid al-Fitr (20 Mar) generated",
		date(2026, 2, 22) in ph and date(2026, 9, 23) in ph and date(2026, 3, 20) in ph and "estimated" in ph[date(2026, 3, 20)], ph)
	check("2026: 4 days of each Eid + 2 national days", len(ph) == 10, len(ph))

	s = _settings(holiday_list=None, business_days="Sunday\nMonday\nTuesday\nWednesday\nThursday")
	frappe.db.set_value("Company", company, "default_holiday_list", None)
	r = health._holidays(s)
	check("no list anywhere -> warn with a Fix button", r["status"] == "warn" and r.get("fix") == "holidays_next_year", r)

	# the user's case: weekly offs only, picked in AlphaX, ends within 60 days
	end = add_days(today, 60)  # the live site: 1 Nov -> list ends 31 Dec
	_list("ZZ Weekends Only", add_days(today, -300), end)
	s = _settings(holiday_list="ZZ Weekends Only")
	r = health._holidays(s)
	nxt = getdate(end).year + 1
	check("list ending soon with no public holidays -> warn, offers to create next year's",
		r["status"] == "warn" and r.get("fix") == "holidays_next_year" and str(nxt) in r["detail"]
		and "no public holidays left" in r["detail"], r)
	already = frappe.db.exists("Holiday List", str(nxt))
	health.apply_fix("holidays_next_year")
	if not already:
		created.append(str(nxt))
	doc = frappe.get_doc("Holiday List", str(nxt))
	pub = [h for h in doc.holidays if not h.weekly_off]
	check(f"Fix creates {nxt} with public holidays and weekly offs", len(pub) >= 8
		and any("Founding Day" in h.description for h in pub) and any("Eid al-Adha" in h.description for h in pub)
		and any(h.weekly_off for h in doc.holidays), [(h.holiday_date, h.description) for h in pub])
	check("weekly offs are the AlphaX non-working days only", all(getdate(h.holiday_date).weekday() not in
		automation.calendar(s).days for h in doc.holidays if h.weekly_off))
	s = frappe.get_single("AlphaX CRM Settings")
	check("the list in use is kept; the new one follows it", automation.holiday_lists(s) == ["ZZ Weekends Only", str(nxt)],
		automation.holiday_lists(s))
	check(f"calendar: Founding Day {nxt} is a non-working day", not automation.is_working_day(date(nxt, 2, 22),
		automation.calendar(s)))
	r = health._holidays(s)
	check("after the Fix: OK, shows both lists and the next public holiday", r["status"] == "ok"
		and "→" in r["detail"] and "Founding Day" in r["detail"], r)
	n = len(doc.holidays)
	holidays.create_holiday_list(nxt, s)
	check("running it again adds nothing twice", len(frappe.get_doc("Holiday List", str(nxt)).holidays) == n)

	# company fallback and other states
	full = _list("ZZ Full", add_days(today, -300), add_days(today, 200), [(add_days(today, 100), "Eid al-Fitr")])
	s = _settings(holiday_list=None)
	frappe.db.set_value("Company", company, "default_holiday_list", full)
	hl = automation.holiday_list(s)
	check("AlphaX field empty -> uses the Company's Default Holiday List", hl.name == full and company in hl.source, hl)
	r = health._holidays(s)
	check("list with public holidays -> OK", r["status"] == "ok" and "Eid al-Fitr" in r["detail"], r)
	for n in created:
		_drop(n)
	mid = _list("ZZ Mid", add_days(today, -100), add_days(today, 250))
	s = _settings(holiday_list=mid)
	r = health._holidays(s)
	check("weekly offs only, list runs on -> warn with 'add public holidays' Fix", r["status"] == "warn"
		and r.get("fix") == "holidays_add_public", r)
	health.apply_fix("holidays_add_public")
	pub = [h for h in frappe.get_doc("Holiday List", mid).holidays if not h.weekly_off]
	r = health._holidays(frappe.get_single("AlphaX CRM Settings"))
	check("after that Fix: public holidays added, check is OK", pub and r["status"] == "ok", (len(pub), r))
	_drop(mid)
	frappe.db.set_value("Company", company, "default_holiday_list", None)
	_drop("ZZ Full")
	_drop("ZZ Weekends Only")
	_list("ZZ Ended", add_days(today, -400), add_days(today, -5), [(add_days(today, -50), "Eid")])
	s = _settings(holiday_list="ZZ Ended")
	r = health._holidays(s)
	check("expired list with nothing after it -> warn with Fix", r["status"] == "warn" and "ended" in r["detail"]
		and r.get("fix") == "holidays_next_year", r)


def _autofill_tests(health):
	s = frappe.get_single("AlphaX CRM Settings")
	s.ai_base_url = s.ai_base_url or "http://127.0.0.1:8090"
	s.ai_api_key = "sk-test-shared-key"
	s.whatsapp_phone_number_id = s.ai_base_url  # what the browser did on the live site
	s.na_api_url = "erpsupport@example.com"
	s.na_api_key = "sk-test-shared-key"
	s.ai_cf_access_client_id = "erpsupport@example.com"
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	s = frappe.get_single("AlphaX CRM Settings")
	bad = {b["field"] for b in health._autofill_suspects(s)}
	check("autofill: e-mail / AI URL in ID fields and the AI key in another secret are flagged",
		bad == {"whatsapp_phone_number_id", "na_api_url", "na_api_key", "ai_cf_access_client_id"}, bad)
	rows = health._autofill(s)
	check("autofill: health row with a Fix button, secret not shown", rows and rows[0]["fix"] == "clear_autofill"
		and "sk-test" not in rows[0]["detail"], rows)
	health.apply_fix("clear_autofill")
	s = frappe.get_single("AlphaX CRM Settings")
	check("autofill Fix clears exactly those fields", not s.whatsapp_phone_number_id and not s.na_api_url
		and not s.ai_cf_access_client_id and not s.na_api_key and s.get_password("ai_api_key") == "sk-test-shared-key")
	s.whatsapp_phone_number_id = "109876543210"
	s.na_api_url = "https://apina.address.gov.sa/NationalAddress/v3.1"
	s.na_api_key = "a-different-key"
	s.ai_cf_access_client_id = "abc123.access"
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	check("autofill: real values are not flagged", not health._autofill_suspects(frappe.get_single("AlphaX CRM Settings")))
