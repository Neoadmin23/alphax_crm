"""AlphaX automation backbone (General Controls, section C of the approved spec).

* Business calendar: working days (default Sun-Thu), business hours (default 08:00-17:00),
  optional ERPNext Holiday List (Eid, National Day...), all in the site time zone
  (Asia/Riyadh). "Working hours" between two moments for WF-02's 24/72-hour rules.
* notify(): the one way every rule sends a message:
    - in-app Notification Log for each recipient, plus
    - an email through the ERPNext email account, logged on the Lead timeline
      (Communication type "Automated Message", so it never counts as sales activity),
    - outside business hours the message is queued and sent at the next business opening,
    - no duplicates: unique key = Rule + Lead + Reference + Trigger Date,
    - every action is written to AlphaX Automation Log (rule, lead, recipients, time, result).
* Activity detection for "no activity since" checks (WF-04/05): emails sent or received,
  comments, follow-up logs, meetings/events, CRM notes, closed ToDos and stage changes.
  AlphaX's own system messages are excluded.
* Lead <-> Quotation links in all three ways ERPNext stores them (direct, via the Customer
  created from the Lead, via the Lead's Opportunity).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime

from alphax_crm.crm.utils import get_settings, log_error

LOG_DT = "AlphaX Automation Log"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_DAYS = "Sunday\nMonday\nTuesday\nWednesday\nThursday"
# Only the exact openings AlphaX writes, so a client or company named "AlphaX..." still counts.
SYSTEM_PREFIXES = ("AlphaX:", "AlphaX [", "[AlphaX")
GO_LIVE_KEY = "alphax_workflow_go_live"
PAUSED_STATE = "Returned for Correction"


# ============================================================================ calendar
def _time(value, default):
	if not value:
		return default
	if isinstance(value, time):
		return value
	if isinstance(value, timedelta):
		return (datetime.min + value).time()
	try:
		parts = [int(p) for p in str(value).split(":")[:2]]
		return time(parts[0], parts[1] if len(parts) > 1 else 0)
	except Exception:
		return default


def calendar(settings=None):
	settings = settings or get_settings()
	days = [d.strip() for d in (settings.get("business_days") or DEFAULT_DAYS).replace(",", "\n").split("\n") if d.strip()]
	holidays = set()
	if settings.get("holiday_list"):
		holidays = {getdate(d) for d in frappe.get_all("Holiday", filters={"parent": settings.holiday_list}, pluck="holiday_date")}
	return frappe._dict(
		days={WEEKDAYS.index(d) for d in days if d in WEEKDAYS},
		start=_time(settings.get("business_start"), time(8, 0)),
		end=_time(settings.get("business_end"), time(17, 0)),
		holidays=holidays,
		mode=settings.get("working_hours_mode") or "Working days (24h per day)",
	)


def is_working_day(d, cal=None) -> bool:
	cal = cal or calendar()
	d = getdate(d)
	return d.weekday() in cal.days and d not in cal.holidays


def is_business_time(dt=None, cal=None) -> bool:
	cal = cal or calendar()
	dt = get_datetime(dt or now_datetime())
	return is_working_day(dt.date(), cal) and cal.start <= dt.time() < cal.end


def next_business_start(dt=None, cal=None) -> datetime:
	cal = cal or calendar()
	dt = get_datetime(dt or now_datetime())
	if is_business_time(dt, cal):
		return dt
	d = dt.date()
	if is_working_day(d, cal) and dt.time() < cal.start:
		return datetime.combine(d, cal.start)
	for _i in range(1, 60):
		d = d + timedelta(days=1)
		if is_working_day(d, cal):
			return datetime.combine(d, cal.start)
	return dt


def working_hours_between(start, end, cal=None) -> float:
	"""Hours between two moments counting only working time.
	Mode "Working days (24h per day)": every hour of a working day counts (24 working hours =
	one working day). Mode "Business hours only": only hours between business start and end."""
	cal = cal or calendar()
	start, end = get_datetime(start), get_datetime(end)
	if end <= start:
		return 0.0
	total = 0.0
	d = start.date()
	while d <= end.date() and (d - start.date()).days < 800:
		if is_working_day(d, cal):
			if cal.mode == "Business hours only":
				win_s, win_e = datetime.combine(d, cal.start), datetime.combine(d, cal.end)
			else:
				win_s, win_e = datetime.combine(d, time(0, 0)), datetime.combine(d + timedelta(days=1), time(0, 0))
			s, e = max(start, win_s), min(end, win_e)
			if e > s:
				total += (e - s).total_seconds() / 3600.0
		d += timedelta(days=1)
	return round(total, 2)


def working_days_between(start, end, cal=None) -> int:
	"""Whole working days from start date to end date (end excluded)."""
	cal = cal or calendar()
	s, e = getdate(start), getdate(end)
	n, d = 0, s
	while d < e and n < 800:
		if is_working_day(d, cal):
			n += 1
		d += timedelta(days=1)
	return n


# ============================================================================ recipients
def user_emails(users):
	users = [u for u in set(users or []) if u and u not in ("Guest", "Administrator")]
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, fields=["name", "email"])
	return {r.name: r.email for r in rows if r.email}


def lead_people(lead_name):
	"""Lead Owner plus users currently assigned to the Lead."""
	owner = frappe.db.get_value("Lead", lead_name, ["lead_owner", "owner"], as_dict=True) or {}
	people = {owner.get("lead_owner") or owner.get("owner")}
	people |= set(frappe.get_all("ToDo", filters={"reference_type": "Lead", "reference_name": lead_name,
		"status": "Open"}, pluck="allocated_to"))
	return [p for p in people if p]


def approvers(settings=None):
	from alphax_crm.crm.quotation import approver_users

	return approver_users(settings)


# ============================================================================ notify
def make_key(rule, lead=None, reference=None, trigger_date=None):
	ref = f"{reference[0]}:{reference[1]}" if reference else "-"
	return f"{rule}|{lead or '-'}|{ref}|{getdate(trigger_date) if trigger_date else getdate()}"


def already_done(key) -> bool:
	return bool(frappe.db.exists(LOG_DT, {"dedupe_key": key}))


def notify(rule, recipients, subject, message, lead=None, reference=None, trigger_date=None,
		email=True, timeline=True, respect_hours=True, key=None):
	"""Send (or queue) a rule notification once. Returns the AlphaX Automation Log name, or None
	if this exact notification (same key) was already handled."""
	settings = get_settings()
	key = key or make_key(rule, lead, reference, trigger_date)
	if already_done(key):
		return None
	users = sorted({u for u in recipients or [] if u and u not in ("Guest",)})
	log = frappe.get_doc({
		"doctype": LOG_DT, "rule": rule, "lead": lead, "dedupe_key": key,
		"reference_doctype": reference[0] if reference else None,
		"reference_name": reference[1] if reference else None,
		"trigger_date": getdate(trigger_date) if trigger_date else getdate(),
		"recipients": "\n".join(users), "subject": subject[:140], "message": message,
		"send_email": 1 if (email and cint(settings.get("notify_by_email", 1))) else 0,
		"log_on_timeline": 1 if timeline else 0, "status": "Queued",
	})
	if not users:
		# Logged, but the key is not consumed: the rule tries again on its next run (at most one
		# "Skipped" row per day) once a Lead Owner / Approver exists.
		skip_key = f"{key}|skipped|{getdate()}"[:140]
		if already_done(skip_key):
			return None
		log.dedupe_key = skip_key
		log.status = "Skipped"
		log.result = _("No recipients (check Lead Owner / Approver role users)")
		log.insert(ignore_permissions=True)
		return log.name
	cal = calendar(settings)
	if respect_hours and cint(settings.get("business_hours_only", 1)) and not is_business_time(None, cal):
		log.send_after = next_business_start(None, cal)
		log.result = _("Outside business hours: queued")
		log.insert(ignore_permissions=True)
		return log.name
	log.insert(ignore_permissions=True)
	deliver(log)
	return log.name


def deliver(log):
	"""Send one queued AlphaX Automation Log: in-app + email (timeline) + system comment."""
	if isinstance(log, str):
		log = frappe.get_doc(LOG_DT, log)
	users = [u for u in (log.recipients or "").split("\n") if u]
	ref_dt, ref_name = log.reference_doctype or ("Lead" if log.lead else None), log.reference_name or log.lead
	results = []
	for user in users:
		if user == "Administrator":
			continue
		try:
			frappe.get_doc({"doctype": "Notification Log", "subject": log.subject, "for_user": user, "type": "Alert",
				"email_content": frappe.utils.markdown(log.message or ""), "document_type": ref_dt,
				"document_name": ref_name, "from_user": "Administrator"}).insert(ignore_permissions=True)
		except Exception:
			log_error("automation in-app notification")
	results.append(_("in-app: {0}").format(len(users)))

	if log.send_email:
		emails = list(user_emails(users).values())
		if emails:
			try:
				comm = _send_email(log, emails)
				log.communication = comm
				results.append(_("email: {0}").format(len(emails)))
			except Exception as e:
				results.append(_("email failed: {0}").format(str(e)[:160]))
				log.status = "Partly Sent"
	if log.log_on_timeline and log.lead and frappe.db.exists("Lead", log.lead):
		system_comment("Lead", log.lead, f"AlphaX [{log.rule}]: {log.subject} → {', '.join(users)}")
	if log.status != "Partly Sent":
		log.status = "Sent"
	log.sent_on = now_datetime()
	log.result = "; ".join(results)
	log.save(ignore_permissions=True)


def _send_email(log, emails):
	content = frappe.utils.markdown(log.message or "")
	if log.lead and frappe.db.exists("Lead", log.lead) and log.log_on_timeline:
		comm = frappe.get_doc({
			"doctype": "Communication", "communication_type": "Automated Message", "communication_medium": "Email",
			"sent_or_received": "Sent", "subject": log.subject, "content": content,
			"recipients": ", ".join(emails), "reference_doctype": "Lead", "reference_name": log.lead,
			"timeline_links": ([{"link_doctype": log.reference_doctype, "link_name": log.reference_name}]
				if log.reference_doctype and log.reference_doctype != "Lead" and log.reference_name else []),
		}).insert(ignore_permissions=True)
		comm.send_email()
		return comm.name
	frappe.sendmail(recipients=emails, subject=log.subject, message=content,
		reference_doctype=log.reference_doctype, reference_name=log.reference_name, now=False)
	return None


def flush_outbox():
	"""Hourly: send notifications that were queued outside business hours."""
	if not frappe.db.table_exists(LOG_DT):
		return
	if not is_business_time():
		return
	for name in frappe.get_all(LOG_DT, filters={"status": "Queued", "send_after": ("<=", now_datetime())},
			pluck="name", order_by="send_after asc", limit=200):
		try:
			deliver(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			# retry up to 3 times, one hour apart, then mark Failed (visible in the health check)
			tries = cint(frappe.db.get_value(LOG_DT, name, "retries")) + 1 if frappe.get_meta(LOG_DT).has_field("retries") else 99
			values = {"result": str(frappe.get_traceback())[-500:]}
			if tries < 3:
				values.update(retries=tries, send_after=now_datetime() + timedelta(hours=1))
			else:
				values["status"] = "Failed"
			frappe.db.set_value(LOG_DT, name, values)
			frappe.db.commit()


def log_action(rule, lead=None, reference=None, result="", key=None, trigger_date=None):
	"""Record an automated action that is not a notification (e.g. stage auto-move)."""
	key = key or make_key(rule, lead, reference, trigger_date) + f"|{now_datetime().isoformat()}"
	frappe.get_doc({"doctype": LOG_DT, "rule": rule, "lead": lead, "dedupe_key": key[:140],
		"reference_doctype": reference[0] if reference else None, "reference_name": reference[1] if reference else None,
		"trigger_date": getdate(trigger_date) if trigger_date else getdate(), "status": "Done",
		"subject": result[:140], "result": result, "sent_on": now_datetime()}).insert(ignore_permissions=True)


def system_comment(doctype, name, text):
	"""Timeline note from the automation itself: type Info, never counted as sales activity."""
	try:
		frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": doctype,
			"reference_name": name, "content": frappe.utils.escape_html(text)}).insert(ignore_permissions=True)
	except Exception:
		log_error("system comment")


def is_system_text(text) -> bool:
	return frappe.utils.strip_html(text or "").strip().startswith(SYSTEM_PREFIXES)


# ============================================================================ activity
def is_paused(lead_name) -> bool:
	"""Reminders pause while the Lead is 'Returned for Correction' (approval workflow)."""
	meta = frappe.get_meta("Lead")
	for field in ("workflow_state", "alphax_review_status"):
		if meta.has_field(field) and frappe.db.get_value("Lead", lead_name, field) == PAUSED_STATE:
			return True
	return False


def activity_since(lead_name, since, extra_refs=(), ignore_stage_to=()) -> list[str]:
	"""Which qualifying activities happened on the Lead (and linked docs) after `since`.
	Returns a list of activity kinds found (empty = no activity)."""
	since = get_datetime(since)
	refs = [("Lead", lead_name)] + [r for r in extra_refs if r and r[1]]
	found = []
	for dt, dn in refs:
		comms = frappe.get_all("Communication", filters={"reference_doctype": dt, "reference_name": dn,
			"communication_type": "Communication", "creation": (">", since)}, fields=["sent_or_received"], limit=5)
		if comms:
			found.append("email")
		for c in frappe.get_all("Comment", filters={"reference_doctype": dt, "reference_name": dn,
				"comment_type": "Comment", "creation": (">", since)}, fields=["content"], limit=20):
			if not is_system_text(c.content):
				found.append("comment")
				break
		if frappe.db.count("ToDo", {"reference_type": dt, "reference_name": dn, "status": "Closed",
				"modified": (">", since)}):
			found.append("closed todo")
	if frappe.db.table_exists("AlphaX Follow-up") and frappe.db.count("AlphaX Follow-up", {
			"reference_doctype": "Lead", "reference_name": lead_name, "creation": (">", since),
			"summary": ("not like", "AlphaX:%")}):
		found.append("follow-up")
	events = frappe.db.sql("""select count(*) from `tabEvent Participants` ep join `tabEvent` e on e.name = ep.parent
		where ep.reference_doctype='Lead' and ep.reference_docname=%s and (e.creation > %s or e.starts_on > %s)""",
		(lead_name, since, since))[0][0]
	if events:
		found.append("meeting")
	if frappe.db.table_exists("CRM Note") and frappe.db.count("CRM Note", {"parenttype": "Lead", "parent": lead_name,
			"added_on": (">", since)}):
		found.append("note")
	stage_filters = {"reference_doctype": "Lead", "reference_name": lead_name, "field_label": "Lead Stage",
		"changed_on": (">", since)}
	if ignore_stage_to:
		stage_filters["to_value"] = ("not in", list(ignore_stage_to))
	if frappe.db.count("AlphaX Stage Transition Log", stage_filters):
		found.append("stage change")
	return sorted(set(found))


# ============================================================================ quotation links
def quotations_for_lead(lead_name, filters=None, fields=("name",)):
	"""Quotations linked to a Lead: directly, via the Customer created from it, or via its Opportunity."""
	filters = dict(filters or {})
	or_names = set(frappe.get_all("Quotation", filters={**filters, "quotation_to": "Lead", "party_name": lead_name}, pluck="name"))
	customers = frappe.get_all("Customer", filters={"lead_name": lead_name}, pluck="name")
	if customers:
		or_names |= set(frappe.get_all("Quotation", filters={**filters, "quotation_to": "Customer",
			"party_name": ["in", customers]}, pluck="name"))
	opps = frappe.get_all("Opportunity", filters={"opportunity_from": "Lead", "party_name": lead_name}, pluck="name")
	if customers:
		opps += frappe.get_all("Opportunity", filters={"opportunity_from": "Customer", "party_name": ["in", customers]}, pluck="name")
	if opps:
		or_names |= set(frappe.get_all("Quotation", filters={**filters, "opportunity": ["in", opps]}, pluck="name"))
	if not or_names:
		return []
	return frappe.get_all("Quotation", filters={"name": ["in", list(or_names)]}, fields=list(fields), order_by="creation desc")


def lead_for_quotation(q) -> str | None:
	"""The Lead behind a Quotation (direct, via Customer.lead_name, or via Opportunity)."""
	if isinstance(q, str):
		q = frappe.db.get_value("Quotation", q, ["quotation_to", "party_name", "opportunity"], as_dict=True)
	if not q:
		return None
	if q.get("quotation_to") == "Lead" and q.get("party_name"):
		return q.party_name
	if q.get("quotation_to") == "Customer" and q.get("party_name"):
		lead = frappe.db.get_value("Customer", q.party_name, "lead_name")
		if lead:
			return lead
	if q.get("opportunity"):
		opp = frappe.db.get_value("Opportunity", q.opportunity, ["opportunity_from", "party_name"], as_dict=True)
		if opp and opp.opportunity_from == "Lead":
			return opp.party_name
		if opp and opp.opportunity_from == "Customer":
			return frappe.db.get_value("Customer", opp.party_name, "lead_name")
	return None


def stage_entry_datetime(lead_name, stage):
	"""When the Lead most recently entered `stage`. Without a logged transition (leads that were
	already at the stage before AlphaX 0.41 was installed) the clock starts at the later of the
	Lead's creation and the go-live date, so the first 08:00 run does not fire every old milestone
	at once."""
	changed_on = frappe.db.get_value("AlphaX Stage Transition Log", {"reference_doctype": "Lead",
		"reference_name": lead_name, "field_label": "Lead Stage", "to_value": stage}, "changed_on", order_by="changed_on desc")
	if changed_on:
		return get_datetime(changed_on)
	created = get_datetime(frappe.db.get_value("Lead", lead_name, "creation"))
	go_live = frappe.db.get_default(GO_LIVE_KEY)
	return max(created, get_datetime(go_live)) if go_live else created


def last_logged_stage(lead_name):
	"""The Lead Stage AlphaX last recorded (used when ERPNext core rewrote the stage in SQL)."""
	return frappe.db.get_value("AlphaX Stage Transition Log", {"reference_doctype": "Lead",
		"reference_name": lead_name, "field_label": "Lead Stage"}, "to_value", order_by="changed_on desc")
