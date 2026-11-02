"""Saudi public holidays for AlphaX's business calendar.

Creates next year's ERPNext Holiday List with the weekly offs (the days that are not AlphaX working days)
and the KSA public holidays: Founding Day (22 Feb), Eid al-Fitr, Eid al-Adha and National Day (23 Sep).

The Eid dates depend on the moon sighting, so they are *estimated* with the arithmetic Hijri calendar
(usually within a day of the Umm al-Qura date) and labelled "(estimated, confirm)" so HR corrects them
when the official holiday announcement comes out.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from alphax_crm.crm import automation
from alphax_crm.crm.utils import get_settings

ESTIMATED = " (estimated, confirm)"
# private-sector holidays (Ministry of Human Resources): 4 days each Eid
EID_FITR = (10, 1, 4, "Eid al-Fitr")     # 1-4 Shawwal
EID_ADHA = (12, 9, 4, "Eid al-Adha")     # 9 (Arafah) - 12 Dhu al-Hijjah


def _hijri_to_gregorian(y: int, m: int, d: int) -> date:
	"""Arithmetic (tabular) Islamic calendar -> Gregorian date."""
	jd = d + math.ceil(29.5 * (m - 1)) + (y - 1) * 354 + math.floor((3 + 11 * y) / 30) + 1948439.5 - 1
	return date.fromordinal(int(jd + 0.5) - 1721425)


def public_holidays(year: int) -> list[tuple[date, str]]:
	"""KSA public holidays falling in a Gregorian year (Eid dates estimated)."""
	out = [(date(year, 2, 22), _("Founding Day")), (date(year, 9, 23), _("Saudi National Day"))]
	approx_hijri = int((year - 622) * 33 / 32)
	for hy in range(approx_hijri - 1, approx_hijri + 3):
		for month, first_day, days, label in (EID_FITR, EID_ADHA):
			start = _hijri_to_gregorian(hy, month, first_day)
			for i in range(days):
				d = start + timedelta(days=i)
				if d.year == year:
					out.append((d, _(label) + (f" {i + 1}" if days > 1 else "") + ESTIMATED))
	return sorted(set(out))


def add_public_holidays(name: str) -> int:
	"""Add the missing KSA public holidays to an existing Holiday List (any name). Returns how many were added;
	a weekly-off row on the same date is relabelled as the public holiday."""
	doc = frappe.get_doc("Holiday List", name)
	start, end = getdate(doc.from_date), getdate(doc.to_date)
	rows = {getdate(h.holiday_date): h for h in doc.holidays}
	added = 0
	for year in range(start.year, end.year + 1):
		for d, label in public_holidays(year):
			if not start <= d <= end:
				continue
			if d in rows:
				if rows[d].weekly_off:
					rows[d].weekly_off, rows[d].description = 0, label
					added += 1
				continue
			doc.append("holidays", {"holiday_date": d, "description": label, "weekly_off": 0})
			added += 1
	if added:
		doc.flags.ignore_permissions = True
		doc.save()
	return added


def create_holiday_list(year: int, settings=None) -> str:
	"""Create (or complete) the Holiday List named after `year`. Existing rows are kept; missing weekly
	offs and public holidays are added. Returns the list name."""
	settings = settings or get_settings()
	name = str(year)
	working = automation.calendar(settings).days
	off_days = [d for d in range(7) if d not in working]
	if frappe.db.exists("Holiday List", name):
		doc = frappe.get_doc("Holiday List", name)
	else:
		doc = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name, "from_date": date(year, 1, 1),
			"to_date": date(year, 12, 31)})
	have = {getdate(h.holiday_date) for h in doc.holidays}
	public = dict(public_holidays(year))
	d = date(year, 1, 1)
	while d.year == year:
		if d not in have:
			if d in public:
				doc.append("holidays", {"holiday_date": d, "description": public[d], "weekly_off": 0})
			elif d.weekday() in off_days:
				doc.append("holidays", {"holiday_date": d, "description": automation.WEEKDAYS[d.weekday()], "weekly_off": 1})
		d += timedelta(days=1)
	doc.flags.ignore_permissions = True
	doc.save() if not doc.is_new() else doc.insert()
	return name


def next_year_needed(settings=None):
	"""The year whose list should be created next: the year after the list in use, if it ends within
	90 days and nothing follows it."""
	hl = automation.holiday_list(settings)
	if not hl.name:
		return getdate(nowdate()).year
	to_date = frappe.db.get_value("Holiday List", hl.name, "to_date")
	if not to_date or automation.following_list(hl.name):
		return None
	return getdate(to_date).year + 1 if (getdate(to_date) - getdate(nowdate())).days <= 90 else None
