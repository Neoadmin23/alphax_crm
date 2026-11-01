"""Site tests for 0.42 open-model tools (guide, discovery, self-test, presets, free tier, health check).
Needs tests/mock_ai.py on :8090. Copy into the app as alphax_crm/zz_models_test.py:
bench --site SITE execute alphax_crm.zz_models_test.run"""

import frappe

results = []
MOCK = "http://127.0.0.1:8090"


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""), flush=True)


def settings(**values):
	s = frappe.get_single("AlphaX CRM Settings")
	for k, v in values.items():
		s.set(k, v)
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	frappe.clear_document_cache("AlphaX CRM Settings", "AlphaX CRM Settings")
	return frappe.get_single("AlphaX CRM Settings")


def raises(fn, *a, **kw):
	try:
		fn(*a, **kw)
		return None
	except Exception as e:
		return e


def run():
	from alphax_crm.ai import catalogue, engine, models, writing
	from alphax_crm.crm import health

	frappe.set_user("Administrator")
	keep = frappe.get_single("AlphaX CRM Settings").as_dict()
	try:
		_run(catalogue, engine, models, writing, health)
	finally:
		frappe.set_user("Administrator")
		settings(**{k: keep.get(k) for k in ("ai_enabled", "ai_provider", "ai_base_url", "ai_chat_path", "ai_model",
			"ai_fast_model", "ai_residency_mode", "ai_allowed_hosts", "ai_preset")})
		frappe.db.commit()
	print(f"RESULT {sum(results)}/{len(results)} passed")


def _run(catalogue, engine, models, writing, health):
	s = settings(ai_enabled=1, ai_provider="Ollama", ai_base_url=MOCK, ai_chat_path="/api/chat", ai_model="qwen3.8:27b",
		ai_fast_model="", ai_residency_mode=0, ai_preset="Ollama (self-hosted)")
	meta = frappe.get_meta("AlphaX CRM Settings")
	check("settings: preset, model info, self-test and free-tier fields exist", all(meta.has_field(f) for f in (
		"ai_preset", "ai_model_info", "ai_selftest_status", "ai_fast_selftest_status", "ai_selftest_fingerprint", "ai_free_tier")))

	cat = models.get_catalogue()
	check("guide: 12 models with licence, GPU size, Arabic and use", len(cat["models"]) == 12 and all(
		m["licence"] and m["gpu"] and m["arabic"] and m["use_label"] for m in cat["models"]))
	check("guide: 4 presets incl. OpenRouter marked External", len(cat["presets"]) == 4
		and cat["presets"]["OpenRouter (hosted open models)"]["external"] == 1)
	check("guide: current model recognised", cat["current"]["main"]["known"] == "Qwen3.8 27B", cat["current"])

	# ------------------------------------------------------------------ discovery
	r = models.list_server_models(MOCK, "Ollama")
	names = {m["model"]: m for m in r["models"]}
	check("discovery (Ollama /api/tags): installed models listed", r["ok"] and "qwen3.8:27b" in names and len(names) == 7, r)
	check("discovery: catalogue labels known models", names["qwen3.8:27b"]["known"] == "Qwen3.8 27B"
		and names["gpt-oss:20b"]["known"] == "gpt-oss 20B" and names["llama3.1"]["known"] is None)
	check("discovery: known models listed first", r["models"][0]["known"] is not None)
	r2 = models.list_server_models(MOCK + "/v1", "OpenAI Compatible")
	n2 = {m["model"]: m for m in r2["models"]}
	check("discovery (OpenAI /v1/models): AWQ build recognised", r2["ok"] and n2["Qwen/Qwen3.6-27B-AWQ"]["known"] == "Qwen3.6 27B", r2)
	r3 = models.list_server_models("http://127.0.0.1:1", "Ollama")
	check("discovery: unreachable server -> clean message", not r3["ok"] and "Could not reach" in r3["message"])
	if not frappe.db.exists("User", "sm.models@test.local"):
		frappe.get_doc({"doctype": "User", "email": "sm.models@test.local", "first_name": "SM", "send_welcome_email": 0,
			"roles": [{"role": "Sales Manager"}]}).insert(ignore_permissions=True)
	frappe.set_user("sm.models@test.local")
	e = raises(models.list_server_models, MOCK, "Ollama")
	frappe.set_user("Administrator")
	check("discovery: System Manager only (calls an address typed in the form)", isinstance(e, frappe.PermissionError), e)

	# ------------------------------------------------------------------ self-test
	res = models.run_self_test("main")
	s = frappe.get_single("AlphaX CRM Settings")
	check("self-test: 4 checks, one in Arabic", len(res["checks"]) == 4 and any("Arabic" in c["name"] for c in res["checks"]))
	check("self-test: good model -> Passed and stored", res["status"] == "Passed" and s.ai_selftest_status == "Passed"
		and s.ai_selftest_fingerprint and "✓ Structured JSON" in (s.ai_selftest_details or ""), res)
	check("self-test: verdict belongs to this server + model", models.status_of(s, "main") == "Passed")

	s = settings(ai_fast_model="tinyllama:1b")
	res = models.run_self_test("fast")
	s = frappe.get_single("AlphaX CRM Settings")
	check("self-test: model that chats instead of JSON -> Failed", res["status"] == "Failed" and s.ai_fast_selftest_status == "Failed", res)
	check("Fast Model that Failed is not used (main model takes over)", writing._model(s) == "qwen3.8:27b", writing._model(s))

	s = settings(ai_fast_model="weak-partial:7b")
	check("changing the Fast Model resets its result to Not tested", s.ai_fast_selftest_status == "Not tested"
		and not s.ai_fast_selftest_fingerprint)
	check("an untested Fast Model is used", writing._model(s) == "weak-partial:7b")
	res = models.run_self_test("fast")
	check("self-test: JSON ok but Arabic fails -> Partial", res["status"] == "Partial"
		and [c["ok"] for c in res["checks"]] == [True, False, True, False], res)

	# main model fails -> automatic AI paused, reviewed tools keep working
	s = settings(ai_model="tinyllama:1b", ai_fast_model="")
	models.run_self_test("main")
	s = frappe.get_single("AlphaX CRM Settings")
	e = raises(engine.complete, "x", "y", feature="lead_next_action")
	check("main model Failed -> automatic AI blocked with a clear message", isinstance(e, engine.AIBlocked)
		and "self-test" in str(e), e)
	e2 = raises(engine.complete, "You are a writing assistant. Improve the wording", "hello", feature="lead_draft_reply")
	check("main model Failed -> drafts a person reviews still work", e2 is None, e2)
	from alphax_crm.api.ai_query import ask

	ans = ask("How many leads by source?")
	check("Ask AI explains the pause instead of 'server unreachable'", "self-test" in (ans.get("answer") or ""), ans)
	rows = health._ai_models(frappe.get_single("AlphaX CRM Settings"))
	check("health check: failed self-test reported as a problem", any(r["status"] == "fail" and "self-test" in str(r).lower()
		for r in rows), rows)
	s = settings(ai_base_url=MOCK + "/")  # same server, different address text -> new fingerprint
	s = settings(ai_base_url="http://localhost:8090")
	check("changing the server address resets the result to Not tested", s.ai_selftest_status == "Not tested")
	check("...and the automatic-AI pause lifts", raises(engine.complete, "x", "y", feature="lead_next_action") is None)
	rows = health._ai_models(s)
	check("health check: Not tested reported as a warning", any(r["status"] == "warn" and "Not tested" in str(r) for r in rows), rows)

	# ------------------------------------------------------------------ free tier
	s = settings(ai_provider="OpenAI Compatible", ai_base_url="https://openrouter.ai/api/v1", ai_chat_path="/chat/completions",
		ai_model="qwen/qwen3.6-27b:free", ai_residency_mode=0)
	check("free tier: OpenRouter ':free' model flagged on save", s.ai_free_tier == 1)
	check("free tier: governance reports it (PII then always masked)", engine._check_governance(s, "translate") is True)
	s = settings(ai_residency_mode=1, ai_allowed_hosts="openrouter.ai")
	e = raises(engine.complete, "x", "y", feature="translate")
	check("free tier: blocked in KSA Data Residency Mode even when the host is allowed", isinstance(e, engine.AIBlocked)
		and "free hosted tier" in str(e), e)
	rows = health._ai_models(s)
	check("health check: issue while a free-tier model is in use", any("Free-tier" in str(r) for r in rows), rows)
	s = settings(ai_model="qwen/qwen3.6-27b", ai_residency_mode=0, ai_allowed_hosts="")
	check("paid OpenRouter model is not flagged free", s.ai_free_tier == 0 and engine._check_governance(s, "translate") is False)
