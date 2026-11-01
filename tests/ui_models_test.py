"""Browser test of the 0.42 AI settings tools. Usage: python ui_models_test.py http://127.0.0.1:8000 OUTDIR
Needs tests/mock_ai.py on :8090. Sets AI Assist to the mock Ollama server, then restores nothing (test site)."""
import sys

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1], sys.argv[2]
MOCK = "http://127.0.0.1:8090"
results, errors = [], []


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""), flush=True)


def menu(page, group, item):
	page.locator(".inner-group-button", has_text=group).locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text=item).first.click()


def save(page):
	# don't await frm.save(): its promise never settles when nothing changed
	page.evaluate("() => { if (cur_frm.is_dirty()) cur_frm.save(); }")
	page.wait_for_function("() => !cur_frm.is_dirty()", timeout=20000)
	page.wait_for_timeout(600)


def shot(page, path):
	page.wait_for_timeout(900)  # let the dialog finish fading in
	page.evaluate("() => document.querySelectorAll('#alert-container .alert, .desk-alert').forEach(e => e.remove())")
	page.screenshot(path=path)


def close_modal(page):
	page.locator(".modal.show .btn-modal-close").first.click()
	page.wait_for_timeout(400)


with sync_playwright() as p:
	browser = p.chromium.launch()
	page = browser.new_page(viewport={"width": 1440, "height": 950})
	page.set_default_timeout(30000)
	page.on("pageerror", lambda e: errors.append(str(e) + " @ " + (e.stack or "")[:300]))
	page.goto(f"{BASE}/login")
	page.fill("#login_email", "Administrator")
	page.fill("#login_password", "admin")
	page.click(".btn-login")
	page.wait_for_url("**/app**", timeout=60000)

	page.goto(f"{BASE}/app/alphax-crm-settings")
	page.wait_for_function("() => window.cur_frm && cur_frm.doctype === 'AlphaX CRM Settings'")
	page.wait_for_timeout(800)
	page.evaluate("""() => { cur_frm.set_value('ai_enabled', 1); cur_frm.set_value('ai_residency_mode', 0);
		cur_frm.set_value('ai_fast_model', ''); cur_frm.set_value('ai_model', 'llama3.1'); }""")
	save(page)

	# preset fills server type + address (an empty address gets the preset's placeholder)
	page.evaluate("() => cur_frm.set_value('ai_base_url', '')")
	page.evaluate("() => cur_frm.set_value('ai_preset', 'vLLM (self-hosted)')")
	page.wait_for_function("() => cur_frm.doc.ai_provider === 'OpenAI Compatible' && cur_frm.doc.ai_base_url")
	page.wait_for_timeout(500)
	check("preset vLLM: server type, path and placeholder address filled",
		page.evaluate("() => [cur_frm.doc.ai_chat_path, cur_frm.doc.ai_base_url]") == ["/chat/completions", "http://ai-server.local:8000/v1"])
	page.evaluate("() => cur_frm.set_value('ai_preset', 'Ollama (self-hosted)')")
	page.wait_for_function("() => cur_frm.doc.ai_provider === 'Ollama'")
	page.wait_for_timeout(500)
	check("switching preset replaces the other preset's placeholder", page.evaluate("() => cur_frm.doc.ai_base_url") == "http://ai-server.local:11434")
	page.evaluate(f"() => cur_frm.set_value('ai_base_url', '{MOCK}')")
	page.evaluate("() => cur_frm.set_value('ai_preset', 'vLLM (self-hosted)')")
	page.wait_for_function("() => cur_frm.doc.ai_provider === 'OpenAI Compatible'")
	page.wait_for_timeout(500)
	check("a typed self-hosted address is kept when switching preset", page.evaluate("() => cur_frm.doc.ai_base_url") == MOCK)
	page.evaluate("() => cur_frm.set_value('ai_preset', 'Ollama (self-hosted)')")
	page.wait_for_function("() => cur_frm.doc.ai_provider === 'Ollama'")
	page.wait_for_timeout(500)
	save(page)

	# open models guide
	menu(page, "AI Assist", "Open Models Guide")
	page.wait_for_selector(".modal.show table.ax-models-guide tbody tr")
	rows = page.locator(".modal.show table.ax-models-guide tbody tr").count()
	check("Open Models Guide lists 12 models", rows == 12, rows)
	txt = page.locator(".modal.show table.ax-models-guide").inner_text()
	check("guide shows licence, GPU size, Arabic and use", all(t in txt for t in ("Apache 2.0", "24 GB", "Very good", "Data centre")))
	shot(page, f"{OUT}/1_models_guide.png")
	page.locator(".modal.show [data-fieldname='use'] select").select_option("light")
	page.wait_for_timeout(300)
	check("guide filter: light use shows the small model only",
		page.locator(".modal.show table.ax-models-guide tbody tr").count() == 1)
	close_modal(page)

	# find models on server
	menu(page, "AI Assist", "Find Models on Server")
	page.wait_for_selector(".modal.show table.ax-server-models tbody tr")
	srv = page.locator(".modal.show table.ax-server-models").inner_text()
	check("Find Models lists installed models with guide labels", "qwen3.8:27b" in srv and "Qwen3.8 27B" in srv
		and "not in the guide" in srv, srv[:300])
	shot(page, f"{OUT}/2_find_models.png")
	page.locator(".modal.show tr[data-model='qwen3.8:27b'] .ax-pick[data-target='ai_model']").click()
	page.wait_for_function("() => cur_frm.doc.ai_model === 'qwen3.8:27b'")
	check("one click fills the Model field", True)
	page.wait_for_function("() => cur_frm.fields_dict.ai_model_info.$wrapper.text().includes('Qwen3.8 27B')")
	check("model info badge under the fields", "Very good" in page.evaluate("() => cur_frm.fields_dict.ai_model_info.$wrapper.text()"))
	save(page)

	# self-test
	menu(page, "AI Assist", "Test Model")
	page.wait_for_selector(".modal.show table.ax-selftest tr", timeout=120000)
	st = page.locator(".modal.show").last.inner_text()
	check("Test Model: 4 checks shown, Passed", "Passed" in st and page.locator(".modal.show table.ax-selftest tr").count() == 4
		and "Arabic request" in st, st[:300])
	shot(page, f"{OUT}/3_model_test_passed.png")
	close_modal(page)
	page.wait_for_function("() => cur_frm.doc.ai_selftest_status === 'Passed'", timeout=20000)
	check("result stored on the settings", True)

	# a weak Fast Model fails
	page.evaluate("() => cur_frm.set_value('ai_fast_model', 'tinyllama:1b')")
	save(page)
	page.reload()
	page.wait_for_function("() => window.cur_frm && cur_frm.doctype === 'AlphaX CRM Settings'")
	page.wait_for_timeout(800)
	menu(page, "AI Assist", "Test Fast Model")
	page.wait_for_selector(".modal.show table.ax-selftest tr", timeout=120000)
	st = page.locator(".modal.show").last.inner_text()
	check("Test Fast Model: weak model Failed, explains the main model takes over", "Failed" in st and "main model takes over" in st, st[:300])
	shot(page, f"{OUT}/4_fast_model_failed.png")
	close_modal(page)

	# a dropped tunnel is reported as an outage, not a failed model
	page.evaluate("() => cur_frm.set_value('ai_fast_model', 'tunnel-down:8b')")
	save(page)
	menu(page, "AI Assist", "Test Fast Model")
	page.wait_for_selector(".modal.show .indicator-pill.orange", timeout=120000)
	st = page.locator(".modal.show").last.inner_text()
	check("dropped tunnel: 'Server unreachable' with readable error and advice", "Server unreachable" in st
		and "Tunnel is down" in st and "<html" not in st.lower(), st[:300])
	shot(page, f"{OUT}/6_server_unreachable.png")
	close_modal(page)
	check("outage did not mark the Fast Model Failed", page.evaluate("() => cur_frm.doc.ai_fast_selftest_status") != "Failed")

	# free tier badge
	page.evaluate("""() => { cur_frm.set_value('ai_fast_model', ''); cur_frm.set_value('ai_preset', 'OpenRouter (hosted open models)'); }""")
	page.wait_for_function("() => cur_frm.doc.ai_base_url === 'https://openrouter.ai/api/v1'")
	page.evaluate("() => cur_frm.set_value('ai_model', 'qwen/qwen3.6-27b:free')")
	page.wait_for_function("() => cur_frm.fields_dict.ai_model_info.$wrapper.text().includes('Free tier')")
	check("free-tier model badge: Free tier · External", True)
	page.locator("[data-fieldname='ai_model_info']").scroll_into_view_if_needed()
	shot(page, f"{OUT}/5_free_tier_badge.png")
	# back to the mock server
	page.evaluate("""() => { cur_frm.set_value('ai_preset', 'Ollama (self-hosted)'); }""")
	page.wait_for_function("() => cur_frm.doc.ai_provider === 'Ollama'")
	page.evaluate(f"() => {{ cur_frm.set_value('ai_base_url', '{MOCK}'); cur_frm.set_value('ai_model', 'llama3.1'); }}")
	save(page)

	check("no JavaScript errors", not errors, errors)
	browser.close()

print(f"RESULT {sum(results)}/{len(results)} passed")
