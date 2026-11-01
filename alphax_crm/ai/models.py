"""AI Settings tools: open models guide, model discovery on the AI server, and the model self-test.

* get_catalogue(): the open models guide (licence, GPU size, Arabic quality, what it suits) and presets.
* list_server_models(): reads the models installed on an Ollama / vLLM / OpenAI-compatible server and
  labels the ones the guide knows, so nobody types model names by hand.
* run_self_test(): four checks with the prompts AlphaX really uses (one in Arabic):
    1. Structured JSON  - lead qualification answered in the required JSON shape (essential)
    2. Arabic spelling  - finds and fixes Arabic typos as JSON corrections
    3. Ask AI planner   - picks the right capability (AlphaX's tool call) for an English question
    4. Arabic request   - the same planner decision for a question asked in Arabic
  Passed = 4/4. Failed = check 1 failed or nothing passed. Otherwise Partial.
  A main model that Failed is kept away from automatic AI (lead classification, next best action,
  intent detection, quotation reminders, follow-up sequences, Ask AI planning); a Fast Model that Failed
  is not used (the main model takes over). Changing the server address or model resets the result.
"""

from __future__ import annotations

import time

import frappe
import requests
from frappe import _
from frappe.utils import cint, now_datetime

from alphax_crm.ai import catalogue

STATUS_FIELDS = {
	"main": ("ai_model", "ai_selftest_status", "ai_selftest_details", "ai_selftest_on", "ai_selftest_fingerprint"),
	"fast": ("ai_fast_model", "ai_fast_selftest_status", "ai_fast_selftest_details", "ai_fast_selftest_on",
		"ai_fast_selftest_fingerprint"),
}

QUALIFY_SYSTEM = (
	"You are a B2B sales qualification assistant for a Saudi/GCC software vendor. Classify the lead. "
	'Respond ONLY with JSON: {"fit": "High|Medium|Low", "urgency": "High|Medium|Low", '
	'"intent": "one short phrase", "summary": "one sentence"}.'
)
QUALIFY_SCHEMA = {
	"type": "object",
	"properties": {
		"fit": {"type": "string", "enum": ["High", "Medium", "Low"]},
		"urgency": {"type": "string", "enum": ["High", "Medium", "Low"]},
		"intent": {"type": "string"}, "summary": {"type": "string"},
	},
	"required": ["fit", "urgency", "intent", "summary"],
}
QUALIFY_LEAD = ("Company: Al Noor Trading (retail, 12 branches in Riyadh and Jeddah)\nSource: Website form\n"
	"Message: We need a ZATCA-ready POS for all branches before the end of the quarter. Please send prices.")
ARABIC_TYPO_TEXT = "نرجو من الشركه ارسال اسعار الصيانة الى المسؤل عن المشتريات"
PLANNER_EN = "How many leads do we have by source?"
PLANNER_AR = "كم عدد العملاء المحتملين حسب المصدر؟"


def _only_admin():
	frappe.only_for("System Manager")  # discovery calls an address typed in the form


# ------------------------------------------------------------------------------------------- guide
@frappe.whitelist()
def get_catalogue():
	settings = frappe.get_single("AlphaX CRM Settings")
	models = [{k: v for k, v in m.items() if k != "patterns"} | {"use_label": catalogue.USE_LABELS[m["use"]]}
		for m in catalogue.MODELS]
	return {
		"models": models,
		"uses": catalogue.USE_LABELS,
		"presets": catalogue.PRESETS,
		"current": {
			"main": catalogue.describe(settings.ai_model or "", settings.ai_base_url or ""),
			"fast": catalogue.describe(settings.get("ai_fast_model") or "", settings.ai_base_url or ""),
		},
	}


@frappe.whitelist()
def describe_model(model=None, base_url=None):
	return catalogue.describe(model or "", base_url or "")


# ------------------------------------------------------------------------------------------- discovery
@frappe.whitelist(methods=["POST"])
def list_server_models(base_url=None, provider=None):
	"""Models installed on the AI server typed in the form (not yet saved is fine)."""
	_only_admin()
	from alphax_crm.crm.utils import ai_request_headers

	settings = frappe.get_single("AlphaX CRM Settings")
	base_url = (base_url or settings.ai_base_url or "").strip()
	provider = provider or settings.get("ai_provider") or "Ollama"
	if not base_url.lower().startswith(("http://", "https://")):
		frappe.throw(_("Enter the AI Base URL first (http:// or https://)."))
	url = catalogue.models_url(base_url, provider)
	# the saved API key / Cloudflare token only go to the server they were saved for
	same_host = catalogue.host_of(base_url) == catalogue.host_of(settings.ai_base_url or "")
	headers = ai_request_headers(settings) if same_host else {"Content-Type": "application/json"}
	try:
		resp = requests.get(url, headers=headers, timeout=20)
	except requests.RequestException as e:
		return {"ok": False, "url": url, "message": _("Could not reach {0}: {1}").format(url, str(e)[:200]), "models": []}
	if resp.status_code in (401, 403):
		return {"ok": False, "url": url, "models": [], "message": _("The server refused the request ({0}). Save the API Key "
			"for this server first, then try again.").format(resp.status_code)}
	if resp.status_code >= 400:
		return {"ok": False, "url": url, "models": [], "message": _("The server answered {0} at {1}. Check the provider "
			"type (Ollama or OpenAI-compatible) and the address.").format(resp.status_code, url)}
	try:
		names = catalogue.parse_models(resp.json())
	except ValueError:
		names = []
	rows = [catalogue.describe(n, base_url) for n in names]
	rows.sort(key=lambda r: (r["known"] is None, r["model"].lower()))
	return {"ok": True, "url": url, "models": rows, "message": _("{0} model(s) on the server, {1} in the guide.").format(
		len(rows), sum(1 for r in rows if r["known"]))}


# ------------------------------------------------------------------------------------------- self-test
def _check(name, fn):
	started = time.monotonic()
	try:
		ok, detail = fn()
	except Exception as e:  # an AI error is a failed check, not a crash
		ok, detail = False, str(e)[:200]
	return {"name": name, "ok": bool(ok), "detail": detail, "seconds": round(time.monotonic() - started, 1)}


def self_test_checks(model):
	"""Run the four checks against `model` on the configured server. Returns a list of check dicts."""
	from alphax_crm.ai.engine import complete_json
	from alphax_crm.ai.writing import SPELL_PROMPT, SPELL_SCHEMA
	from alphax_crm.api.ai_query import _plan_prompt

	kw = {"model": model, "feature": "model_self_test", "temperature": 0, "timeout": 90, "max_tokens": 600}

	def structured():
		d = complete_json(QUALIFY_SYSTEM, QUALIFY_LEAD, schema=QUALIFY_SCHEMA, **kw)
		ok = isinstance(d, dict) and d.get("fit") in ("High", "Medium", "Low") and d.get("urgency") in ("High", "Medium", "Low") \
			and bool(d.get("summary"))
		return ok, f"fit={d.get('fit')}, urgency={d.get('urgency')}" if isinstance(d, dict) else "not an object"

	def arabic_spelling():
		d = complete_json(SPELL_PROMPT, "Text to check:\n<<<\n" + ARABIC_TYPO_TEXT + "\n>>>", schema=SPELL_SCHEMA, **kw)
		fixes = {(c.get("original") or "").strip(): (c.get("corrected") or "").strip()
			for c in (d or {}).get("changes") or [] if isinstance(c, dict)}
		ok = fixes.get("الشركه") == "الشركة"
		return ok, ", ".join(f"{a} → {b}" for a, b in fixes.items())[:200] or "no corrections"

	def planner(question):
		def run():
			system, user = _plan_prompt(question, None)
			d = complete_json(system, user, **kw)
			params = (d or {}).get("params") or {}
			ok = d.get("capability") == "aggregate" and str(params.get("doctype", "")).lower() == "lead" \
				and "source" in str(params.get("group_by", "")).lower()
			return ok, f"capability={d.get('capability')}, params={params}"[:200]
		return run

	return [
		_check("Structured JSON", structured),
		_check("Arabic spelling", arabic_spelling),
		_check("Ask AI planner (tool choice)", planner(PLANNER_EN)),
		_check("Arabic request (tool choice)", planner(PLANNER_AR)),
	]


@frappe.whitelist(methods=["POST"])
def run_self_test(target="main"):
	"""Test the saved main model or Fast Model and store the verdict on AlphaX CRM Settings."""
	_only_admin()
	if target not in STATUS_FIELDS:
		frappe.throw(_("Unknown target"))
	settings = frappe.get_single("AlphaX CRM Settings")
	if not cint(settings.ai_enabled):
		frappe.throw(_("Enable AI Assist and save the settings first."))
	model_f, status_f, details_f, on_f, fp_f = STATUS_FIELDS[target]
	model = (settings.get(model_f) or "").strip()
	if not model:
		frappe.throw(_("Fill in the model name and save first."))
	checks = self_test_checks(model)
	verdict = catalogue.grade(checks)
	from alphax_crm.ai.engine import provider

	values = {
		status_f: verdict,
		details_f: "\n".join(f"{'✓' if c['ok'] else '✗'} {c['name']} ({c['seconds']} s): {c['detail']}" for c in checks),
		on_f: now_datetime(),
		fp_f: catalogue.fingerprint(provider(settings), settings.ai_base_url, settings.ai_chat_path, model),
	}
	for k, v in values.items():
		frappe.db.set_single_value("AlphaX CRM Settings", k, v)
	frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")
	return {"model": model, "status": verdict, "checks": checks}


def status_of(settings, target="main") -> str:
	"""Stored verdict, but only while it still belongs to the configured server + model."""
	from alphax_crm.ai.engine import provider

	model_f, status_f, _d, _o, fp_f = STATUS_FIELDS[target]
	model = settings.get(model_f)
	if not model:
		return "Not tested"
	fp = catalogue.fingerprint(provider(settings), settings.get("ai_base_url"), settings.get("ai_chat_path"), model)
	if settings.get(fp_f) != fp:
		return "Not tested"
	return settings.get(status_f) or "Not tested"
