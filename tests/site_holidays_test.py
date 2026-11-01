"""Holiday-list fallback + health check (0.42.2). Copy to alphax_crm/zz_holidays_test.py:
bench --site SITE execute alphax_crm.zz_holidays_test.run"""
import frappe
from frappe.utils import add_days, getdate, nowdate

results = []


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""), flush=True)


def _list(name, start, end, public=()):
	if frappe.db.exists("Holiday List", name):
		frappe.delete_doc("Holiday List", name, force=1, ignore_permissions=True)
	doc = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name, "from_date": start, "to_date": end})
	skip = {getdate(day) for day, _ in public}
	d = getdate(start)
	while d <= getdate(end):
		if d.weekday() in (4, 5) and d not in skip:
			doc.append("holidays", {"holiday_date": d, "description": d.strftime("%A"), "weekly_off": 1})
		d = add_days(d, 1)
	for day, desc in public:
		doc.append("holidays", {"holiday_date": day, "description": desc, "weekly_off": 0})
	doc.insert(ignore_permissions=True)
	return name


def run():
	from alphax_crm.crm import automation, health

	frappe.set_user("Administrator")
	company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
	keep_company = frappe.db.get_value("Company", company, "default_holiday_list")
	keep_settings = frappe.db.get_single_value("AlphaX CRM Settings", "holiday_list")
	today = getdate(nowdate())
	try:
		frappe.db.set_single_value("AlphaX CRM Settings", "holiday_list", None)
		frappe.db.set_value("Company", company, "default_holiday_list", None)
		frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")
		s = frappe.get_single("AlphaX CRM Settings")
		r = health._holidays(s)
		check("no list anywhere -> warn, says where to set it", r["status"] == "warn" and "Default Holiday List" in r["detail"], r)

		# the user's case: weekly offs only, set on the Company, AlphaX field empty
		weekend = _list("ZZ Weekends Only", add_days(today, -300), add_days(today, 200))
		frappe.db.set_value("Company", company, "default_holiday_list", weekend)
		hl = automation.holiday_list(s)
		check("AlphaX field empty -> uses the Company's Default Holiday List", hl.name == weekend and company in hl.source, hl)
		r = health._holidays(s)
		check("weekly offs only -> warn: add Eid / National Day", r["status"] == "warn" and "only weekly offs" in r["detail"], r)

		eid = add_days(today, 100)
		full = _list("ZZ Full", add_days(today, -300), add_days(today, 200), [(eid, "Eid al-Fitr")])
		frappe.db.set_value("Company", company, "default_holiday_list", full)
		r = health._holidays(s)
		check("list with public holidays -> OK, shows the next one", r["status"] == "ok" and "Eid al-Fitr" in r["detail"], r)
		check("calendar treats the Eid date as non-working", not automation.is_working_day(eid, automation.calendar(s)))

		ending = _list("ZZ Ending", add_days(today, -300), add_days(today, 30), [(add_days(today, 10), "National Day")])
		s.holiday_list = ending
		r = health._holidays(s)
		check("AlphaX field wins over the Company list", automation.holiday_list(s).name == ending)
		check("list ending within 60 days -> warn: create next year's", r["status"] == "warn" and "next year" in r["detail"], r)
		ended = _list("ZZ Ended", add_days(today, -400), add_days(today, -5), [(add_days(today, -50), "Eid")])
		s.holiday_list = ended
		r = health._holidays(s)
		check("expired list -> warn", r["status"] == "warn" and "ended" in r["detail"], r)
	finally:
		frappe.db.set_value("Company", company, "default_holiday_list", keep_company)
		frappe.db.set_single_value("AlphaX CRM Settings", "holiday_list", keep_settings)
		for n in ("ZZ Weekends Only", "ZZ Full", "ZZ Ending", "ZZ Ended"):
			if frappe.db.exists("Holiday List", n):
				frappe.delete_doc("Holiday List", n, force=1, ignore_permissions=True)
		frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")
