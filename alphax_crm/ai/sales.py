"""AlphaX Sales AI: next best action, website research, follow-up email sequences
(human-approved) and the quotation expiry watch.

The AI never overwrites AlphaX's own rule-based Lead Score or the salesperson's own
Next Contact Date: its output lives in separate "AI" fields and in ToDos tagged [AlphaX AI].
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_to_date,
	cint,
	date_diff,
	get_datetime,
	now_datetime,
	nowdate,
	strip_html,
)

from alphax_crm.ai import pure
from alphax_crm.ai.engine import AIError, complete_json, is_enabled, language_instruction
from alphax_crm.crm.utils import get_settings

TODO_TAG = "[AlphaX AI]"
DRAFT_DT = "AlphaX Email Draft"
LEAD_FIELDS = (
	"lead_name", "company_name", "job_title", "website", "industry", "market_segment", "territory",
	"source", "status", "custom_lead_status", "qualification_status", "city", "country",
	"no_of_employees", "annual_revenue", "alphax_lead_score", "alphax_score_breakdown",
	"alphax_next_contact_date", "alphax_idle_days", "alphax_inbound_message", "alphax_ai_brief",
	"alphax_ai_company_brief",
)
CLOSED_LEAD_STATUSES = ("Converted", "Do Not Contact", "Lost Quotation")


def _base_system(settings, language=None):
	return (
		"You are the sales assistant of the company described below.\n"
		f"Company profile: {settings.get('ai_company_profile') or 'A B2B solutions provider in Saudi Arabia / GCC.'}\n"
		f"Brand voice: {settings.get('ai_brand_voice') or 'Professional, concise, helpful.'}\n"
		"Never invent facts, prices, discounts, client names or certifications that are not in the input.\n"
		+ language_instruction(language)
	).strip()


# ============================================================================== language
def lead_language(lead_name) -> str:
	"""Arabic or English, matching the lead: its language setting, else its own inbound messages."""
	if not lead_name:
		return get_settings().get("ai_email_language") or "English"
	lang = (frappe.db.get_value("Lead", lead_name, "language") or "").lower()
	if lang.startswith("ar"):
		return "Arabic"
	# the client's most recent message decides; then the inbound message captured at intake
	latest = frappe.get_all("Communication", filters={"reference_doctype": "Lead", "reference_name": lead_name,
		"sent_or_received": "Received", "communication_type": "Communication"}, fields=["content"],
		order_by="creation desc", limit=1)
	for text in ([strip_html(latest[0].content or "")] if latest else []) + [frappe.db.get_value("Lead", lead_name, "alphax_inbound_message") or ""]:
		if text.strip():
			return pure.detect_language(text)
	return get_settings().get("ai_email_language") or "English"


# ============================================================================== context
def lead_context(lead) -> dict:
	meta = frappe.get_meta("Lead")
	data = {}
	for f in LEAD_FIELDS:
		if (meta.has_field(f) or f in ("lead_name", "status")) and lead.get(f) not in (None, "", 0):
			data[f] = pure.truncate(strip_html(str(lead.get(f))), 400)
	activity = _activity("Lead", lead.name)
	quotations = frappe.get_all("Quotation",
		filters={"quotation_to": "Lead", "party_name": lead.name, "docstatus": 1},
		fields=["name", "status", "grand_total", "currency", "valid_till"], order_by="creation desc", limit=5)
	last = activity[0]["date"] if activity else None
	return {
		"lead": data,
		"activity": activity,
		"quotations": [dict(q) for q in quotations],
		"days_since_activity": date_diff(nowdate(), last) if last else None,
	}


def _activity(ref_dt, ref_name, limit=12):
	out = []
	for c in frappe.get_all("Communication",
			filters={"reference_doctype": ref_dt, "reference_name": ref_name, "communication_type": "Communication"},
			fields=["communication_date", "sent_or_received", "subject", "content", "communication_medium"],
			order_by="communication_date desc", limit=limit):
		out.append({"date": str(get_datetime(c.communication_date).date()), "direction": c.sent_or_received or "Sent",
			"subject": pure.truncate(c.subject or c.communication_medium or "", 80),
			"excerpt": pure.truncate(strip_html(c.content or "").strip().replace("\n", " "), 220)})
	if frappe.db.table_exists("AlphaX Follow-up"):
		for f in frappe.get_all("AlphaX Follow-up", filters={"reference_doctype": ref_dt, "reference_name": ref_name},
				fields=["follow_up_datetime", "channel", "outcome", "summary"], order_by="follow_up_datetime desc", limit=5):
			out.append({"date": str(get_datetime(f.follow_up_datetime).date()), "direction": f"Follow-up ({f.channel})",
				"subject": f.outcome or "", "excerpt": pure.truncate(f.summary or "", 220)})
	for n in frappe.get_all("Comment",
			filters={"reference_doctype": ref_dt, "reference_name": ref_name, "comment_type": "Comment"},
			fields=["creation", "content"], order_by="creation desc", limit=5):
		out.append({"date": str(get_datetime(n.creation).date()), "direction": "Note", "subject": "Internal note",
			"excerpt": pure.truncate(strip_html(n.content or "").strip(), 220)})
	out.sort(key=lambda a: a["date"], reverse=True)
	return out[:limit]


def _context_text(ctx) -> str:
	lines = ["LEAD"] + [f"- {k}: {v}" for k, v in ctx["lead"].items()]
	lines.append(f"- days_since_last_activity: {ctx['days_since_activity'] if ctx['days_since_activity'] is not None else 'no activity'}")
	lines.append("RECENT ACTIVITY (newest first)")
	lines += [f"- {a['date']} [{a['direction']}] {a['subject']}: {a['excerpt']}" for a in ctx["activity"]] or ["- none recorded"]
	lines.append("QUOTATIONS")
	lines += [f"- {q['name']} {q['status']} {q['grand_total']} {q['currency']} valid till {q['valid_till']}"
		for q in ctx["quotations"]] or ["- none"]
	return "\n".join(lines)


# ============================================================================== next best action
NBA_SCHEMA = {
	"type": "object",
	"properties": {
		"summary": {"type": "string"},
		"next_action": {"type": "string"},
		"channel": {"type": "string", "enum": ["Call", "Email", "WhatsApp", "Meeting", "Visit", "Other"]},
		"in_days": {"type": "integer"},
		"reasons": {"type": "array", "items": {"type": "string"}},
	},
	"required": ["summary", "next_action", "channel", "in_days", "reasons"],
}


def next_best_action(lead_name: str, language=None) -> dict:
	settings = get_settings()
	lead = frappe.get_doc("Lead", lead_name)
	ctx = lead_context(lead)
	system = _base_system(settings, language) + (
		"\nYou coach a B2B salesperson. Given the lead and its history, recommend the single most useful next step."
		" Be concrete (who to contact, how, and what to say or send). Be strict: a lead with no engagement is not hot."
		" in_days = when to do it (0-30). reasons = up to 3 short reasons.")
	result = complete_json(system, f"Today is {nowdate()}.\n\n" + _context_text(ctx), schema=NBA_SCHEMA,
		feature="lead_next_action", reference=("Lead", lead.name), max_tokens=700)
	in_days = pure.clamp(result.get("in_days", 2), 0, 30)
	action = pure.truncate(str(result.get("next_action") or "").strip(), 300)
	channel = str(result.get("channel") or "").strip()
	reasons = [str(r) for r in (result.get("reasons") or [])][:3]
	text = (f"[{channel}] " if channel else "") + action
	values = {
		"alphax_ai_next_action": text + ("\n" + "\n".join(f"• {r}" for r in reasons) if reasons else ""),
		"alphax_ai_next_action_date": add_days(nowdate(), in_days),
		"alphax_ai_last_run": now_datetime(),
	}
	summary = pure.truncate(str(result.get("summary") or "").strip(), 600)
	if summary:
		values["alphax_ai_brief"] = summary
	frappe.db.set_value("Lead", lead.name, values, update_modified=False)
	owner = lead.get("lead_owner") or lead.owner
	if action and cint(settings.get("ai_next_action_todo")):
		_refresh_todo("Lead", lead.name, owner, text, values["alphax_ai_next_action_date"])
	elif action:
		# spec C: the AI only writes AI fields, timeline notes and notifications
		from alphax_crm.crm.automation import notify

		notify("WF-07 AI next best action", [owner], _("AI next best action for {0}").format(lead.name),
			text, lead=lead.name, email=False, respect_hours=False,
			key=f"WF-07 nba|{lead.name}|{now_datetime().isoformat()}")
	return {**values, "summary": summary}


def _refresh_todo(ref_dt, ref_name, owner, action, due, priority="Medium"):
	if not owner or owner in ("Administrator", "Guest"):
		return
	for name in frappe.get_all("ToDo", filters={"reference_type": ref_dt, "reference_name": ref_name, "status": "Open",
			"description": ("like", f"{TODO_TAG}%")}, pluck="name"):
		frappe.db.set_value("ToDo", name, "status", "Cancelled", update_modified=False)
	frappe.get_doc({"doctype": "ToDo", "allocated_to": owner, "reference_type": ref_dt, "reference_name": ref_name,
		"description": f"{TODO_TAG} {action}", "date": due, "priority": priority,
		"assigned_by": "Administrator"}).insert(ignore_permissions=True)


def enqueue_next_action(lead_name):
	frappe.enqueue("alphax_crm.ai.sales.next_action_job", queue="long", lead_name=lead_name,
		job_id=f"alphax_ai_nba::{frappe.local.site}::{lead_name}", deduplicate=True, enqueue_after_commit=True)


def next_action_job(lead_name):
	try:
		next_best_action(lead_name)
		frappe.db.commit()
	except AIError as e:
		frappe.logger("alphax_crm").info(f"next action skipped for {lead_name}: {e}")
	except Exception:
		frappe.log_error(title=f"AlphaX AI: next action failed for {lead_name}", message=frappe.get_traceback())


def daily_next_action_sweep():
	"""Refresh the AI next action on open leads that have not been looked at for a while."""
	settings = get_settings()
	if not (is_enabled() and cint(settings.get("ai_next_action_daily"))):
		return
	cutoff = add_days(nowdate(), -(cint(settings.get("stale_lead_days")) or 5))
	leads = frappe.get_all("Lead", filters={"status": ("not in", CLOSED_LEAD_STATUSES)},
		fields=["name", "alphax_ai_last_run"], order_by="modified desc", limit=500)
	due = [lead.name for lead in leads if not lead.alphax_ai_last_run or str(lead.alphax_ai_last_run) < str(cutoff)]
	for name in due[: cint(settings.get("ai_daily_batch")) or 100]:
		enqueue_next_action(name)


# ============================================================================== website research
BRIEF_SCHEMA = {
	"type": "object",
	"properties": {"brief": {"type": "string"}, "industry": {"type": "string"}, "size_hint": {"type": "string"},
		"relevance": {"type": "string"}},
	"required": ["brief", "industry", "size_hint", "relevance"],
}


def research_website(lead_name: str, language=None) -> dict:
	from alphax_crm.ai.sources import fetch_page_text

	settings = get_settings()
	lead = frappe.get_doc("Lead", lead_name)
	if not lead.get("website"):
		frappe.throw(_("Add the lead's website first."))
	page = fetch_page_text(lead.website)
	system = _base_system(settings, language) + (
		"\nYou research prospect companies from the text of their own website only. brief = 3-4 sentences on what"
		" they do and who they serve. relevance = one sentence on why they could need our offering, or 'unclear'."
		" Use 'unknown' when the page does not say.")
	result = complete_json(system, f"Website: {lead.website}\n\nPAGE TEXT\n{page}", schema=BRIEF_SCHEMA,
		feature="lead_website_research", reference=("Lead", lead.name), max_tokens=600)
	parts = [str(result.get("brief") or "").strip()]
	for label, key in ((_("Industry"), "industry"), (_("Size"), "size_hint"), (_("Relevance"), "relevance")):
		val = str(result.get(key) or "").strip()
		if val and val.lower() != "unknown":
			parts.append(f"{label}: {val}")
	brief = "\n".join(p for p in parts if p)
	frappe.db.set_value("Lead", lead.name, "alphax_ai_company_brief", brief, update_modified=False)
	return {"brief": brief}


# ============================================================================== follow-up sequences
EMAIL_SCHEMA = {
	"type": "object",
	"properties": {"subject": {"type": "string"}, "body_html": {"type": "string"}},
	"required": ["subject", "body_html"],
}


def draft_followups(lead_name, steps=None, purpose="Follow-up", instruction="", language=None) -> list[str]:
	"""Create a sequence of email drafts. Nothing is sent until a person approves each one."""
	settings = get_settings()
	lead = frappe.get_doc("Lead", lead_name)
	if not lead.get("email_id"):
		frappe.throw(_("Lead {0} has no email address.").format(lead.name))
	cadence = pure.parse_cadence(settings.get("ai_followup_cadence"))
	if steps:
		cadence = cadence[: max(1, min(int(steps), len(cadence)))]
	language = language or lead_language(lead.name)
	ctx_text = _context_text(lead_context(lead))
	created, subjects = [], []
	for step, offset in enumerate(cadence, start=1):
		system = _base_system(settings, language) + (
			f"\nWrite email {step} of {len(cadence)} in a {purpose.lower()} sequence to this lead."
			" Keep it under 150 words, specific to their situation, with one clear call to action."
			" Each email must take a different angle from the previous ones. body_html uses simple <p> tags,"
			" no signature (it is added automatically)."
			+ (f"\nPrevious subjects: {'; '.join(subjects)}" if subjects else "")
			+ (f"\nExtra instruction from the salesperson: {instruction}" if instruction else ""))
		result = complete_json(system, ctx_text, schema=EMAIL_SCHEMA, feature="lead_followup_email",
			reference=("Lead", lead.name), max_tokens=900, temperature=0.4)
		subject = pure.truncate(str(result.get("subject") or _("Following up")), 140)
		subjects.append(subject)
		body = str(result.get("body_html") or "").strip()
		if settings.get("ai_email_signature"):
			body += f"<br>{settings.ai_email_signature}"
		created.append(frappe.get_doc({
			"doctype": DRAFT_DT, "purpose": purpose, "sequence_no": step, "language": language,
			"reference_doctype": "Lead", "reference_name": lead.name, "recipient": lead.email_id,
			"subject": subject, "body": body, "generated_by_ai": 1,
			"send_after": add_to_date(now_datetime(), days=offset, as_datetime=True),
		}).insert().name)
	return created


def cancel_pending_sequence(ref_dt, ref_name, reason):
	if not frappe.db.table_exists(DRAFT_DT):
		return 0
	names = frappe.get_all(DRAFT_DT, filters={"reference_doctype": ref_dt, "reference_name": ref_name,
		"status": ("in", ("Draft", "Approved")), "purpose": ("in", ("Follow-up", "Re-engagement"))}, pluck="name")
	for name in names:
		frappe.db.set_value(DRAFT_DT, name, {"status": "Cancelled", "error": reason})
	return len(names)


def on_communication(doc, method=None):
	"""A reply from the lead stops its pending follow-up emails (and optionally refreshes the next action)."""
	if doc.reference_doctype != "Lead" or not doc.reference_name or doc.communication_type != "Communication":
		return
	if doc.sent_or_received != "Received" or not frappe.db.exists("Lead", doc.reference_name):
		return
	settings = get_settings()
	if cint(settings.get("ai_stop_sequence_on_reply", 1)):
		cancel_pending_sequence("Lead", doc.reference_name, _("Cancelled automatically: the lead replied."))
	if is_enabled() and cint(settings.get("ai_next_action_on_reply")):
		enqueue_next_action(doc.reference_name)


def send_draft(name):
	draft = frappe.get_doc(DRAFT_DT, name)
	if draft.status != "Approved":
		frappe.throw(_("Only approved drafts can be sent."))
	try:
		from frappe.core.doctype.communication.email import make

		result = make(doctype=draft.reference_doctype, name=draft.reference_name, content=draft.body,
			subject=draft.subject, recipients=draft.recipient, cc=draft.cc or None,
			communication_medium="Email", sent_or_received="Sent", send_email=True)
		comm = result.get("name") if isinstance(result, dict) else None
		draft.db_set({"status": "Sent", "sent_on": now_datetime(), "communication": comm, "error": None})
	except Exception as e:
		draft.db_set({"status": "Failed", "error": str(e)[:500]})
		frappe.log_error(title=f"AlphaX AI: email draft {name} failed", message=frappe.get_traceback())


def send_due_drafts():
	"""Every 10 minutes: send approved drafts whose time has come."""
	if not frappe.db.table_exists(DRAFT_DT):
		return
	for name in frappe.get_all(DRAFT_DT, filters={"status": "Approved", "send_after": ("<=", now_datetime())},
			pluck="name", order_by="send_after asc", limit=50):
		send_draft(name)
		frappe.db.commit()


# ============================================================================== quotation watch
OPEN_QUOTATION = ("Open", "Replied")


def expiring_quotations(days=None, limit=200):
	days = cint(days if days is not None else get_settings().get("ai_quotation_reminder_days")) or 3
	return frappe.get_all("Quotation",
		filters={"docstatus": 1, "status": ("in", OPEN_QUOTATION), "valid_till": ("between", (nowdate(), add_days(nowdate(), days)))},
		fields=["name", "quotation_to", "party_name", "customer_name", "grand_total", "currency", "valid_till",
			"contact_email", "owner"], order_by="valid_till asc", limit=limit)


def daily_quotation_watch():
	settings = get_settings()
	if not cint(settings.get("ai_quotation_watch")):
		return
	for q in expiring_quotations():
		days_left = date_diff(q.valid_till, nowdate())
		if not frappe.db.exists("ToDo", {"reference_type": "Quotation", "reference_name": q.name, "status": "Open",
				"description": ("like", f"{TODO_TAG}%")}):
			frappe.get_doc({"doctype": "ToDo", "allocated_to": q.owner, "reference_type": "Quotation",
				"reference_name": q.name, "date": q.valid_till, "priority": "High" if days_left <= 1 else "Medium",
				"assigned_by": "Administrator",
				"description": f"{TODO_TAG} " + _("Quotation {0} for {1} expires on {2} ({3} day(s) left). "
					"Confirm the decision or extend validity.").format(q.name, q.customer_name or q.party_name,
					q.valid_till, days_left)}).insert(ignore_permissions=True)
		if cint(settings.get("ai_draft_quotation_reminders")) and is_enabled() and q.contact_email:
			if frappe.db.exists(DRAFT_DT, {"reference_doctype": "Quotation", "reference_name": q.name,
					"purpose": "Quotation Reminder"}):
				continue
			try:
				draft_quotation_reminder(q.name)
				frappe.db.commit()
			except AIError as e:
				frappe.logger("alphax_crm").info(f"quotation reminder for {q.name} skipped: {e}")
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"AlphaX AI: quotation reminder failed for {q.name}", message=frappe.get_traceback())


def draft_quotation_reminder(quotation, language=None) -> str:
	settings = get_settings()
	doc = frappe.get_doc("Quotation", quotation)
	if not doc.contact_email:
		frappe.throw(_("Quotation {0} has no contact email.").format(doc.name))
	if not language:
		from alphax_crm.crm.automation import lead_for_quotation

		language = lead_language(lead_for_quotation(doc))
	items = "\n".join(f"- {i.item_name} x {i.get_formatted('qty')}" for i in doc.items[:8])
	user = (f"Quotation {doc.name} for {doc.customer_name or doc.party_name}\nTotal: {doc.get_formatted('grand_total')}\n"
		f"Valid till: {doc.get_formatted('valid_till')} ({date_diff(doc.valid_till, nowdate()) if doc.valid_till else '?'} days left)\n"
		f"Contact: {doc.get('contact_display') or ''}\nItems:\n{items}")
	system = _base_system(settings, language) + (
		"\nWrite a short, polite reminder email that the quotation is about to expire, offering help with questions"
		" and asking whether they would like to proceed. Under 120 words. body_html uses simple <p> tags, no signature.")
	result = complete_json(system, user, schema=EMAIL_SCHEMA, feature="quotation_reminder",
		reference=("Quotation", doc.name), max_tokens=700, temperature=0.3)
	body = str(result.get("body_html") or "").strip()
	if settings.get("ai_email_signature"):
		body += f"<br>{settings.ai_email_signature}"
	return frappe.get_doc({"doctype": DRAFT_DT, "purpose": "Quotation Reminder", "sequence_no": 1, "language": language,
		"reference_doctype": "Quotation", "reference_name": doc.name, "recipient": doc.contact_email,
		"subject": str(result.get("subject") or _("Your quotation {0}").format(doc.name))[:140], "body": body,
		"generated_by_ai": 1}).insert(ignore_permissions=True).name


# ============================================================================== desk API
def _check(doctype, name, ptype="write"):
	if not frappe.has_permission(doctype, ptype, name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _run(fn, *args, **kwargs):
	try:
		return fn(*args, **kwargs)
	except AIError as e:
		frappe.throw(str(e), title=_("AlphaX AI"))


@frappe.whitelist(methods=["POST"])
def api_next_action(lead, language=None):
	_check("Lead", lead)
	return _run(next_best_action, lead, language)


@frappe.whitelist(methods=["POST"])
def api_research_website(lead, language=None):
	_check("Lead", lead)
	return _run(research_website, lead, language)


@frappe.whitelist(methods=["POST"])
def api_draft_followups(lead, steps=None, purpose="Follow-up", instruction="", language=None):
	_check("Lead", lead)
	if not frappe.has_permission(DRAFT_DT, "create"):
		frappe.throw(_("Not permitted to create email drafts"), frappe.PermissionError)
	return _run(draft_followups, lead, cint(steps) or None, purpose, instruction, language)


@frappe.whitelist(methods=["POST"])
def api_draft_quotation_reminder(quotation, language=None):
	_check("Quotation", quotation, "read")
	if not frappe.has_permission(DRAFT_DT, "create"):
		frappe.throw(_("Not permitted to create email drafts"), frappe.PermissionError)
	return _run(draft_quotation_reminder, quotation, language)


# ============================================================================== WF-07: lead brief
BRIEF_LEAD_SCHEMA = {
	"type": "object",
	"properties": {"summary": {"type": "string"}, "last_interaction": {"type": "string"},
		"open_items": {"type": "array", "items": {"type": "string"}}},
	"required": ["summary", "last_interaction", "open_items"],
}


def lead_brief(lead_name, language=None) -> dict:
	"""History summary, last interaction and open items, written to the AI Brief field."""
	settings = get_settings()
	lead = frappe.get_doc("Lead", lead_name)
	ctx = lead_context(lead)
	open_items = []
	for t in frappe.get_all("ToDo", filters={"reference_type": "Lead", "reference_name": lead.name, "status": "Open"},
			fields=["description", "date"], limit=5):
		open_items.append(f"ToDo: {strip_html(t.description or '')[:120]} (due {t.date or '-'})")
	if frappe.db.table_exists("AlphaX Follow-up"):
		for f in frappe.get_all("AlphaX Follow-up", filters={"reference_doctype": "Lead", "reference_name": lead.name,
				"next_follow_up_date": [">=", nowdate()]}, fields=["next_action", "next_follow_up_date"], limit=3):
			open_items.append(f"Follow-up: {f.next_action or ''} on {f.next_follow_up_date}")
	if lead.get("alphax_proposed_action"):
		open_items.append(f"Pending decision: {lead.alphax_proposed_action}")
	language = language or lead_language(lead.name)
	system = _base_system(settings, language) + (
		"\nWrite a brief for the salesperson about this lead. summary = 2-3 sentences on the history and where it stands;"
		" last_interaction = the most recent contact (date, channel, what was said); open_items = what is pending."
		" Use only the data given.")
	user = _context_text(ctx) + "\nOPEN ITEMS\n" + ("\n".join(f"- {i}" for i in open_items) or "- none")
	r = complete_json(system, user, schema=BRIEF_LEAD_SCHEMA, feature="lead_brief", reference=("Lead", lead.name), max_tokens=700)
	items = [str(i) for i in (r.get("open_items") or [])][:6]
	brief = str(r.get("summary") or "").strip()
	if r.get("last_interaction"):
		brief += "\n" + _("Last interaction") + ": " + str(r["last_interaction"]).strip()
	if items:
		brief += "\n" + _("Open items") + ":\n" + "\n".join(f"• {i}" for i in items)
	frappe.db.set_value("Lead", lead.name, {"alphax_ai_brief": brief, "alphax_ai_last_run": now_datetime()}, update_modified=False)
	return {"brief": brief}


@frappe.whitelist(methods=["POST"])
def api_lead_brief(lead, language=None):
	_check("Lead", lead, "read")
	return _run(lead_brief, lead, language)


# ============================================================================== WF-07: intent detection
INTENTS = {
	"interested": "Interested", "revision": "Quotation", "postpone": "Postponed",
	"rejected": "Lost with reason", "ready_to_sign": "Contract Under Signing",
}
INTENT_SCHEMA = {
	"type": "object",
	"properties": {
		"intent": {"type": "string", "enum": list(INTENTS) + ["other"]},
		"confidence": {"type": "integer"},
		"summary": {"type": "string"},
	},
	"required": ["intent", "confidence", "summary"],
}
INTENT_LABELS = {"interested": "Interested", "revision": "Asks for a revision", "postpone": "Wants to postpone",
	"rejected": "Rejected", "ready_to_sign": "Ready to sign", "other": "Other"}


def on_inbound_email(doc, method=None):
	"""Inbound client email on a Lead (or on a Quotation linked to one): detect intent in the background."""
	if doc.get("sent_or_received") != "Received" or doc.get("communication_type") != "Communication":
		return
	settings = get_settings()
	if not (cint(settings.ai_enabled) and cint(settings.get("ai_intent_detection", 1))):
		return
	lead = None
	if doc.reference_doctype == "Lead":
		lead = doc.reference_name
	elif doc.reference_doctype == "Quotation":
		from alphax_crm.crm.automation import lead_for_quotation

		lead = lead_for_quotation(doc.reference_name)
	if lead and frappe.db.exists("Lead", lead):
		frappe.enqueue("alphax_crm.ai.sales.detect_intent", queue="short", communication=doc.name, lead=lead,
			enqueue_after_commit=True, job_id=f"alphax_intent::{doc.name}", deduplicate=True)


def detect_intent(communication, lead):
	from alphax_crm.crm import automation as auto
	from alphax_crm.crm.workflow import approved_stages, stage_depth

	comm = frappe.get_doc("Communication", communication)
	text = pure.truncate(strip_html(comm.content or ""), 4000)
	if not text.strip():
		return None
	settings = get_settings()
	current = frappe.db.get_value("Lead", lead, "status")
	system = ("You classify a client's email to a B2B sales team (Arabic or English). intent is one of: interested "
		"(wants to proceed or know more), revision (asks to change the quotation/price/scope), postpone (later, not now), "
		"rejected (not interested / went elsewhere), ready_to_sign (accepts, asks for contract/PO), other. "
		"confidence 0-100. summary = one sentence in English quoting the key phrase.")
	try:
		r = complete_json(system, f"Subject: {comm.subject or ''}\n\n{text}", schema=INTENT_SCHEMA,
			feature="intent_detection", reference=("Lead", lead), max_tokens=300, temperature=0)
	except AIError:
		return None
	intent = r.get("intent") if r.get("intent") in INTENT_LABELS else "other"
	conf = pure.clamp(r.get("confidence", 0), 0, 100)
	suggested = INTENTS.get(intent)
	if suggested and suggested.lower() not in {s.lower() for s in approved_stages(settings)}:
		suggested = None
	if suggested and suggested.lower() == (current or "").lower():
		suggested = None
	if intent == "interested" and suggested:
		depth = stage_depth(settings)
		if depth.get((current or "").lower(), 0) >= depth.get("interested", 1):
			suggested = None  # already past Interested: nothing to suggest
	label = f"{INTENT_LABELS[intent]} ({conf}%) — {pure.truncate(str(r.get('summary') or ''), 200)}"
	frappe.db.set_value("Lead", lead, {"alphax_ai_intent": label, "alphax_ai_suggested_stage": suggested or ""},
		update_modified=False)
	auto.system_comment("Lead", lead, f"AlphaX AI: inbound email intent = {label}"
		+ (f'; suggested stage "{suggested}" (needs your confirmation)' if suggested else ""))
	owner = frappe.db.get_value("Lead", lead, "lead_owner") or frappe.db.get_value("Lead", lead, "owner")
	auto.notify("WF-07 AI intent detected", [owner], _("Client email on {0}: {1}").format(lead, INTENT_LABELS[intent]),
		label + (("\n\n" + _('Suggested stage: **{0}**. Open the Lead and use "Apply Suggested Stage" to confirm.').format(suggested))
			if suggested else ""), lead=lead, email=False, respect_hours=False, key=f"WF-07 intent|{communication}")
	frappe.db.commit()
	return {"intent": intent, "confidence": conf, "suggested_stage": suggested}


@frappe.whitelist(methods=["POST"])
def apply_suggested_stage(lead, next_contact_date=None):
	"""The user confirms the AI's suggested stage. All workflow rules (WF-01/05/06) still apply."""
	_check("Lead", lead)
	doc = frappe.get_doc("Lead", lead)
	stage = doc.get("alphax_ai_suggested_stage")
	if not stage:
		frappe.throw(_("There is no suggested stage on this Lead."))
	doc.status = stage
	if next_contact_date:
		doc.alphax_next_contact_date = next_contact_date
	doc.alphax_ai_suggested_stage = None
	doc.save()
	return doc.status
