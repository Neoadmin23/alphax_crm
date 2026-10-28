"""AlphaX CRM health check: verifies configuration, data and runtime against the approved
Lead workflow spec (A, B WF-01..07, C). Run from AlphaX CRM Settings > Health Check, or
bench --site SITE execute alphax_crm.crm.health.run_health_check
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

from alphax_crm.crm import workflow
from alphax_crm.crm.utils import ensure_select_option, get_settings

SPEC_TRANSITIONS = [
	("Lead", "Interested"), ("Interested", "Qualified lead"), ("Qualified lead", "Quotation"),
	("Quotation", "Postponed"), ("Quotation", "Contract Under Signing"), ("Quotation", "Lost Quotation"),
	("Postponed", "Won"), ("Postponed", "Lost with reason"), ("Postponed", "Lost Quotation"),
	("Contract Under Signing", "Won"), ("Contract Under Signing", "Lost with reason"), ("Contract Under Signing", "Lost Quotation"),
]
REQUIRED_LEAD_FIELDS = {
	"custom_lead_status": "Lead Status (spec A mapping)",
	"custom_contract": "Contract (WF-06 Won)",
	"won_or_lost_date": "Won/Lost Date (WF-06)",
	"lost_reason": "Lost Reason (WF-06)",
	"detailed_reason": "Detailed Reason (WF-06)",
	"alphax_next_contact_date": "Next Contact Date (WF-05 Postponed)",
}


def _c(area, title, status, detail="", fix=None, count=None):
	return {"area": area, "title": title, "status": status, "detail": detail, "fix": fix, "count": count}


@frappe.whitelist()
def run_health_check():
	frappe.only_for(("System Manager", "Sales Manager"))
	settings = get_settings()
	checks = []
	for fn in (_runtime, _configuration, _data, _ai):
		try:
			checks += fn(settings)
		except Exception as e:
			checks.append(_c(fn.__name__.strip("_").title(), _("Check failed to run"), "fail", str(e)[:300]))
	summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "fail")}
	return {"summary": summary, "checks": checks, "ran_on": str(now_datetime())}


# ------------------------------------------------------------------------------- runtime
def _runtime(settings):
	out = []
	from frappe.utils.scheduler import is_scheduler_disabled

	out.append(_c("Runtime", _("Scheduler"), "fail" if is_scheduler_disabled() else "ok",
		_("Scheduled reminders will not run. Enable with: bench --site SITE enable-scheduler")
		if is_scheduler_disabled() else _("Enabled")))
	try:
		from frappe.utils.background_jobs import get_workers

		n = len(get_workers())
		out.append(_c("Runtime", _("Background workers"), "ok" if n else "fail", _("{0} running").format(n)))
	except Exception:
		out.append(_c("Runtime", _("Background workers"), "warn", _("Could not read the worker list")))
	tz = frappe.db.get_single_value("System Settings", "time_zone")
	out.append(_c("Runtime", _("Time zone"), "ok" if tz == "Asia/Riyadh" else "warn",
		tz if tz == "Asia/Riyadh" else _("{0}: daily rules run at 08:00 of this time zone; the spec expects Asia/Riyadh.").format(tz or "-")))
	jobs = {"alphax_crm.crm.workflow.daily_0800": "WF-04/05 daily 08:00", "alphax_crm.crm.automation.flush_outbox": "outbox",
		"alphax_crm.crm.workflow.wf02_hourly": "WF-02 hourly"}
	missing = [label for method, label in jobs.items() if not frappe.db.exists("Scheduled Job Type", {"method": method})]
	out.append(_c("Runtime", _("Scheduled jobs registered"), "fail" if missing else "ok",
		_("Missing: {0}. Run bench migrate.").format(", ".join(missing)) if missing else _("All registered")))
	email = frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name")
	out.append(_c("Runtime", _("Outgoing email account"), "ok" if email else "fail",
		email or _("No default outgoing Email Account: notifications go in-app only (spec C requires email).")))
	stuck = frappe.db.count("AlphaX Automation Log", {"status": "Queued", "send_after": ["<", add_days(now_datetime(), -1)]})
	failed = frappe.db.count("AlphaX Automation Log", {"status": ["in", ["Failed", "Partly Sent"]], "creation": [">", add_days(now_datetime(), -7)]})
	out.append(_c("Runtime", _("Notification outbox"), "warn" if stuck or failed else "ok",
		_("{0} queued for over a day, {1} failed or partly sent in 7 days (see AlphaX Automation Log)").format(stuck, failed),
		count=stuck + failed))
	errors = frappe.db.count("Error Log", {"method": ["like", "AlphaX%"], "creation": [">", add_days(now_datetime(), -1)]})
	out.append(_c("Runtime", _("AlphaX errors (24h)"), "warn" if errors else "ok", _("{0} in Error Log").format(errors), count=errors))
	return out


# ------------------------------------------------------------------------------- configuration
def _configuration(settings):
	out = []
	meta = frappe.get_meta("Lead")
	for field, label in REQUIRED_LEAD_FIELDS.items():
		has = meta.has_field(field)
		out.append(_c("Configuration", _("Lead field: {0}").format(label), "ok" if has else "fail",
			field if has else _("Field {0} is missing on Lead (add it with Customize Form)").format(field)))

	stages = workflow.approved_stages(settings)
	options = [o.strip() for o in (meta.get_field("status").options or "").split("\n") if o.strip()]
	missing = [s for s in stages if s not in options]
	out.append(_c("Configuration", _("Lead Stage options"), "fail" if missing else "ok",
		_("Missing options: {0}").format(", ".join(missing)) if missing else _("All approved stages selectable"),
		fix="stage_options" if missing else None))
	if meta.has_field("custom_lead_status"):
		st_opts = [o.strip() for o in (meta.get_field("custom_lead_status").options or "").split("\n") if o.strip()]
		need = sorted({st for _s, st in workflow.stage_map(settings)} - set(st_opts))
		out.append(_c("Configuration", _("Lead Status options"), "fail" if need else "ok",
			_("Missing: {0}").format(", ".join(need)) if need else _("OK"), fix="status_options" if need else None))

	current = [(s.lower(), st.lower()) for s, st in workflow.stage_map(settings)]
	spec = [(s.lower(), st.lower()) for s, st in workflow.SPEC_STAGE_MAP]
	diff = [f"{s} → {st}" for s, st in workflow.SPEC_STAGE_MAP if (s.lower(), st.lower()) not in current]
	extra = [f"{s} → {st}" for s, st in workflow.stage_map(settings) if (s.lower(), st.lower()) not in spec]
	out.append(_c("Configuration", _("Stage ↔ Status mapping (spec A)"), "warn" if diff or extra else "ok",
		(_("Missing: {0}").format("; ".join(diff)) if diff else "") + (_(" Not in spec: {0}").format("; ".join(extra)) if extra else "")
		or _("Matches the approved mapping"), fix="stage_map" if diff or extra else None))

	have = {((t.from_stage or "").lower(), (t.to_stage or "").lower()) for t in settings.get("stage_transitions") or []}
	miss_t = [f"{a} → {b}" for a, b in SPEC_TRANSITIONS if (a.lower(), b.lower()) not in have]
	out.append(_c("Configuration", _("Approved transitions (WF-01)"), "warn" if miss_t else "ok",
		_("Missing: {0}").format("; ".join(miss_t)) if miss_t else _("{0} transitions").format(len(have)),
		fix="transitions" if miss_t else None))
	out.append(_c("Configuration", _("Stage control enabled (WF-01)"), "ok" if cint(settings.get("stage_flow_enabled", 1)) else "fail",
		_("Bypass roles: {0}").format(settings.get("stage_flow_bypass_roles") or "-")))
	out.append(_c("Configuration", _("Stage protection from ERPNext core"), "ok" if cint(settings.get("protect_lead_stage", 1)) else "warn",
		_("Without it, a submitted quotation or a new Customer silently resets the Lead Stage")))

	sla_stages = {(r.stage or "").lower() for r in settings.get("stage_sla_rules") or []}
	miss_s = [s for s in ("Lead", "Interested", "Qualified lead", "Contract Under Signing") if s.lower() not in sla_stages]
	out.append(_c("Configuration", _("SLA rules (WF-05)"), "warn" if miss_s else "ok",
		_("No rules for: {0}").format(", ".join(miss_s)) if miss_s else _("{0} rules").format(len(settings.get("stage_sla_rules") or [])),
		fix="sla" if miss_s else None))
	approvers = [u for u in workflow.auto.approvers(settings) if frappe.db.get_value("User", u, "email")]
	out.append(_c("Configuration", _("Approvers ({0} role)").format(settings.get("approver_role") or "Sales Manager"),
		"ok" if approvers else "fail", ", ".join(approvers[:6]) or _("No enabled users: escalations have no recipient")))
	cal = workflow.auto.calendar(settings)
	days = ", ".join(workflow.auto.WEEKDAYS[d] for d in sorted(cal.days, key=lambda d: (d + 1) % 7))
	out.append(_c("Configuration", _("Working days & hours (spec C)"), "ok" if cal.days else "fail",
		f"{days}, {cal.start:%H:%M}–{cal.end:%H:%M}; {cal.mode}"))
	out.append(_c("Configuration", _("Public holidays"), "ok" if settings.get("holiday_list") else "warn",
		settings.get("holiday_list") or _("No Holiday List: Eid and National Day count as working days")))
	wf = frappe.db.get_value("Workflow", {"document_type": "Lead", "is_active": 1}, "name")
	paused_state = wf and frappe.db.exists("Workflow Document State", {"parent": wf, "state": "Returned for Correction"})
	out.append(_c("Configuration", _("'Returned for Correction' pause"), "ok" if paused_state else "warn",
		_("Workflow {0}").format(wf) if paused_state else _("No active Lead workflow with that state")))
	for flag, label in (("wf_quotation_check_enabled", "WF-02 quotation check"), ("wf03_confirmation_enabled", "WF-03 confirmation"),
			("wf03_require_valid_till", "WF-03 Valid Till mandatory"), ("wf04_enabled", "WF-04 validity follow-up"),
			("stage_sla_enabled", "WF-05 SLA"), ("closure_controls_enabled", "WF-06 closure controls"),
			("notify_by_email", "Email notifications"), ("business_hours_only", "Business hours only")):
		on = cint(settings.get(flag, 1))
		out.append(_c("Configuration", _(label), "ok" if on else "warn", _("On") if on else _("Off")))
	return out


# ------------------------------------------------------------------------------- data
def _data(settings):
	out = []
	stages = workflow.approved_stages(settings)
	bad = frappe.db.sql("select status, count(*) from `tabLead` where status not in %(s)s group by status", {"s": stages or [""]})
	n = sum(r[1] for r in bad)
	out.append(_c("Data", _("Leads in non-approved stages"), "warn" if n else "ok",
		", ".join(f"{r[0]}: {r[1]}" for r in bad) or _("None"), count=n))
	q_leads = frappe.get_all("Lead", filters={"status": "Quotation"}, pluck="name", limit=2000)
	no_q = [l for l in q_leads if not workflow.auto.quotations_for_lead(l, {"docstatus": ["<", 2]})]
	out.append(_c("Data", _("At Quotation without a quotation (WF-02)"), "warn" if no_q else "ok",
		", ".join(no_q[:10]) or _("None"), count=len(no_q)))
	meta = frappe.get_meta("Lead")
	won = settings.get("won_stage_value") or "Won"
	cond = []
	if meta.has_field("custom_contract"):
		cond.append("ifnull(custom_contract,'') != %(signed)s")
	if meta.has_field("won_or_lost_date"):
		cond.append("won_or_lost_date is null")
	cnt = 0
	if cond:
		cnt = frappe.db.sql(f"select count(*) from `tabLead` where status=%(won)s and ({' or '.join(cond)})",
			{"won": won, "signed": settings.get("contract_signed_value") or "Signed"})[0][0]
	out.append(_c("Data", _("Won leads missing closure data (WF-06)"), "warn" if cnt else "ok", _("{0} leads").format(cnt), count=cnt))
	lq = settings.get("lost_quotation_stage_value") or "Lost Quotation"
	lq_leads = frappe.get_all("Lead", filters={"status": lq}, pluck="name", limit=2000)
	bad_lq = [l for l in lq_leads if not workflow.auto.quotations_for_lead(l, {"docstatus": 1, "status": "Lost"})]
	out.append(_c("Data", _("Lost Quotation without a lost quotation (WF-06)"), "warn" if bad_lq else "ok",
		", ".join(bad_lq[:10]) or _("None"), count=len(bad_lq)))
	pp = settings.get("postponed_stage_value") or "Postponed"
	no_date = frappe.db.count("Lead", {"status": pp, "alphax_next_contact_date": ["is", "not set"]}) if meta.has_field("alphax_next_contact_date") else 0
	out.append(_c("Data", _("Postponed without Next Contact Date (WF-05)"), "warn" if no_date else "ok", _("{0} leads").format(no_date), count=no_date))
	no_vt = frappe.db.count("Quotation", {"docstatus": 1, "quotation_to": "Lead", "valid_till": ["is", "not set"]})
	out.append(_c("Data", _("Lead quotations without Valid Till (WF-03)"), "warn" if no_vt else "ok", _("{0} quotations").format(no_vt), count=no_vt))
	return out


# ------------------------------------------------------------------------------- AI
def _ai(settings):
	out = []
	if not cint(settings.ai_enabled):
		return [_c("AI (WF-07)", _("AI Assist"), "warn", _("Off: lead brief, intent detection, drafts and next action are unavailable"))]
	from alphax_crm.ai import engine

	try:
		engine.complete("You are a connection test.", "Reply OK", feature="health_check", max_tokens=10, timeout=20)
		out.append(_c("AI (WF-07)", _("AI server"), "ok", f"{engine.provider(settings)} · {engine.chat_url(settings)} · {settings.ai_model}"))
	except engine.AIError as e:
		out.append(_c("AI (WF-07)", _("AI server"), "fail", str(e)[:300]))
	out.append(_c("AI (WF-07)", _("Intent detection on inbound emails"), "ok" if cint(settings.get("ai_intent_detection", 1)) else "warn",
		_("On") if cint(settings.get("ai_intent_detection", 1)) else _("Off")))
	out.append(_c("AI (WF-07)", _("AI write limits (spec C)"), "ok" if not cint(settings.get("ai_next_action_todo")) else "warn",
		_("AI writes only AI fields, timeline notes, notifications and drafts") if not cint(settings.get("ai_next_action_todo"))
		else _("'Create a ToDo for the Lead Owner' is on: the AI also writes ToDos")))
	return out


# ------------------------------------------------------------------------------- fixes
@frappe.whitelist(methods=["POST"])
def apply_fix(fix):
	frappe.only_for("System Manager")
	settings = frappe.get_single("AlphaX CRM Settings")
	if fix == "stage_options":
		for s in workflow.approved_stages(settings):
			ensure_select_option("Lead", "status", s, clear_cache=False)
		frappe.clear_cache(doctype="Lead")
	elif fix == "status_options":
		for _s, st in workflow.stage_map(settings):
			ensure_select_option("Lead", "custom_lead_status", st, clear_cache=False)
		frappe.clear_cache(doctype="Lead")
	elif fix == "stage_map":
		settings.set("lead_stage_map", [{"lead_stage": s, "lead_status": st} for s, st in workflow.SPEC_STAGE_MAP])
		settings.save()
	elif fix == "transitions":
		have = {((t.from_stage or "").lower(), (t.to_stage or "").lower()) for t in settings.stage_transitions}
		for a, b in SPEC_TRANSITIONS:
			if (a.lower(), b.lower()) not in have:
				settings.append("stage_transitions", {"from_stage": a, "to_stage": b})
		settings.save()
	elif fix == "sla":
		from alphax_crm.setup.install import _default_stage_sla_rules

		have = {(r.stage or "").lower() for r in settings.stage_sla_rules}
		for row in _default_stage_sla_rules():
			if row[0].lower() not in have:
				settings.append("stage_sla_rules", dict(zip(("stage", "days", "notify", "require_no_activity", "label",
					"repeat_every_days"), row)))
		settings.save()
	else:
		frappe.throw(_("Unknown fix {0}").format(fix))
	return run_health_check()
