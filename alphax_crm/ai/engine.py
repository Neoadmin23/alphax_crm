"""AlphaX AI engine: the single gateway for every model call AlphaX CRM makes.

    from alphax_crm.ai.engine import complete, complete_json
    text = complete(system, user, feature="lead_draft_reply", reference=("Lead", name))

What it adds on top of a plain HTTP call:

* Providers: Ollama (native /api/chat) and any OpenAI-compatible server
  (LocalAI, vLLM, LM Studio, an internal gateway) via /v1/chat/completions.
* Structured output: a JSON schema is passed to the server (Ollama `format`,
  OpenAI `response_format`) so small local models return valid JSON.
* Governance, checked before anything leaves the site:
    - KSA Data Residency Mode: only private-network hosts or hosts listed in
      "Allowed AI Hosts" are called.
    - Daily token budget across all users.
    - PII masking: emails and phone numbers are swapped for placeholders
      before the call and restored in the answer, so features such as
      translate still return the real values.
* AlphaX AI Log: one row per call (feature, user, record, model, status,
  tokens, latency, optional excerpts) with automatic retention.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils import add_days, cint, flt, now_datetime, nowdate

from alphax_crm.ai import pure
from alphax_crm.crm.utils import ai_request_headers, get_settings

LOG_DT = "AlphaX AI Log"
PROVIDERS = ("Ollama", "OpenAI Compatible")


class AIError(Exception):
	"""A failure the user should see as a clean message."""


class AIBlocked(AIError):
	"""Governance stopped the call before it was sent."""


# ----------------------------------------------------------------------------- settings
def provider(settings=None) -> str:
	settings = settings or get_settings()
	p = settings.get("ai_provider")
	if p in PROVIDERS:
		return p
	return "OpenAI Compatible" if "chat/completions" in (settings.ai_chat_path or "") else "Ollama"


def chat_url(settings=None) -> str:
	settings = settings or get_settings()
	base = (settings.ai_base_url or "http://localhost:11434").rstrip("/")
	path = (settings.ai_chat_path or "").strip()
	if provider(settings) == "OpenAI Compatible":
		if base.endswith("/chat/completions"):
			return base
		if not path or path == "/api/chat":
			path = "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
	elif not path:
		path = "/api/chat"
	return base + (path if path.startswith("/") else "/" + path)


def is_enabled() -> bool:
	try:
		return bool(cint(get_settings().ai_enabled))
	except Exception:
		return False


def language_instruction(language: str | None) -> str:
	if language == "Arabic":
		return ("Write the final output in Modern Standard Arabic suitable for Saudi business readers. "
			"Keep product names, company names, numbers and codes in their original form.")
	if language == "English":
		return "Write the final output in clear, professional English."
	return ""


# ----------------------------------------------------------------------------- public API
def complete(system: str, user: str, *, feature: str = "adhoc", reference=None, want_json=False,
		schema: dict | None = None, model: str | None = None, max_tokens: int | None = None,
		timeout: int | None = None, temperature: float | None = None) -> str:
	"""Call the configured model and return its text answer (governed + logged)."""
	settings = get_settings()
	log = _new_log(settings, feature, reference, model)
	started = time.monotonic()
	masks = {}
	try:
		_check_governance(settings)
		if cint(settings.get("ai_mask_pii")):
			system, masks = pure.mask_pii(system, masks)
			user, masks = pure.mask_pii(user, masks)
		if cint(settings.get("ai_log_excerpts")):
			log["request_excerpt"] = pure.truncate(f"[system]\n{system}\n\n[user]\n{user}", 4000)
		text, usage = _dispatch(settings, system, user, want_json or bool(schema), schema, model,
			max_tokens, timeout, temperature)
		text = pure.strip_thinking(text)
		if masks:
			text = pure.unmask(text, masks)
		log.update(status="Success", input_tokens=usage[0], output_tokens=usage[1])
		if cint(settings.get("ai_log_excerpts")):
			log["response_excerpt"] = pure.truncate(text, 4000)
		return text
	except AIBlocked as e:
		log.update(status="Blocked", error=str(e))
		raise
	except AIError as e:
		log.update(status="Failed", error=str(e))
		raise
	except requests.RequestException as e:
		log.update(status="Failed", error=str(e)[:500])
		raise AIError(_("Could not reach the AI server: {0}").format(str(e)[:300])) from e
	finally:
		log["latency_ms"] = int((time.monotonic() - started) * 1000)
		_write_log(settings, log)


def complete_json(system: str, user: str, *, schema: dict | None = None, **kwargs):
	"""complete() + robust JSON parsing (handles code fences and chatter)."""
	text = complete(system, user, want_json=True, schema=schema, **kwargs)
	try:
		return pure.extract_json(text)
	except ValueError as e:
		raise AIError(_("The AI model did not return valid JSON ({0}).").format(kwargs.get("feature", "adhoc"))) from e


# ----------------------------------------------------------------------------- governance
def _check_governance(settings):
	if not cint(settings.ai_enabled):
		raise AIBlocked(_("AI Assist is disabled. Enable it in AlphaX CRM Settings."))
	if cint(settings.get("ai_residency_mode")):
		host = urlparse(chat_url(settings)).hostname or ""
		allowed = (settings.get("ai_allowed_hosts") or "").splitlines()
		if not (pure.is_private_host(host) or pure.host_allowed(host, allowed)):
			raise AIBlocked(_("KSA Data Residency Mode is on: AI host {0} is not on a private network "
				"and not in Allowed AI Hosts.").format(host or "?"))
	budget = cint(settings.get("ai_daily_token_budget"))
	if budget > 0:
		used = flt(frappe.db.sql(
			f"select coalesce(sum(input_tokens + output_tokens), 0) from `tab{LOG_DT}` "
			"where creation >= %s and status = 'Success'", (nowdate(),))[0][0])
		if used >= budget:
			raise AIBlocked(_("Today's AI usage limit ({0} tokens) is used up. AI features resume tomorrow.")
				.format(budget))


# ----------------------------------------------------------------------------- providers
def _dispatch(settings, system, user, want_json, schema, model, max_tokens, timeout, temperature):
	messages = [m for m in ({"role": "system", "content": system}, {"role": "user", "content": user}) if m["content"]]
	model = model or settings.ai_model or "llama3.1"
	max_tokens = cint(max_tokens) or cint(settings.get("ai_max_output_tokens")) or 1500
	temperature = 0.2 if temperature is None else temperature
	timeout = cint(timeout) or cint(settings.ai_timeout) or 60
	headers = ai_request_headers(settings)
	url = chat_url(settings)

	if provider(settings) == "OpenAI Compatible":
		payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
		if cint(settings.get("ai_disable_thinking")):
			payload["reasoning_effort"] = "none"
		if schema:
			payload["response_format"] = {"type": "json_schema",
				"json_schema": {"name": "result", "strict": True, "schema": schema}}
		elif want_json:
			payload["response_format"] = {"type": "json_object"}
		data = _post(url, payload, headers, timeout, retry_without="response_format")
		choices = data.get("choices") or []
		if not choices:
			raise AIError(_("The AI server returned no answer."))
		text = (choices[0].get("message") or {}).get("content") or ""
		usage = data.get("usage") or {}
		return text, (cint(usage.get("prompt_tokens")), cint(usage.get("completion_tokens")))

	payload = {"model": model, "messages": messages, "stream": False,
		"options": {"temperature": temperature, "num_predict": max_tokens}}
	if schema:
		payload["format"] = schema  # Ollama >= 0.5 accepts a JSON schema here
	elif want_json:
		payload["format"] = "json"
	data = _post(url, payload, headers, timeout, retry_without="format", retry_value="json" if schema else None)
	if "message" in data:
		text = (data.get("message") or {}).get("content") or ""
	elif data.get("choices"):
		text = data["choices"][0].get("message", {}).get("content") or ""
	else:
		raise AIError(_("Unexpected answer from the AI server."))
	return text, (cint(data.get("prompt_eval_count")), cint(data.get("eval_count")))


def _post(url, payload, headers, timeout, retry_without=None, retry_value=None):
	resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=timeout)
	if resp.status_code in (400, 422, 500) and retry_without and retry_without in payload:
		# older servers reject structured-output options: retry once with a simpler one
		if retry_value:
			payload[retry_without] = retry_value
		else:
			payload.pop(retry_without)
		resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=timeout)
	if resp.status_code >= 400:
		raise AIError(_("AI server returned HTTP {0}: {1}").format(resp.status_code, resp.text[:300]))
	try:
		return resp.json()
	except ValueError as e:
		raise AIError(_("AI server returned a non-JSON response.")) from e


# ----------------------------------------------------------------------------- logging
def _new_log(settings, feature, reference, model):
	return {
		"doctype": LOG_DT,
		"status": "Failed",
		"feature": feature,
		"provider": provider(settings),
		"model": model or settings.ai_model,
		"reference_doctype": reference[0] if reference else None,
		"reference_name": reference[1] if reference else None,
		"user": frappe.session.user,
	}


def _write_log(settings, log):
	if not cint(settings.get("ai_log_enabled", 1)):
		return
	if not frappe.db.table_exists(LOG_DT):
		return
	if log.get("status") != "Success" and not frappe.flags.in_test:
		# failed/blocked calls usually precede a rollback: write from a job so the row survives
		try:
			frappe.enqueue("alphax_crm.ai.engine.insert_log", queue="short", log=log, enqueue_after_commit=False)
			return
		except Exception:
			pass
	insert_log(log)


def insert_log(log: dict):
	try:
		frappe.get_doc(log).insert(ignore_permissions=True, ignore_links=True)
	except Exception:
		frappe.log_error(title="AlphaX CRM: could not write AI log", message=frappe.get_traceback())


def purge_old_logs():
	"""Daily: keep the AI log for the configured number of days (default 90)."""
	if not frappe.db.table_exists(LOG_DT):
		return
	days = cint(get_settings().get("ai_log_retention_days")) or 90
	frappe.db.delete(LOG_DT, {"creation": ("<", add_days(now_datetime(), -days))})
	frappe.db.commit()


def usage_today() -> dict:
	row = frappe.db.sql(
		f"""select count(*), coalesce(sum(input_tokens + output_tokens), 0),
		sum(status = 'Failed'), sum(status = 'Blocked') from `tab{LOG_DT}` where creation >= %s""",
		(nowdate(),))[0]
	return {"calls": cint(row[0]), "tokens": cint(row[1]), "failed": cint(row[2]), "blocked": cint(row[3])}


@frappe.whitelist()
def get_usage():
	frappe.only_for(("System Manager", "Sales Manager"))
	s = get_settings()
	return {**usage_today(), "budget": cint(s.get("ai_daily_token_budget")), "provider": provider(s),
		"url": chat_url(s), "model": s.ai_model, "fast_model": s.get("ai_fast_model")}


def strip_code(text: str) -> str:
	return re.sub(r"^```\w*\s*|\s*```$", "", (text or "").strip())
