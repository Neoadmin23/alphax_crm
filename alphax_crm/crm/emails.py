"""Every email/notification AlphaX sends, with its wording kept in the front end.

Each rule below has an Email Template ("AlphaX - <rule>", Settings > Email Template) that holds the
subject and body, and a row in AlphaX CRM Settings > 1. General > 1.2 Emails & Notifications where it
can be switched off, sent in-app only, or pointed at another template. The texts here are only the
first version, created once on install/migrate; edits made in the front end are never overwritten.

Templates are Jinja: {{ lead.lead_name }}, {{ quotation.grand_total }}, {{ link }} and the variables
listed for each rule. If a template is broken, the built-in wording below is used and the error is
written to the Error Log, so a typo never stops a reminder.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_url_to_form

PREFIX = "AlphaX - "
CHILD_DT = "AlphaX Email Rule"
TABLE = "email_rules"

COMMON_VARS = "lead (all Lead fields), lead_name, quotation (all Quotation fields, when there is one), link"
QUOTATION_VARS = "quotation_no, quotation_date, valid_till, amount, party"

_QUOTATION_TABLE = (
	"<p><strong>Quotation No.:</strong> {{ quotation_no }}<br>"
	"<strong>Date:</strong> {{ quotation_date }}<br>"
	"<strong>Valid Till:</strong> {{ valid_till }}<br>"
	"<strong>Amount:</strong> {{ amount }}<br>"
	"<strong>Lead / Company:</strong> {{ party }}{% if lead %} ({{ lead.name }}){% endif %}</p>"
)
_OPEN = '<p><a href="{{ link }}">Open {{ link_label }}</a></p>'

# key (stored on the Automation Log as the rule), who gets it, when, send by email by default,
# subject, body, extra variables
RULES = [
	dict(key="New lead", to="Lead Owner", when="A new lead is created (sent in business hours)", email=1,
		subject="New lead {{ lead_name }} (score {{ score }})",
		body="<p>A new lead has been captured and assigned to you.</p>"
			"<p><strong>Name:</strong> {{ lead_name }}<br><strong>Source:</strong> {{ source }}<br>"
			"<strong>Score:</strong> {{ score }}</p><p>Respond quickly: speed-to-lead drives conversion.</p>" + _OPEN,
		vars="source, score"),
	dict(key="Follow-up due", to="Lead Owner", when="The Lead's Next Contact Date is reached (08:00, working days)", email=1,
		subject="Follow-up due for {{ lead_name }}",
		body="<p>The Next Contact Date for Lead {{ lead.name }} ({{ lead_name }}) is {{ due }}.</p>" + _OPEN,
		vars="due"),
	dict(key="WF-02 Quotation created", to="Approvers (Sales Managers)", when="An agent creates a quotation", email=1,
		subject="Quotation {{ quotation_no }} created by {{ created_by }}",
		body=_QUOTATION_TABLE + _OPEN, vars=QUOTATION_VARS + ", created_by"),
	dict(key="WF-02 Quotation submitted", to="Approvers (Sales Managers)", when="A quotation is submitted", email=1,
		subject="Quotation {{ quotation_no }} submitted",
		body=_QUOTATION_TABLE + _OPEN, vars=QUOTATION_VARS),
	dict(key="WF-03 Quotation confirmation", to="Quotation creator + Lead Owner", when="A quotation is submitted", email=1,
		subject="Your quotation has been created successfully",
		body=_QUOTATION_TABLE + _OPEN, vars=QUOTATION_VARS),
	dict(key="WF-02 No quotation (alert)", to="Lead Owner + assigned users", when="A Lead moves to stage Quotation with no quotation linked",
		email=1, subject="Create the quotation for Lead {{ lead.name }}",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) is at stage Quotation but no Quotation is linked to it.</p>" + _OPEN,
		vars=""),
	dict(key="WF-02 No quotation (reminder)", to="Lead Owner + assigned users", when="Still no quotation after the reminder hours (default 24 working hours)",
		email=1, subject="Reminder: no quotation for Lead {{ lead.name }} yet",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) is at stage Quotation but no Quotation is linked to it.</p>" + _OPEN,
		vars="hours"),
	dict(key="WF-02 No quotation (escalation)", to="Approvers + Lead Owner + assigned users", when="Still no quotation after the escalation hours (default 72 working hours)",
		email=1, subject="Escalation: no quotation for Lead {{ lead.name }} after {{ hours }} working hours",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) is at stage Quotation but no Quotation is linked to it.</p>" + _OPEN,
		vars="hours"),
	dict(key="WF-04 Validity notice", to="Lead Owner", when="Quotation expires in 2 working days and there was follow-up", email=1,
		subject="Quotation {{ quotation_no }} is valid until {{ valid_till }}",
		body="<p>Quotation {{ quotation_no }} expires on {{ valid_till }}. Recent activity: {{ activity }}.</p>" + _OPEN,
		vars=QUOTATION_VARS + ", activity"),
	dict(key="WF-04 Expiring, no activity (reminder)", to="Lead Owner", when="Quotation expires in 2 working days with no follow-up", email=1,
		subject="Follow up on Quotation {{ quotation_no }} (expires {{ valid_till }})",
		body="<p>Quotation {{ quotation_no }} expires on {{ valid_till }} and there has been no follow-up since it was issued.</p>"
			"{% if ai_draft %}<p>An AI-drafted follow-up email is ready for your review: {{ ai_draft }} "
			"(it is not sent until you approve it).</p>{% endif %}" + _OPEN,
		vars=QUOTATION_VARS + ", ai_draft"),
	dict(key="WF-04 Valid Till reached, no activity", to="Lead Owner + Approvers", when="Valid Till date reached with no activity", email=1,
		subject="Quotation {{ quotation_no }} expires today with no follow-up",
		body="<p>Quotation {{ quotation_no }} reaches its Valid Till date ({{ valid_till }}) with no activity since it was issued. "
			"Please extend it, postpone the Lead, or mark it as lost.</p>" + _OPEN,
		vars=QUOTATION_VARS),
	dict(key="WF-04 Expired, no action (escalation)", to="Lead Owner + Approvers", when="Quotation expired some days ago and nothing was done",
		email=1, subject="Quotation {{ quotation_no }} expired {{ days_expired }} days ago: confirm Lost Quotation?",
		body="<p>Quotation {{ quotation_no }} expired on {{ valid_till }} and nothing was done. Proposed action: mark it as "
			"<strong>Lost Quotation</strong>. The Lead Owner confirms with the Confirm Lost Quotation button on the Lead or "
			"Quotation.</p>" + _OPEN,
		vars=QUOTATION_VARS + ", days_expired"),
	dict(key="WF-04 Lost quotation digest", to="Approvers (Sales Managers)", when="Daily at 08:00 on working days, when there are lost quotations",
		email=1, subject="Lost quotations follow-up: {{ new_count }} new, {{ total }} total",
		body="<p><strong>New since last working day: {{ new_count }}</strong></p>{{ new_leads_html }}"
			"<p><strong>All leads at Lost Quotation: {{ total }}</strong></p>"
			"{% if top_reasons %}<p>Top reasons: {{ top_reasons }}</p>{% endif %}",
		vars="new_count, total, new_leads_html, new_leads (list), top_reasons"),
	dict(key="WF-05 Stage SLA", to="As set per rule in 4. Stages & Follow-up (Lead Owner / Approver / Both)",
		when="Each Stage SLA rule (days in stage), daily 08:00", email=1,
		subject="AlphaX SLA: {{ label }} — {{ lead.name }}",
		body='<p>Lead {{ lead.name }} ({{ lead_name }}) has been at stage "{{ stage }}" for {{ days }} day(s)'
			"{% if no_activity %} with no recorded activity{% endif %}.</p>" + _OPEN,
		vars="label, stage, days, no_activity"),
	dict(key="WF-05 Postponed follow-up", to="Lead Owner", when="A Postponed Lead's follow-up date is reached", email=1,
		subject="Postponed Lead {{ lead.name }} is due for follow-up ({{ due }})",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) was postponed to {{ due }}.</p>" + _OPEN, vars="due"),
	dict(key="WF-05 Postponed overdue (approvers)", to="Lead Owner + Approvers", when="A Postponed Lead is overdue with no activity", email=1,
		subject="Postponed Lead {{ lead.name }} overdue with no activity",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) was due on {{ due }} and no comment or activity has been added since.</p>" + _OPEN,
		vars="due"),
	dict(key="WF-05 Expected closing passed", to="Lead Owner + Approvers", when="Contract Under Signing and the Expected Closing Date has passed",
		email=1, subject="Contract for Lead {{ lead.name }} not signed: expected closing {{ closing_date }} has passed",
		body="<p>Lead {{ lead.name }} ({{ lead_name }}) is still at Contract Under Signing; the Expected Closing Date was "
			"{{ closing_date }}.</p>" + _OPEN,
		vars="closing_date"),
	dict(key="WF-07 AI next best action", to="Lead Owner", when="The AI suggests a next action (when AI To Do is off)", email=0,
		subject="AI next best action for {{ lead.name }}",
		body="<p>{{ action }}</p>" + _OPEN, vars="action"),
	dict(key="WF-07 AI intent detected", to="Lead Owner", when="The AI reads a client email and detects its intent", email=0,
		subject="Client email on {{ lead.name }}: {{ intent }}",
		body="<p>{{ detail }}</p>{% if suggested_stage %}<p>Suggested stage: <strong>{{ suggested_stage }}</strong>. Open the "
			'Lead and use "Apply Suggested Stage" to confirm.</p>{% endif %}' + _OPEN,
		vars="intent, detail, suggested_stage"),
]
RULE_MAP = {r["key"]: r for r in RULES}


def template_name(key):
	return PREFIX + key


# ============================================================================ seeding (install / migrate)
def seed():
	"""Create the missing Email Templates and settings rows. Never changes what the admin edited."""
	if not frappe.db.exists("DocType", CHILD_DT):
		return
	frappe.clear_cache(doctype="AlphaX CRM Settings")
	if not frappe.get_meta("AlphaX CRM Settings").has_field(TABLE):
		return
	for rule in RULES:
		name = template_name(rule["key"])
		if not frappe.db.exists("Email Template", name):
			doc = frappe.new_doc("Email Template")
			doc.name = name
			doc.subject = rule["subject"]
			doc.response = rule["body"]
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
	settings = frappe.get_single("AlphaX CRM Settings")
	rows = {r.rule: r for r in settings.get(TABLE) or []}
	changed = False
	for rule in RULES:
		row = rows.get(rule["key"])
		if not row:
			row = settings.append(TABLE, {"rule": rule["key"], "enabled": 1, "send_email": rule["email"]})
			changed = True
		info = {"recipients": rule["to"], "trigger": rule["when"],
			"variables": ", ".join(v for v in (COMMON_VARS, rule["vars"]) if v)}
		for field, value in info.items():
			if row.get(field) != value:
				row.set(field, value)
				changed = True
		if not row.email_template or not frappe.db.exists("Email Template", row.email_template):
			row.email_template = template_name(rule["key"])
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)


# ============================================================================ rendering
def setting_for(key, settings=None):
	from alphax_crm.crm.utils import get_settings

	settings = settings or get_settings()
	for row in settings.get(TABLE) or []:
		if row.rule == key:
			return row
	return None


def quotation_context(doc, lead=None):
	"""The quotation variables every quotation email can use."""
	from frappe.utils import fmt_money, formatdate

	if isinstance(doc, str):
		doc = frappe.get_doc("Quotation", doc)
	party = (frappe.db.get_value("Lead", lead, "company_name") or frappe.db.get_value("Lead", lead, "lead_name")) if lead \
		else (doc.get("customer_name") or doc.get("party_name"))
	return {
		"quotation_no": doc.name,
		"quotation_date": formatdate(doc.transaction_date) if doc.get("transaction_date") else "-",
		"valid_till": formatdate(doc.valid_till) if doc.get("valid_till") else "-",
		"amount": fmt_money(doc.grand_total, currency=doc.currency),
		"party": party or "-",
	}


def _context(context, lead=None, reference=None):
	ctx = dict(context or {})
	if lead and "lead" not in ctx and frappe.db.exists("Lead", lead):
		ctx["lead"] = frappe.get_doc("Lead", lead).as_dict()
	ctx.setdefault("lead", None)
	if ctx["lead"]:
		ctx.setdefault("lead_name", ctx["lead"].get("lead_name") or ctx["lead"].get("name"))
	if reference and reference[0] == "Quotation" and "quotation" not in ctx and frappe.db.exists("Quotation", reference[1]):
		ctx["quotation"] = frappe.get_doc("Quotation", reference[1]).as_dict()
	ctx.setdefault("quotation", None)
	target = reference if reference and reference[1] else (("Lead", lead) if lead else None)
	ctx.setdefault("link", get_url_to_form(*target) if target else frappe.utils.get_url("/app"))
	ctx.setdefault("link_label", f"{_(target[0])} {target[1]}" if target else "AlphaX CRM")
	return ctx


def _render(src, ctx):
	return frappe.render_template(src or "", ctx).strip()


def build(key, context=None, lead=None, reference=None, settings=None):
	"""-> dict(enabled, email, subject, message) for a rule, or None if the key is not a known rule.
	`email` is None when the rule has no settings row (the caller's default applies)."""
	rule = RULE_MAP.get(key)
	if not rule:
		return None
	row = setting_for(key, settings)
	out = {"enabled": cint(row.enabled) if row else 1, "email": cint(row.send_email) if row else None}
	if not out["enabled"]:
		return out
	ctx = _context(context, lead, reference)
	subject_src, body_src = rule["subject"], rule["body"]
	tpl_name = (row.email_template if row else None) or template_name(key)
	if frappe.db.exists("Email Template", tpl_name):
		tpl = frappe.get_cached_doc("Email Template", tpl_name)
		subject_src = tpl.subject or subject_src
		body_src = (tpl.response_html if cint(tpl.use_html) else tpl.response) or body_src
	try:
		out["subject"], out["message"] = _render(subject_src, ctx), _render(body_src, ctx)
	except Exception:
		frappe.log_error(title=f"AlphaX: Email Template {tpl_name} could not be rendered", message=frappe.get_traceback())
		out["subject"], out["message"] = _render(rule["subject"], ctx), _render(rule["body"], ctx)
	out["subject"] = " ".join(out["subject"].split())[:140]
	return out


@frappe.whitelist()
def preview(rule):
	"""Front end: the template rendered with the latest Lead (and its quotation) as sample data."""
	frappe.only_for(("System Manager", "Sales Manager"))
	lead = frappe.get_all("Lead", pluck="name", order_by="creation desc", limit=1)
	lead = lead[0] if lead else None
	q = frappe.get_all("Quotation", filters={"docstatus": ("<", 2)}, pluck="name", order_by="creation desc", limit=1)
	ctx = {"score": 0, "source": "-", "due": frappe.utils.formatdate(frappe.utils.nowdate()), "hours": 24,
		"created_by": frappe.utils.get_fullname(), "activity": "email", "ai_draft": "", "days_expired": 3,
		"new_count": 1, "total": 3, "new_leads_html": "<ul><li>CRM-LEAD-0001 (Sample), owner you</li></ul>", "new_leads": [],
		"top_reasons": "Price (2)", "label": "First contact reminder", "stage": "Interested", "days": 3, "no_activity": 1,
		"closing_date": frappe.utils.formatdate(frappe.utils.nowdate()), "action": "Call the client to confirm the meeting.",
		"intent": "Interested", "detail": "Interested (80%) — sample", "suggested_stage": "Interested"}
	if lead:
		ctx.update(source=frappe.db.get_value("Lead", lead, "source") or "-",
			score=frappe.db.get_value("Lead", lead, "alphax_lead_score") or 0)
	uses_quotation = "quotation_no" in (RULE_MAP.get(rule) or {}).get("vars", "")
	if q and uses_quotation:
		ctx.update(quotation_context(q[0], lead))
	out = build(rule, ctx, lead=lead, reference=("Quotation", q[0]) if q and uses_quotation else None)
	if not out:
		frappe.throw(_("Unknown notification {0}").format(rule))
	return out
