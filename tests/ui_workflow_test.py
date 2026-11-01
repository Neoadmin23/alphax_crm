"""Browser test of the 0.41 workflow screens. Usage: python ui_workflow_test.py http://127.0.0.1:8000 OUTDIR
Run tests/ui_workflow_setup.py on the site first. Logs in as Administrator (stage bypass off: System Manager
only bypasses, so a Sales User flow is simulated with the same rules)."""
import json
import sys

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1], sys.argv[2]
SETUP = json.load(open("/srv/mock/ui_setup.json"))
results, errors = [], []


def check(label, cond, detail=""):
	results.append(bool(cond))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""), flush=True)


def open_lead(page, name):
	page.goto(f"{BASE}/app/lead/{name}")
	page.wait_for_selector(".form-layout")
	page.wait_for_function("() => cur_frm && cur_frm.docname && !cur_frm.is_dirty()")
	page.wait_for_timeout(800)


def menu(page, group, item):
	page.locator(".inner-group-button", has_text=group).locator("button").first.click()
	page.locator(".dropdown-menu.show .dropdown-item", has_text=item).first.click()


with sync_playwright() as p:
	browser = p.chromium.launch()
	page = browser.new_page(viewport={"width": 1366, "height": 900})
	page.set_default_timeout(20000)
	page.on("pageerror", lambda e: errors.append(str(e) + " @ " + (e.stack or "")[:300]))
	page.goto(f"{BASE}/login")
	page.fill("#login_email", "Administrator")
	page.fill("#login_password", "admin")
	page.click(".btn-login")
	page.wait_for_url("**/app**", timeout=60000)
	page.wait_for_function("() => window.frappe && frappe.boot && frappe.boot.alphax_workflow")

	# Lead Stage dropdown offers approved stages only
	open_lead(page, SETUP["postpone"])
	opts = page.evaluate("() => cur_frm.fields_dict.status.df.options.split('\\n')")
	check("Lead Stage dropdown: approved stages only", "Replied" not in opts and "Converted" not in opts
		and "Contract Under Signing" in opts and opts[0] == "Lead", opts)

	# Postponed prompt
	page.evaluate("() => cur_frm.set_value('status', 'Postponed')")
	page.wait_for_selector(".modal.show [data-fieldname='date'] input")
	check("choosing Postponed asks for the Next Contact Date", page.locator(".modal.show .modal-title", has_text="Postpone Lead").count() == 1)
	page.screenshot(path=f"{OUT}/1_postpone_prompt.png")
	page.locator(".modal.show [data-fieldname='note'] textarea").fill("Client budget opens next quarter")
	page.locator(".modal.show .btn-primary", has_text="Postpone").click()
	page.wait_for_timeout(500)
	page.evaluate("() => cur_frm.save()")
	page.wait_for_function("() => !cur_frm.is_dirty() && cur_frm.doc.status === 'Postponed'", timeout=20000)
	check("Lead saved as Postponed with a Next Contact Date", page.evaluate("() => !!cur_frm.doc.alphax_next_contact_date"))
	check("Lead Status follows (Cold Lead)", page.evaluate("() => cur_frm.doc.custom_lead_status") == "Cold Lead")

	# AI suggested stage -> banner + Apply
	open_lead(page, SETUP["suggest"])
	check("AI suggestion banner shown", page.locator(".ax-wf-banner >> text=AI suggests moving this Lead to").count() >= 1)
	page.screenshot(path=f"{OUT}/2_ai_suggestion.png")
	menu(page, "AlphaX AI", "Apply Suggested Stage")
	page.wait_for_selector(".modal.show .btn-primary")
	page.locator(".modal.show .btn-primary", has_text="Apply").click()
	page.wait_for_function("() => cur_frm.doc.status === 'Contract Under Signing'", timeout=20000)
	check("Apply Suggested Stage moves the Lead after confirmation", True)

	# Proposed Lost Quotation -> banner + Confirm Lost Quotation
	open_lead(page, SETUP["lost"])
	check("WF-04 proposal banner shown", page.locator(".ax-wf-banner >> text=Confirm Lost Quotation for").count() >= 1)
	menu(page, "AlphaX AI", "Confirm Lost Quotation")
	page.wait_for_selector(".modal.show [data-fieldname='reason'] input")
	page.locator(".modal.show [data-fieldname='reason'] input").fill("Price too high")
	page.wait_for_timeout(600)
	page.keyboard.press("Escape") if page.locator(".awesomplete ul:visible").count() else None
	page.locator(".modal.show [data-fieldname='detailed_reason'] textarea").fill("Client chose a cheaper option")
	page.screenshot(path=f"{OUT}/3_confirm_lost.png")
	page.locator(".modal.show .btn-primary", has_text="Mark as Lost").click()
	page.wait_for_function("() => cur_frm.doc.status === 'Lost Quotation'", timeout=20000)
	check("Confirm Lost Quotation: Lead -> Lost Quotation", page.evaluate("() => cur_frm.doc.custom_lead_status") == "Inactive Lead")
	q_status = page.evaluate(f"async () => (await frappe.db.get_value('Quotation', '{SETUP['lost_q']}', 'status')).message.status")
	check("...and the quotation is marked Lost", q_status == "Lost", q_status)

	# Health check dialog
	page.goto(f"{BASE}/app/alphax-crm-settings")
	page.wait_for_selector(".form-layout")
	page.wait_for_timeout(1200)
	page.locator(".page-actions button", has_text="Run Health Check").click()
	page.wait_for_selector(".modal.show .modal-title >> text=AlphaX Health Check")
	page.wait_for_timeout(500)
	rows = page.locator(".modal.show tbody tr").count()
	check("Health Check dialog lists the checks", rows > 30, rows)
	page.screenshot(path=f"{OUT}/4_health_check.png", full_page=False)
	check("no JavaScript errors", not errors, errors)
	browser.close()

print(f"RESULT {sum(results)}/{len(results)} passed")
