"""Browser test of AlphaX AI 0.40 (Playwright). Usage: python ui_ai_test.py http://127.0.0.1:8000 OUTDIR"""

import sys

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1], sys.argv[2]
results, errors = [], []
RUN = __import__("secrets").token_hex(3)


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""), flush=True)


def val(page, field):
	return page.evaluate(f"() => cur_frm.doc['{field}']")


def expand_to(page, field):
	page.evaluate(f"() => cur_frm.scroll_to_field('{field}')")
	page.wait_for_timeout(500)


with sync_playwright() as p:
	browser = p.chromium.launch()
	page = browser.new_page(viewport={"width": 1366, "height": 900})
	page.set_default_timeout(20000)
	page.on("pageerror", lambda e: errors.append(str(e) + " @ " + (e.stack or "")[:600]))
	page.goto(f"{BASE}/login")
	page.fill("#login_email", "Administrator")
	page.fill("#login_password", "admin")
	page.click(".btn-login")
	page.wait_for_url("**/app**", timeout=60000)
	page.wait_for_function("() => window.frappe && frappe.boot && frappe.boot.user")
	page.evaluate("""async () => {
		await frappe.xcall('frappe.client.set_value', {doctype: 'AlphaX CRM Settings', name: 'AlphaX CRM Settings',
			fieldname: {ai_enabled: 1, ai_writing_enabled: 1, ai_spellcheck_mode: 'Suggest', ai_provider: 'Ollama',
				ai_chat_path: '/api/chat', ai_base_url: 'http://127.0.0.1:8090', ai_residency_mode: 0, ai_daily_token_budget: 0}});
	}""")
	page.reload()
	page.wait_for_function("() => frappe.boot && frappe.boot.alphax_ai_writing && frappe.boot.alphax_ai")
	check("writing tools config booted", page.evaluate("() => frappe.boot.alphax_ai_writing.doctypes.includes('Lead')"))

	# ---------------------------------------------------------------- new Lead: AI button + spell check
	page.goto(f"{BASE}/app/lead/new")
	page.wait_for_selector(".form-layout")
	page.wait_for_timeout(800)
	page.locator('.frappe-control[data-fieldname="first_name"] input').fill("Sara")
	page.locator('.frappe-control[data-fieldname="email_id"] input').fill(f"sara.ui.{RUN}@acme.sa")
	expand_to(page, "alphax_inbound_message")
	inbound = '.frappe-control[data-fieldname="alphax_inbound_message"]'
	page.wait_for_selector(f"{inbound} .ax-ai-btn", timeout=10000)
	check("AI button next to text field label", page.locator(f"{inbound} .ax-ai-btn").count() == 1)
	expand_to(page, "alphax_ai_draft_reply")
	addr = page.evaluate("() => Object.keys(cur_frm.fields_dict).filter(f => f.includes('address') && ['Small Text','Text'].includes(cur_frm.fields_dict[f].df.fieldtype))")
	check("no AI button on address fields", all(page.locator(f'.frappe-control[data-fieldname="{f}"] .ax-ai-btn').count() == 0 for f in addr), addr)
	check("no AI button on name/email fields", page.locator('.frappe-control[data-fieldname="email_id"] .ax-ai-btn').count() == 0)

	page.locator(f"{inbound} textarea").fill("Please recieve teh quotation for 12 branches")
	page.keyboard.press("Tab")
	page.wait_for_selector(".ax-ai-pop", timeout=15000)
	chips = page.locator(".ax-ai-pop .ax-chip").all_inner_texts()
	check("spell suggestions on leaving the field", len(chips) == 2, chips)
	page.screenshot(path=f"{OUT}/1_spell_suggest.png")
	page.click(".ax-ai-pop .ax-apply")
	page.wait_for_timeout(500)
	check("Apply fixes spelling", val(page, "alphax_inbound_message") == "Please receive the quotation for 12 branches",
		val(page, "alphax_inbound_message"))

	# ---------------------------------------------------------------- AI menu: translate -> Replace
	reply = '.frappe-control[data-fieldname="alphax_ai_draft_reply"]'
	expand_to(page, "alphax_ai_draft_reply")
	page.locator(f"{reply} textarea").fill("We will send the Quotation to ops@acme.sa today")
	page.wait_for_timeout(700)
	page.locator(f"{reply} .ax-ai-btn").click()
	page.wait_for_selector(".ax-ai-menu")
	items = page.locator(".ax-ai-menu button").all_inner_texts()
	check("AI menu has 6 actions", len(items) == 6 and "Translate to English" in items, items)
	page.screenshot(path=f"{OUT}/2_ai_menu.png")
	page.locator(".ax-ai-menu button", has_text="Translate to Arabic").click()
	page.wait_for_selector(".modal.show .ax-ai-compare")
	page.wait_for_timeout(400)
	result = page.locator(".modal.show .ax-pane.ax-result").inner_text()
	check("translation preview", result.startswith("ترجمة: ") and "ops@acme.sa" in result, result)
	page.wait_for_timeout(300)
	check("busy overlay cleared after result", page.evaluate("() => !frappe.dom.freeze_count"), page.evaluate("() => frappe.dom.freeze_count"))
	page.screenshot(path=f"{OUT}/3_translate_preview.png")
	page.locator(".modal.show .btn-primary", has_text="Replace").click()
	page.wait_for_timeout(600)
	check("Replace writes translation", val(page, "alphax_ai_draft_reply").startswith("ترجمة: We will send"),
		val(page, "alphax_ai_draft_reply"))

	# translate English back, keep original + add below
	page.locator(f"{reply} textarea").fill("Thank you for your interest")
	page.wait_for_timeout(700)
	page.locator(f"{reply} .ax-ai-btn").click()
	page.locator(".ax-ai-menu button", has_text="Translate to Arabic").click()
	page.wait_for_selector(".modal.show .ax-ai-compare")
	page.locator(".modal.show .btn-secondary", has_text="Add Below Original").click()
	page.wait_for_timeout(600)
	check("Add Below Original keeps both", val(page, "alphax_ai_draft_reply") == "Thank you for your interest\n\nترجمة: Thank you for your interest",
		val(page, "alphax_ai_draft_reply"))

	# improve: preview only, Cancel leaves the field alone
	page.locator(f"{reply} .ax-ai-btn").click()
	page.locator(".ax-ai-menu button", has_text="Improve wording").click()
	page.wait_for_selector(".modal.show .ax-ai-compare")
	check("improve preview", page.locator(".modal.show .ax-pane.ax-result").inner_text().startswith("Improved: "))
	page.evaluate("() => window.cur_dialog && cur_dialog.hide()")
	page.wait_for_timeout(500)
	check("closing preview changes nothing", val(page, "alphax_ai_draft_reply").startswith("Thank you for your interest\n\n"))

	# ---------------------------------------------------------------- save + Sales AI buttons
	page.evaluate("() => cur_frm.save()")
	page.wait_for_function("() => !cur_frm.doc.__islocal && !cur_frm.is_dirty()", timeout=30000)
	page.wait_for_timeout(1200)
	lead = page.evaluate("() => cur_frm.docname")
	check("lead saved", lead.startswith("CRM-LEAD") or bool(lead), lead)
	page.locator(".inner-group-button", has_text="AlphaX AI").locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text="Next Best Action").click()
	page.wait_for_function("() => (cur_frm.doc.alphax_ai_next_action || '').startsWith('[Call]')", timeout=20000)
	check("Next Best Action button fills the AI field", True)
	expand_to(page, "alphax_ai_next_action")
	page.screenshot(path=f"{OUT}/4_next_best_action.png")

	page.locator(".inner-group-button", has_text="AlphaX AI").locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text="Draft Follow-up Emails").click()
	page.wait_for_selector(".modal.show [data-fieldname='steps']")
	page.locator(".modal.show [data-fieldname='language'] select").select_option("Arabic")
	page.locator(".modal.show .btn-primary", has_text="Create Drafts").click()
	page.wait_for_url("**/app/alphax-email-draft**", timeout=30000)
	page.wait_for_timeout(1500)
	rows = page.evaluate(f"async () => (await frappe.db.get_list('AlphaX Email Draft', {{filters: {{reference_name: '{lead}'}}, fields: ['name','status','subject']}}))")
	check("3 drafts created, none sent", len(rows) == 3 and all(r["status"] == "Draft" for r in rows), rows)
	page.goto(f"{BASE}/app/alphax-email-draft/{rows[0]['name']}")
	page.wait_for_selector(".form-layout")
	page.wait_for_timeout(800)
	page.screenshot(path=f"{OUT}/5_email_draft.png")
	page.locator(".page-actions button", has_text="Approve").click()
	page.wait_for_function("() => cur_frm.doc.status === 'Approved'", timeout=15000)
	check("Approve button works", True)

	# ---------------------------------------------------------------- Ask AI in Arabic
	page.goto(f"{BASE}/app/lead/{lead}")
	page.wait_for_selector(".form-layout")
	page.wait_for_timeout(800)
	page.locator(".inner-group-button", has_text="AlphaX").filter(has_not_text="AlphaX AI").locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text="Ask AI").click()
	page.wait_for_selector(".modal.show [data-fieldname='answer_language'] select")
	page.locator(".modal.show [data-fieldname='answer_language'] select").select_option("Arabic")
	page.locator(".modal.show [data-fieldname='question'] textarea").fill("What is a lead?")
	page.locator(".modal.show .btn-primary", has_text="Ask").click()
	page.wait_for_selector(".modal.show #alphax-ai-conversation div[dir='rtl']", timeout=20000)
	ans = page.locator(".modal.show #alphax-ai-conversation div[dir='rtl']").first.inner_text()
	check("Ask AI answers in Arabic, right-to-left", ans.startswith("مرحبا"), ans)
	page.screenshot(path=f"{OUT}/6_ask_ai_arabic.png")
	page.evaluate("() => window.cur_dialog && cur_dialog.hide()")
	page.wait_for_timeout(400)
	page.reload()
	page.wait_for_selector(".form-layout")
	page.locator(".inner-group-button", has_text="AlphaX").filter(has_not_text="AlphaX AI").locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text="Ask AI").click()
	page.wait_for_selector(".modal.show [data-fieldname='answer_language'] select")
	check("answer language remembered", page.locator(".modal.show [data-fieldname='answer_language'] select").input_value() == "Arabic")
	page.keyboard.press("Escape")

	# ---------------------------------------------------------------- settings form
	page.goto(f"{BASE}/app/alphax-crm-settings")
	page.wait_for_selector(".form-layout")
	page.wait_for_timeout(1500)
	page.evaluate("() => cur_frm.set_value('ai_provider', 'OpenAI Compatible')")
	page.wait_for_timeout(500)
	check("server type switch suggests /v1/chat/completions", val(page, "ai_chat_path") == "/v1/chat/completions", val(page, "ai_chat_path"))
	expand_to(page, "ai_usage_html")
	page.wait_for_selector("text=Usage today", timeout=10000)
	check("usage today shown in settings", page.locator("text=Open AI Log").count() == 1)
	page.screenshot(path=f"{OUT}/7_settings_governance.png")
	page.evaluate("() => cur_frm.reload_doc()")
	page.wait_for_timeout(800)

	check("no JavaScript errors", not errors, errors)
	browser.close()

print(f"RESULT {sum(results)}/{len(results)} passed")
