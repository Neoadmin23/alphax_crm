"""Prepare Leads for tests/ui_workflow_test.py. bench execute alphax_crm.zz_ui_setup.run"""
import json

import frappe
from frappe.utils import add_days, nowdate


def _lead(tag):
	d = frappe.get_doc({"doctype": "Lead", "first_name": "UI", "lead_name": f"UI {tag} {frappe.generate_hash(length=4)}",
		"email_id": f"ui.{frappe.generate_hash(length=6)}@client.sa", "mobile_no": "+966511223344", "source": "Website",
		"company_name": "UI Client"})
	d.flags.alphax_skip_ai = True
	d.insert(ignore_permissions=True)
	for st in ("Interested", "Qualified lead", "Quotation"):
		x = frappe.get_doc("Lead", d.name)
		x.status = st
		x.save(ignore_permissions=True)
	company = frappe.db.get_value("Company", {}, "name")
	item = frappe.db.get_value("Item", {"is_sales_item": 1, "disabled": 0}, "name")
	q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Lead", "party_name": d.name, "company": company,
		"valid_till": add_days(nowdate(), 5), "items": [{"item_code": item, "qty": 1, "rate": 2500}]}).insert(ignore_permissions=True)
	q.submit()
	return d.name, q.name


def run():
	frappe.set_user("Administrator")
	frappe.db.set_single_value("AlphaX CRM Settings", "stage_flow_bypass_roles", "System Manager")
	if not frappe.db.exists("Quotation Lost Reason", "Price too high"):
		frappe.get_doc({"doctype": "Quotation Lost Reason", "order_lost_reason": "Price too high"}).insert(ignore_permissions=True)
	out = {}
	out["postpone"], _ = _lead("postpone")
	out["suggest"], _ = _lead("suggest")
	frappe.db.set_value("Lead", out["suggest"], {"alphax_ai_suggested_stage": "Contract Under Signing",
		"alphax_ai_intent": "Ready to sign (91%) — Client asks for the contract."})
	out["lost"], out["lost_q"] = _lead("lost")
	frappe.db.set_value("Lead", out["lost"], "alphax_proposed_action", f"Confirm Lost Quotation for {out['lost_q']} (expired, no action)")
	frappe.db.commit()
	json.dump(out, open("/srv/mock/ui_setup.json", "w"))
	print("UI SETUP", out)
