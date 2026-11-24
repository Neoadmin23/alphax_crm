"""Approved Lead workflow (spec sections A and B): stage <-> status mapping, stage protection
against ERPNext core overrides, WF-01 approved stages, WF-02 quotation existence check,
WF-03 quotation confirmation, WF-04 quotation validity follow-up, WF-05 SLA engine,
WF-06 Lost Quotation control. Notifications go through crm.automation.notify (business hours,
email + in-app + timeline, de-duplicated, logged).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import (add_days, cint, date_diff, escape_html, formatdate, get_datetime, get_url_to_form, getdate,
	now_datetime, nowdate)

from alphax_crm.crm import automation as auto
from alphax_crm.crm import emails
from alphax_crm.crm.utils import ensure_select_option, get_settings, log_error

STAGE = "status"
STATUS = "custom_lead_status"
CORE_STATUSES = {"Open", "Replied", "Opportunity", "Quotation", "Converted", "Lost Quotation", "Interested", "Do Not Contact", "Lead"}

# Spec section A: Lead Stage -> Lead Status (custom_lead_status)
SPEC_STAGE_MAP = [
	("Lead", "Lead"), ("Interested", "Lead"), ("Qualified lead", "Lead"), ("Quotation", "Prospect"),
	("Postponed", "Cold Lead"), ("Contract Under Signing", "Successful"), ("Won", "Customer"),
	("Lost with reason", "Inactive Lead"), ("Lost Quotation", "Inactive Lead"),
]
SPEC_FLOW = ["Lead", "Interested", "Qualified lead", "Quotation", "Postponed", "Contract Under Signing", "Won",
	"Lost with reason", "Lost Quotation"]


# ============================================================================ stages
def stage_map(settings=None):
	"""[(stage, status)] from AlphaX CRM Settings > Lead Stage Map (rows: Lead Status, Lead Stage)."""
	return list(SPEC_STAGE_MAP)


def approved_stages(settings=None):
	return list(SPEC_FLOW)


def initial_stage(settings=None) -> str:
	stages = approved_stages(settings)
	return stages[0] if stages else "Lead"


def stage_depth(settings=None) -> dict:
	"""Distance of each stage from the initial stage along the approved transitions."""
	settings = settings or get_settings()
	start = initial_stage(settings).lower()
	edges = {}
	for t in settings.get("stage_transitions") or []:
		edges.setdefault((t.from_stage or "").strip().lower(), []).append((t.to_stage or "").strip().lower())
	depth, queue = {start: 0}, [start]
	while queue:
		cur = queue.pop(0)
		for nxt in edges.get(cur, []):
			if nxt not in depth:
				depth[nxt] = depth[cur] + 1
				queue.append(nxt)
	return depth


def _is_approved(stage, settings) -> bool:
	return (stage or "").strip().lower() in {s.lower() for s in approved_stages(settings)}


def status_for_stage(stage, settings=None):
	for s, st in stage_map(settings):
		if s.lower() == (stage or "").strip().lower():
			return st
	return None


def stage_for_status(status, current_stage, settings=None):
	"""Reverse map. Several stages share a status (Lead/Interested/Qualified -> Lead): keep the
	current stage if it already maps to that status, else take the first stage for it."""
	rows = stage_map(settings)
	if any(s.lower() == (current_stage or "").lower() and st.lower() == (status or "").lower() for s, st in rows):
		return current_stage
	for s, st in rows:
		if st.lower() == (status or "").strip().lower():
			return s
	return None


# ============================================================================ Lead hooks
def lead_before_validate(doc, method=None):
	"""Remember the stage the user chose, before ERPNext core's Lead.set_status() runs."""
	doc.flags.alphax_intended_stage = doc.get(STAGE)


def lead_validate(doc, settings):
	"""Runs from crm.lead.validate (after core validate): protect, sync, enforce."""
	protect_stage_from_core(doc, settings)
	sync_stage_and_status(doc, settings)
	enforce_approved_stage(doc, settings)
	enforce_postponed_date(doc, settings)
	if doc.get(STAGE) == "Contract Under Signing" and doc.get("custom_contract"):
		frappe.throw(_("Clear Contract while the contract is under signing. Set it to Signed when marking the Lead Won."))


def protect_stage_from_core(doc, settings):
	if not cint(settings.get("protect_lead_stage", 1)):
		return
	intended = doc.flags.get("alphax_intended_stage")
	current = doc.get(STAGE)
	if not intended or current == intended or current not in CORE_STATUSES:
		return
	# approved stage chosen by the user, or a legacy value (Open, Replied...) already stored on an old
	# Lead: either way core's side-effect must not change it (otherwise old Leads become unsavable)
	doc.set(STAGE, intended)


def sync_stage_and_status(doc, settings):
	"""Spec A in both directions. Stage changed -> Lead Status follows. Only Lead Status changed ->
	Lead Stage follows (the stage rules below then still apply)."""
	if not cint(settings.get("auto_set_stage_from_status", 1)) or not doc.meta.has_field(STATUS):
		return
	if doc.is_new():
		old_stage, old_status = None, None
	else:
		old_stage, old_status = frappe.db.get_value("Lead", doc.name, [STAGE, STATUS]) or (None, None)
	stage, status = doc.get(STAGE), doc.get(STATUS)
	if stage:
		stage = next((s for s in SPEC_FLOW if s.lower() == stage.strip().lower()), stage)
		doc.set(STAGE, stage)
	if stage != old_stage or doc.is_new():
		target = status_for_stage(stage, settings)
		if target and target != status:
			ensure_select_option("Lead", STATUS, target)
			doc.set(STATUS, target)
	elif status != old_status:
		target = stage_for_status(status, stage, settings)
		if not target:
			frappe.throw(_("Select a Lead Status from the approved mapping."))
		if target != stage:
			ensure_select_option("Lead", STAGE, target)
			doc.set(STAGE, target)
			doc.flags.alphax_stage_auto_set = True


def enforce_approved_stage(doc, settings):
	"""WF-01: only approved stages; a new Lead starts at the first stage."""
	if not cint(settings.get("stage_flow_enabled", 1)) or doc.flags.get("alphax_system_stage"):
		return
	stages = approved_stages(settings)
	if not stages:
		return
	stage = (doc.get(STAGE) or "").strip()
	first = initial_stage(settings)
	if doc.is_new():
		if stage.lower() != first.lower():
			doc.set(STAGE, first)
			if doc.meta.has_field(STATUS):
				doc.set(STATUS, status_for_stage(first, settings) or doc.get(STATUS))
		return
	if not _is_approved(stage, settings):
		old = frappe.db.get_value("Lead", doc.name, STAGE)
		if (old or "") == stage:
			return  # legacy value already stored: allow other edits; health check reports it
		frappe.throw(_('"{0}" is not a stage in the approved Lead workflow. Use one of: {1}').format(
			stage, ", ".join(stages)), title=_("Stage Not Allowed"))


def enforce_postponed_date(doc, settings):
	"""WF-05: Next Contact Date is mandatory for Postponed (and must be today or later when entering it)."""
	if not cint(settings.get("postponed_require_next_contact", 1)):
		return
	postponed = (settings.get("postponed_stage_value") or "Postponed").strip().lower()
	if (doc.get(STAGE) or "").strip().lower() != postponed or not doc.meta.has_field("alphax_next_contact_date"):
		return
	old_stage, old_date = (None, None) if doc.is_new() else (frappe.db.get_value("Lead", doc.name,
		[STAGE, "alphax_next_contact_date"]) or (None, None))
	entering = (old_stage or "").strip().lower() != postponed
	date = doc.get("alphax_next_contact_date")
	# Entering Postponed: the date must be chosen in the same save. The date AlphaX seeds when a
	# Lead is created ("first follow-up") must not count as the agreed revisit date.
	chosen = date and (not entering or str(getdate(date)) != str(getdate(old_date) if old_date else ""))
	if date and doc.get("alphax_confirmed_postpone_date") and getdate(doc.alphax_confirmed_postpone_date) == getdate(date):
		chosen = True
	if doc.meta.has_field("alphax_confirmed_postpone_date"):
		doc.alphax_confirmed_postpone_date = None
	if not date or not chosen or (entering and getdate(date) < getdate(nowdate())):
		frappe.throw(_("Choose the Next Contact Date (today or later) when postponing this Lead."),
			title=_("Next Contact Date Required"))


def lead_on_update(doc, before, settings):
	"""Log every stage/status change (SLA timers start here) and start WF-02 when entering Quotation."""
	if not before:
		return
	if doc.get("alphax_review_status") != before.get("alphax_review_status"):
		state = doc.get("alphax_review_status")
		if state in ("Pending Review", "Returned for Correction", "Approved"):
			if state == "Pending Review":
				from alphax_crm.setup.install import REVIEWER_ROLE
				people = auto.approvers(frappe._dict(approver_role=REVIEWER_ROLE))
			else:
				people = [doc.get("lead_owner") or doc.owner]
			auto.notify("Lead review " + state, people, lead=doc.name,
				subject=_("Lead {0}: {1}").format(doc.name, state),
				message=escape_html(doc.get("alphax_review_notes") or state))
	if before.get(STAGE) != doc.get(STAGE):
		_transition(doc.name, "Lead Stage", before.get(STAGE), doc.get(STAGE))
		if doc.meta.has_field("alphax_proposed_action") and doc.get("alphax_proposed_action"):
			frappe.db.set_value("Lead", doc.name, "alphax_proposed_action", None, update_modified=False)
		if (doc.get(STAGE) or "").lower() == "quotation":
			wf02_check_lead(doc.name, settings, on_entry=True)
	if doc.meta.has_field(STATUS) and before.get(STATUS) != doc.get(STATUS) and doc.get(STATUS):
		_transition(doc.name, "Lead Status", before.get(STATUS), doc.get(STATUS))


def set_stage_system(lead, stage, reason, reference=None, rule="Stage auto-move", from_stage=None):
	"""A documented system stage move: syncs Lead Status, stamps Won/Lost date for closing stages,
	clears pending proposals, logs the transition, adds a timeline note and an automation-log row.
	Also completes the job when ERPNext core already flipped the stage silently (from_stage = the
	stage before core touched it)."""
	settings = get_settings()
	current = frappe.db.get_value("Lead", lead, STAGE)
	from_stage = from_stage or current
	meta = frappe.get_meta("Lead")
	ensure_select_option("Lead", STAGE, stage)
	values = {STAGE: stage}
	st = status_for_stage(stage, settings)
	if st and meta.has_field(STATUS):
		ensure_select_option("Lead", STATUS, st)
		values[STATUS] = st
	closing = {x.strip().lower() for x in (settings.get("lost_stage_values") or "").split(",")} | {(settings.get("won_stage_value") or "Won").lower()}
	if stage.lower() in closing and meta.has_field("won_or_lost_date") and not frappe.db.get_value("Lead", lead, "won_or_lost_date"):
		values["won_or_lost_date"] = nowdate()
	if meta.has_field("alphax_proposed_action"):
		values["alphax_proposed_action"] = None
	# update `modified` so a form opened before this move gets "document has been modified"
	# instead of silently writing the old stage back
	frappe.db.set_value("Lead", lead, values)
	if from_stage == stage:
		logged = auto.last_logged_stage(lead)  # core may already have written `stage` in SQL
		if not logged or logged == stage:
			return False
		from_stage = logged
	_transition(lead, "Lead Stage", from_stage, stage)
	auto.system_comment("Lead", lead, f'AlphaX: Lead Stage moved from "{from_stage}" to "{stage}" — {reason}')
	auto.log_action(rule, lead, reference, f"{from_stage} → {stage}: {reason}")
	return True


def _transition(lead, label, old, new):
	try:
		from alphax_crm.crm.activity import record_transition

		record_transition("Lead", lead, label, old, new)
	except Exception:
		log_error("record transition")


# ============================================================================ stage protection for linked docs
def _stash(doc, lead):
	if lead and frappe.db.exists("Lead", lead):
		doc.flags.alphax_lead = lead
		doc.flags.alphax_lead_stage = frappe.db.get_value("Lead", lead, STAGE)


def _restore(doc, why):
	"""Undo a Lead Stage change ERPNext core made as a side effect of saving a linked document."""
	settings = get_settings()
	if not cint(settings.get("protect_lead_stage", 1)):
		return
	lead, before = doc.flags.get("alphax_lead"), doc.flags.get("alphax_lead_stage")
	if not lead or not before or not _is_approved(before, settings):
		return
	now = frappe.db.get_value("Lead", lead, STAGE)
	if now == before or now not in CORE_STATUSES:
		return
	frappe.db.set_value("Lead", lead, STAGE, before, update_modified=False)
	auto.system_comment("Lead", lead, f'AlphaX: Lead Stage kept at "{before}" (ERPNext had changed it to "{now}" after {why}).')


def customer_validate(doc, method=None):
	_stash(doc, doc.get("lead_name"))


def customer_after_save(doc, method=None):
	_restore(doc, _("the Customer was saved"))


def opportunity_validate(doc, method=None):
	if doc.get("opportunity_from") == "Lead":
		_stash(doc, doc.get("party_name"))


def opportunity_after_save(doc, method=None):
	_restore(doc, _("the Opportunity was saved"))


# ============================================================================ Quotation hooks (WF-02/03/06)
def quotation_validate(doc, method=None):
	settings = get_settings()
	lead = auto.lead_for_quotation(doc)
	_stash(doc, lead)
	if lead and cint(settings.get("wf03_require_valid_till", 1)) and not doc.get("valid_till"):
		frappe.throw(_("Valid Till is mandatory on a Quotation linked to a Lead ({0}).").format(lead), title=_("Valid Till Required"))


def quotation_before_submit(doc, method=None):
	_stash(doc, auto.lead_for_quotation(doc))


def quotation_after_insert(doc, method=None):
	"""Approvers are told whenever an agent creates a quotation (WF-02)."""
	settings = get_settings()
	if not cint(settings.get("notify_approvers_on_quotation_create", 1)):
		return
	lead = auto.lead_for_quotation(doc)
	auto.notify("WF-02 Quotation created", auto.approvers(settings), lead=lead, reference=("Quotation", doc.name),
		trigger_date=nowdate(), key=f"WF-02 created|{doc.name}",
		context={**emails.quotation_context(doc, lead), "created_by": frappe.utils.get_fullname(doc.owner)})

def quotation_on_submit(doc, method=None):
	settings = get_settings()
	lead = auto.lead_for_quotation(doc)
	if lead:
		_wf03_move_lead(doc, lead, settings)
	if cint(settings.get("wf03_confirmation_enabled", 1)):
		people = [doc.owner] + ([frappe.db.get_value("Lead", lead, "lead_owner")] if lead else [])
		auto.notify("WF-03 Quotation confirmation", people, lead=lead, reference=("Quotation", doc.name),
			trigger_date=nowdate(), key=f"WF-03 confirm|{doc.name}", context=emails.quotation_context(doc, lead))
	if cint(settings.get("notify_approvers_on_quotation", 1)):
		auto.notify("WF-02 Quotation submitted", auto.approvers(settings), lead=lead,
			reference=("Quotation", doc.name), trigger_date=nowdate(), key=f"WF-02 submitted|{doc.name}",
			context=emails.quotation_context(doc, lead))

def quotation_before_cancel(doc, method=None):
	"""Cancel runs no validate: stash the Lead stage here so on_cancel can undo core's change."""
	_stash(doc, auto.lead_for_quotation(doc))


def quotation_on_cancel(doc, method=None):
	_restore(doc, _("the Quotation was cancelled"))


def _wf03_move_lead(doc, lead, settings):
	"""Lead still at an earlier stage -> move to Quotation (logged); otherwise keep its stage."""
	before = doc.flags.get("alphax_lead_stage") or frappe.db.get_value("Lead", lead, STAGE)
	target = "Quotation"
	b = (before or "").strip().lower()
	earlier = b in {"lead", "interested", "qualified lead", "open", "replied", "opportunity"}
	if earlier and cint(settings.get("wf03_move_lead_to_quotation", 1)):
		frappe.db.set_value("Lead", lead, STAGE, before, update_modified=False)  # undo core's silent change first
		set_stage_system(lead, target, _("Quotation {0} was submitted (WF-03)").format(doc.name), ("Quotation", doc.name),
			"WF-03 Lead moved to Quotation")
	elif before and frappe.db.get_value("Lead", lead, STAGE) != before:
		frappe.db.set_value("Lead", lead, STAGE, before, update_modified=False)


def check_lost_quotation(doc, settings):
	"""WF-06: Lost Quotation needs a linked quotation marked Lost, with a reason."""
	stage = (doc.get(STAGE) or "").strip().lower()
	lq = (settings.get("lost_quotation_stage_value") or "Lost Quotation").strip().lower()
	if stage != lq:
		return True
	lost = auto.quotations_for_lead(doc.name, {"docstatus": 1, "status": "Lost"}, fields=("name", "order_lost_reason"))
	for q in lost:
		if (q.order_lost_reason or "").strip() or frappe.db.exists("Quotation Lost Reason Detail", {"parent": q.name, "parenttype": "Quotation", "lost_reason": ["is", "set"]}):
			return True
	frappe.throw(_("Lost Quotation needs a linked Quotation marked Lost with a reason. Open the quotation and use "
		"<b>Set as Lost</b> (or the <b>Confirm Lost Quotation</b> button on the Lead)."), title=_("Closure Requirements Not Met"))


@frappe.whitelist(methods=["POST"])
def confirm_lost_quotation(quotation, reason, detailed_reason=None):
	"""User confirmation for WF-04's proposal: mark the quotation Lost with a reason; the Lead moves
	to Lost Quotation through ERPNext's own Set-as-Lost path (WF-06 then passes)."""
	q = frappe.get_doc("Quotation", quotation)
	q.check_permission("write")
	settings = get_settings()
	lead = auto.lead_for_quotation(q)
	if lead:
		if not frappe.has_permission("Lead", "write", lead):
			frappe.throw(_("You are not allowed to change Lead {0}.").format(lead), frappe.PermissionError)
		stage = (frappe.db.get_value("Lead", lead, STAGE) or "").strip()
		if stage.lower() in _terminal(settings):
			frappe.throw(_('Lead {0} is already closed ("{1}"); its quotation cannot move it to Lost Quotation.').format(
				lead, stage), title=_("Lead Closed"))
		if stage.lower() not in {"quotation", "postponed", "contract under signing"}:
			frappe.throw(_("Move the Lead through the approved workflow before closing its quotation."))
		_stash(q, lead)
	if q.docstatus != 1 or q.status not in ("Open", "Expired", "Replied") or not (reason or "").strip():
		frappe.throw(_("Choose an open or expired submitted quotation and supply a loss reason."))
	if not frappe.db.exists("Quotation Lost Reason", reason):
		frappe.throw(_("Select an existing Quotation Lost Reason."))
	q.flags.alphax_confirmed_by = frappe.utils.get_fullname()
	q.declare_enquiry_lost([{"lost_reason": reason}], [], detailed_reason or reason)
	# guard_lead_stage (on_update_after_submit) normally ran quotation_marked_lost already
	if lead and not q.flags.get("alphax_lost_handled"):
		quotation_marked_lost(q)
	return {"quotation": quotation, "lead": lead, "stage": frappe.db.get_value("Lead", lead, STAGE) if lead else None}


# ============================================================================ WF-02 (hourly)
def wf02_check_lead(lead, settings=None, on_entry=False):
	settings = settings or get_settings()
	if not cint(settings.get("wf_quotation_check_enabled", 1)) or auto.is_paused(lead):
		return
	if auto.quotations_for_lead(lead, {"docstatus": ["<", 2]}):
		return
	entry = auto.stage_entry_datetime(lead, "Quotation")
	people = auto.lead_people(lead)
	if on_entry or not auto.already_done(f"WF-02 alert|{lead}|{getdate(entry)}"):
		auto.notify("WF-02 No quotation (alert)", people, lead=lead, trigger_date=entry,
			key=f"WF-02 alert|{lead}|{getdate(entry)}")
		if on_entry:
			return
	hours = auto.working_hours_between(entry, now_datetime())
	if hours >= cint(settings.get("wf02_escalation_hours") or 72):
		auto.notify("WF-02 No quotation (escalation)", list(set(auto.approvers(settings) + people)), lead=lead,
			trigger_date=entry, key=f"WF-02 escalation|{lead}|{getdate(entry)}", context={"hours": int(hours)})
	if hours >= cint(settings.get("wf02_reminder_hours") or 24):
		auto.notify("WF-02 No quotation (reminder)", people, lead=lead, trigger_date=entry,
			key=f"WF-02 reminder|{lead}|{getdate(entry)}", context={"hours": int(hours)})


def wf02_hourly():
	settings = get_settings()
	if not cint(settings.get("wf_quotation_check_enabled", 1)) or not auto.is_business_time():
		return
	for row in _leads_paged({STAGE: "Quotation"}, ["name"]):
		lead = row.name
		try:
			wf02_check_lead(lead, settings)
		except Exception:
			log_error(f"WF-02 {lead}")
	frappe.db.commit()


# ============================================================================ WF-04 (daily 08:00, working days)
def wf04_daily():
	settings = get_settings()
	if not cint(settings.get("wf04_enabled", 1)) or not auto.is_working_day(nowdate()):
		return
	before = cint(settings.get("wf04_days_before") or 2)
	after = cint(settings.get("wf04_escalate_days_after") or 3)
	today = getdate(nowdate())
	# "Expired" too: ERPNext's own daily job flips Open -> Expired the day after Valid Till, and the
	# T0 (weekend expiry) and T+3 steps happen after that. The window ahead covers weekends/holidays
	# because T-2 counts working days.
	quotations = _leads_paged(filters={"docstatus": 1, "status": ["in", ["Open", "Replied", "Expired"]],
		"valid_till": ["<=", add_days(today, before + 60)]},
		fields=["name", "owner", "creation", "valid_till", "transaction_date", "quotation_to", "party_name", "opportunity",
			"contact_email", "grand_total", "currency"], doctype="Quotation")
	for q in quotations:
		try:
			_wf04_quotation(q, today, before, after, settings)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			log_error(f"WF-04 {q.name}")


def _wf04_quotation(q, today, before, after, settings):
	lead = auto.lead_for_quotation(q)
	if lead and (auto.is_paused(lead) or (frappe.db.get_value("Lead", lead, STAGE) or "").lower() in _terminal(settings)):
		return
	owner = (frappe.db.get_value("Lead", lead, "lead_owner") if lead else None) or q.owner
	days_to = date_diff(q.valid_till, today)
	# follow-up = activity after the quotation was issued; moving the Lead INTO Quotation (WF-03) is not one
	since = _quotation_activity_start(q)
	activity = auto.activity_since(lead, since, extra_refs=[("Quotation", q.name)], ignore_stage_to=("Quotation",)) \
		if lead else _quotation_activity(q)
	vt = formatdate(q.valid_till)
	name = q.name
	key = lambda m: f"WF-04 {m}|{name}|{q.valid_till}"
	ref = ("Quotation", name)
	if days_to <= -after:
		if lead and frappe.db.get_value("Lead", lead, STAGE) != "Quotation":
			return
		if auto.already_done(key("T+")):
			return
		# "if no action has been taken": anything done since the quotation expired cancels the proposal
		after_expiry = get_datetime(q.valid_till)
		late = auto.activity_since(lead, after_expiry, extra_refs=[("Quotation", q.name)], ignore_stage_to=("Quotation",)) \
			if lead else _quotation_activity(q, since=after_expiry)
		if late:
			return
		if lead and frappe.get_meta("Lead").has_field("alphax_proposed_action"):
			frappe.db.set_value("Lead", lead, "alphax_proposed_action",
				_("Confirm Lost Quotation for {0} (expired {1}, no action)").format(name, vt), update_modified=False)
		auto.notify("WF-04 Expired, no action (escalation)", list({owner} | set(auto.approvers(settings))),
			lead=lead, reference=ref, trigger_date=q.valid_till, key=key("T+"),
			context={**emails.quotation_context(name, lead), "days_expired": -days_to})
		return
	if days_to <= 0:
		if activity or auto.already_done(key("T0")):
			return
		auto.notify("WF-04 Valid Till reached, no activity", list({owner} | set(auto.approvers(settings))),
			lead=lead, reference=ref, trigger_date=q.valid_till, key=key("T0"), context=emails.quotation_context(name, lead))
		return
	notice_date = validity_notice_date(q.valid_till, before, settings)
	if today >= notice_date and not auto.already_done(key("T-")):
		if activity:
			auto.notify("WF-04 Validity notice", [owner], lead=lead, reference=ref, trigger_date=q.valid_till, key=key("T-"),
				context={**emails.quotation_context(name, lead), "activity": ", ".join(activity)})
		else:
			draft = None
			if cint(settings.get("wf04_ai_draft", 1)) and (q.contact_email or (lead and frappe.db.get_value("Lead", lead, "email_id"))) and cint(settings.get("ai_enabled")):
				try:
					from alphax_crm.ai.sales import draft_quotation_reminder, lead_language

					draft = draft_quotation_reminder(name, lead_language(lead) if lead else None)
				except Exception:
					log_error(f"WF-04 AI draft {name}")
			if not draft:
				auto.log_action("WF-04 Draft unavailable", lead, ref,
					"Review AI settings, provider and contact email. Use Draft Expiry Reminder after correction.")

			auto.notify("WF-04 Expiring, no activity (reminder)", [owner], lead=lead, reference=ref,
				trigger_date=q.valid_till, key=key("T-"),
				context={**emails.quotation_context(name, lead), "ai_draft": draft or ""})


def validity_notice_date(expiry, days_before, settings):
	notice = getdate(add_days(expiry, -days_before))
	cal = auto.calendar(settings)
	for step in range(60):
		if auto.is_working_day(notice, cal):
			break
		notice = getdate(add_days(notice, -1))
	return notice


def _quotation_activity_start(q):
	issue = get_datetime(q.transaction_date)
	created = get_datetime(q.creation)
	return max(issue, created) if getdate(issue) == getdate(created) else issue


def _quotation_activity(q, since=None):
	return auto.activity_since(None, since or _quotation_activity_start(q),
		extra_refs=[("Quotation", q.name)])


def lost_quotation_digest():
	"""Daily (working days 08:00) follow-up of lost quotations for Sales Managers (Approvers)."""
	settings = get_settings()
	if not cint(settings.get("lost_quotation_digest_enabled", 1)) or not auto.is_working_day(nowdate()):
		return
	people = auto.approvers(settings)
	today = nowdate()
	for q in _leads_paged({"status": "Lost", "docstatus": 1}, ["name", "party_name", "quotation_to",
			"opportunity", "order_lost_reason"], doctype="Quotation"):
		lead = auto.lead_for_quotation(q)
		if lead and auto.is_paused(lead):
			continue
		reasons = frappe.get_all("Quotation Lost Reason Detail", filters={"parent": q.name,
			"parenttype": "Quotation"}, pluck="lost_reason")
		auto.notify("WF-04 Daily lost quotation", people, lead=lead, reference=("Quotation", q.name),
			trigger_date=today, context={**emails.quotation_context(q.name, lead),
				"reason": ", ".join(reasons) or q.order_lost_reason or _("No reason recorded")})


# ============================================================================ WF-05 SLA engine (daily 08:00)
def _terminal(settings):
	won = (settings.get("won_stage_value") or "Won").strip().lower()
	out = {s.strip().lower() for s in (settings.get("lost_stage_values") or "").split(",") if s.strip()}
	return out | {won, "do not contact", "converted"}


def sla_daily():
	settings = get_settings()
	if not cint(settings.get("stage_sla_enabled", 1)) or not auto.is_working_day(nowdate()):
		return
	rules = settings.get("stage_sla_rules") or []
	by_stage = {}
	for r in rules:
		by_stage.setdefault((r.stage or "").strip(), []).append(r)
	today = getdate(nowdate())
	terminal = _terminal(settings)
	for stage, stage_rules in by_stage.items():
		if not stage or stage.lower() in terminal:
			continue
		for lead in _leads_paged({STAGE: stage}, ["name", "lead_name", "lead_owner", "owner"]):
			try:
				_sla_lead(lead, stage, stage_rules, today, settings)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				log_error(f"SLA {lead.name}")
	for fn in (postponed_daily, contract_close_daily):
		try:
			fn(settings)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			log_error(f"SLA {fn.__name__}")


def _leads_paged(filters, fields, page=500, doctype="Lead"):
	"""All matching Leads, in pages (no silent cap on big pipelines)."""
	start = 0
	while True:
		rows = frappe.get_all(doctype, filters=filters, fields=fields, order_by="name asc", start=start, page_length=page)
		yield from rows
		if len(rows) < page:
			return
		start += page


def _sla_lead(lead, stage, stage_rules, today, settings):
	"""Each rule is evaluated on its own (its own key), so a milestone that fell on a weekend is sent
	on the next working day instead of being swallowed by a later one. For "no activity" rules the
	idle clock restarts at the previous occurrence, i.e. days are recalculated from the last check."""
	if auto.is_paused(lead.name):
		return
	entry = auto.stage_entry_datetime(lead.name, stage)
	days = date_diff(today, getdate(entry))
	owner = lead.lead_owner or lead.owner
	covers = {"Lead Owner": {"owner"}, "Approver (Sales Manager)": {"approver"}, "Both": {"owner", "approver"}}
	reached = set()  # audiences already notified today by a later milestone
	to_send = []
	# latest milestone first: an older one that was missed (weekend/holiday) still goes out, unless a
	# later reminder to the same people goes out today (no "first" and "second" reminder on one morning)
	for rule in sorted(stage_rules, key=lambda r: cint(r.days), reverse=True):
		start, every = cint(rule.days), cint(rule.get("repeat_every_days"))
		if stage.lower() == "lead" and start == 7:
			first_rule = next((r for r in stage_rules if cint(r.days) == 3), None)
			if first_rule:
				first_key = f"WF-05 {first_rule.label or stage}#{first_rule.days}.0|{lead.name}|{getdate(entry)}"
				sent = frappe.db.get_value(auto.LOG_DT, {"dedupe_key": first_key,
					"status": ["in", ["Sent", "Partly Sent"]]}, "sent_on")
				if not sent or date_diff(today, getdate(sent)) < 4:
					continue
		if days < start:
			continue
		occurrence = (days - start) // every if every else 0
		milestone = start + occurrence * every
		key = f"WF-05 {rule.label or rule.stage}#{rule.days}.{occurrence}|{lead.name}|{getdate(entry)}"
		if auto.already_done(key):
			continue
		window_start = add_days(getdate(entry), milestone - every) if every and occurrence else entry
		activity = auto.activity_since(lead.name, get_datetime(window_start))
		if stage.lower() == "interested":
			activity = "meeting" in activity
		elif stage.lower() == "qualified lead":
			activity = auto.quotations_for_lead(lead.name, {"docstatus": ["<", 2]})
		elif stage.lower() == "lead":
			contact = frappe.db.exists("Communication", {"reference_doctype": "Lead",
				"reference_name": lead.name, "communication_type": "Communication", "creation": [">=", entry]})
			activity = contact or {"follow-up", "meeting"}.intersection(activity)
		if cint(rule.require_no_activity) and activity and not (stage.lower() == "contract under signing" and start == 10):
			continue
		audience = covers.get(rule.notify, set())
		if audience and audience <= reached:
			auto.log_action("WF-05 superseded", lead.name, None, f"{rule.label or stage} day {milestone}: covered by a later "
				"reminder sent today", key=key)
			continue
		reached |= audience
		recipients = []
		if rule.notify in ("Lead Owner", "Both"):
			recipients.append(owner)
		if rule.notify in ("Approver (Sales Manager)", "Both"):
			recipients += auto.approvers(settings)
		label = rule.label or f"{stage} day {milestone}"
		to_send.append((recipients, {"label": label, "stage": stage, "days": days, "no_activity": not activity}, key))
	for recipients, ctx, key in reversed(to_send):  # oldest milestone first in the inbox
		auto.notify(f"WF-05 {stage}", recipients, lead=lead.name, trigger_date=entry, key=key, template="WF-05 Stage SLA",
			context=ctx)


def postponed_daily(settings):
	"""Postponed: remind on the Next Contact Date; approvers too when it is overdue with no activity
	(e.g. no comment added). No date -> revisit after N days (default 30)."""
	postponed = (settings.get("postponed_stage_value") or "Postponed").strip()
	today = getdate(nowdate())
	revisit = cint(settings.get("postponed_default_revisit_days") or 30)
	for lead in _leads_paged({STAGE: postponed}, ["name", "lead_name", "lead_owner", "owner", "alphax_next_contact_date"]):
		if auto.is_paused(lead.name):
			continue
		entry = auto.stage_entry_datetime(lead.name, postponed)
		due = getdate(lead.alphax_next_contact_date) if lead.alphax_next_contact_date else getdate(add_days(entry, revisit))
		if today < due:
			continue
		owner = lead.lead_owner or lead.owner
		activity = auto.activity_since(lead.name, entry)
		auto.notify("WF-05 Postponed follow-up", [owner], lead=lead.name, trigger_date=due,
			key=f"WF-05 postponed|{lead.name}|{due}", context={"due": formatdate(due)})
		if date_diff(today, due) >= 1 and "comment" not in activity:
			auto.notify("WF-05 Postponed overdue (approvers)", list({owner} | set(auto.approvers(settings))),
				lead=lead.name, trigger_date=due, key=f"WF-05 postponed-overdue|{lead.name}|{due}",
				context={"due": formatdate(due)})


CLOSING_FIELDS = ("custom_expected_closing_date", "expected_closing_date", "expected_closing", "alphax_expected_closing_date")


def contract_close_daily(settings):
	"""Contract Under Signing: alert when the Expected Closing Date passes."""
	if not cint(settings.get("cus_expected_close_alert", 1)):
		return
	stage = "Contract Under Signing"
	meta = frappe.get_meta("Lead")
	field = next((f for f in CLOSING_FIELDS if meta.has_field(f)), None)
	today = getdate(nowdate())
	for lead in _leads_paged({STAGE: stage}, ["name", "lead_name", "lead_owner", "owner"] + ([field] if field else [])):
		if auto.is_paused(lead.name):
			continue
		close = lead.get(field) if field else None
		if not close:
			opp = frappe.get_all("Opportunity", filters={"opportunity_from": "Lead", "party_name": lead.name},
				fields=["expected_closing"], order_by="creation desc", limit=1)
			close = opp[0].expected_closing if opp else None
		if not close or getdate(close) >= today:
			continue
		auto.notify("WF-05 Expected closing passed", list({lead.lead_owner or lead.owner} | set(auto.approvers(settings))),
			lead=lead.name, trigger_date=close, key=f"WF-05 closing-passed|{lead.name}|{getdate(close)}",
			context={"closing_date": formatdate(close)})


def new_lead_alert(doc):
	"""New lead -> Lead Owner (replaces the 'AlphaX New Lead Alert' email; business hours)."""
	owner = doc.get("lead_owner")
	if not owner:
		return
	auto.notify("New lead", [owner], lead=doc.name, key=f"New lead|{doc.name}", context={
		"lead": doc.as_dict(), "lead_name": doc.lead_name or doc.name, "source": doc.get("source") or "-",
		"score": doc.get("alphax_lead_score") or 0})


def _previous_working_day():
	"""Last working day before today (looks back up to 30 days: long Eid holidays)."""
	d = add_days(nowdate(), -1)
	while not auto.is_working_day(d) and date_diff(nowdate(), d) < 30:
		d = add_days(d, -1)
	return d


def followup_due_daily():
	"""Next Contact Date reached -> Lead Owner (replaces the 'AlphaX Follow-up Due' email). Dates that
	fell on a weekend/holiday are picked up on the next working day."""
	settings = get_settings()
	if not auto.is_working_day(nowdate()) or not frappe.get_meta("Lead").has_field("alphax_next_contact_date"):
		return
	start = _previous_working_day()
	terminal = _terminal(settings) | {(settings.get("postponed_stage_value") or "Postponed").lower()}
	for lead in frappe.get_all("Lead", filters={"alphax_next_contact_date": ["between", [add_days(start, 1), nowdate()]]},
			fields=["name", "lead_name", "lead_owner", "owner", "status", "alphax_next_contact_date"]):
		stage = (lead.status or "").lower()
		if stage in terminal or auto.is_paused(lead.name):
			continue
		explicit = _logged_followup(lead.name, lead.alphax_next_contact_date)
		if stage == "lead" and not explicit:
			continue  # the date AlphaX seeds on a new Lead is covered by the New-lead alert and the WF-05 Lead reminders
		recipients = [lead.lead_owner or lead.owner] + ([explicit.agent] if explicit and explicit.agent else [])
		auto.notify("Follow-up due", recipients, lead=lead.name,
			trigger_date=lead.alphax_next_contact_date, key=f"Follow-up due|{lead.name}|{lead.alphax_next_contact_date}",
			context={"due": formatdate(lead.alphax_next_contact_date),
				"next_action": (explicit.next_action if explicit else "") or ""})


def _logged_followup(lead_name, due):
	"""The follow-up an agent logged that set this Next Contact Date: the latest real (not AlphaX
	placeholder) AlphaX Follow-up for the Lead, if its Next Follow-up Date is `due`. Else None."""
	rows = frappe.get_all("AlphaX Follow-up", filters={"reference_doctype": "Lead", "reference_name": lead_name},
		fields=["name", "agent", "next_action", "next_follow_up_date", "summary"],
		order_by="follow_up_datetime desc, creation desc", limit=10)
	for r in rows:
		if (r.summary or "").startswith("AlphaX:"):
			continue
		return r if r.next_follow_up_date and getdate(r.next_follow_up_date) == getdate(due) else None
	return None


DAILY_JOBS = ("sla_daily", "wf04_daily", "lost_quotation_digest", "followup_due_daily")


def daily_0800():
	"""Single 08:00 (site time zone) entry point. Each rule runs as its own job on the long queue
	(1-hour timeout instead of the default queue's 5 minutes), so a big pipeline or one failing
	rule cannot stop the others."""
	for name in DAILY_JOBS:
		try:
			frappe.enqueue("alphax_crm.crm.workflow.run_daily_job", job=name, queue="long", timeout=3600,
				job_id=f"alphax-{name}-{nowdate()}", deduplicate=True)
		except Exception:
			log_error(f"enqueue {name}")
			run_daily_job(name)


def run_daily_job(job):
	if job not in DAILY_JOBS:
		return
	try:
		globals()[job]()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		log_error(f"daily workflow {job}")


def quotation_marked_lost(doc):
	"""Quotation set as Lost: the Lead becomes Lost Quotation only if no other open quotation is alive."""
	lead = auto.lead_for_quotation(doc)
	if not lead:
		return
	settings = get_settings()
	others = [q.name for q in auto.quotations_for_lead(lead, {"docstatus": 1, "status": ["not in", ["Lost", "Cancelled", "Expired"]]})
		if q.name != doc.name]
	# "Set as Lost" saves as update-after-submit (no validate) and core rewrote the Lead before that
	# save, so the stage before core touched it comes from AlphaX's own transition log.
	before = doc.flags.get("alphax_lead_stage") or (frappe.db.get_value("Lead", lead, STAGE) if doc.get("quotation_to") != "Lead" else None) or auto.last_logged_stage(lead)
	if not before:
		before = frappe.db.get_value("Lead", lead, STAGE)
	if before and before.lower() in _terminal(settings):
		if frappe.db.get_value("Lead", lead, STAGE) != before:
			frappe.db.set_value("Lead", lead, STAGE, before)
		return
	if others or (before or "").lower() not in {"quotation", "postponed", "contract under signing"}:
		if before and frappe.db.get_value("Lead", lead, STAGE) != before and _is_approved(before, settings):
			frappe.db.set_value("Lead", lead, STAGE, before, update_modified=False)
			st = status_for_stage(before, settings)
			if st and frappe.get_meta("Lead").has_field(STATUS):
				frappe.db.set_value("Lead", lead, STATUS, st, update_modified=False)
		auto.system_comment("Lead", lead, f"AlphaX: Quotation {doc.name} marked Lost; Lead stays open because {', '.join(others)} is still open.")
		auto.log_action("WF-06 Quotation marked Lost", lead, ("Quotation", doc.name), f"Lead kept at {before}: {', '.join(others)} still open")
		return
	target = (settings.get("lost_quotation_stage_value") or "Lost Quotation").strip()
	if doc.docstatus != 1 or doc.status != "Lost" or not ((doc.get("order_lost_reason") or "").strip() or any(r.get("lost_reason") for r in doc.get("lost_reasons") or [])
			or frappe.db.exists("Quotation Lost Reason Detail", {"parent": doc.name, "parenttype": "Quotation", "lost_reason": ["is", "set"]})):
		frappe.throw(_("A submitted Lost quotation with a reason is required."))
	who = doc.flags.get("alphax_confirmed_by")
	reason = _("{0} confirmed Lost Quotation for {1}").format(who, doc.name) if who else _("Quotation {0} was marked Lost").format(doc.name)
	set_stage_system(lead, target, reason, ("Quotation", doc.name),
		"WF-04 Lost Quotation confirmed" if who else "WF-06 Quotation marked Lost", from_stage=before)


def boot_session(bootinfo):
	"""Approved stages for the Lead form (dropdown filtering, Postponed prompt)."""
	if frappe.session.user == "Guest":
		return
	try:
		settings = get_settings()
		bootinfo.alphax_workflow = {
			"enabled": cint(settings.get("stage_flow_enabled", 1)),
			"stages": approved_stages(settings),
			"postponed": (settings.get("postponed_stage_value") or "Postponed").strip(),
			"lost_quotation": (settings.get("lost_quotation_stage_value") or "Lost Quotation").strip(),
			"require_next_contact": cint(settings.get("postponed_require_next_contact", 1)),
			"postponed_highlight": settings.get("postponed_highlight") or "Both",
		}
	except Exception:
		pass


@frappe.whitelist()
def lead_quotations(lead):
	"""Submitted quotations linked to the Lead (any of the three link paths) for the Confirm Lost dialog."""
	if not frappe.has_permission("Lead", "read", lead):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	rows = auto.quotations_for_lead(lead, {"docstatus": 1, "status": ["in", ["Open", "Replied", "Expired"]]},
		fields=("name", "valid_till", "grand_total", "currency", "status"))
	return [q for q in rows if frappe.has_permission("Quotation", "read", q.name)]
