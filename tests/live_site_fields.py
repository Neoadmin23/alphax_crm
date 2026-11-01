"""Test-site fixture: the Lead fields the live AlphaX site added via Customize Form
(the app reads them but does not create them). bench execute alphax_crm.zz_fixture.run"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def run():
	create_custom_fields({"Lead": [
		{"fieldname": "custom_lead_status", "label": "Lead Status", "fieldtype": "Select",
		 "options": "\nLead\nProspect\nCold Lead\nInactive Lead\nSuccessful\nCustomer", "insert_after": "status"},
		{"fieldname": "custom_contract", "label": "Contract", "fieldtype": "Select", "options": "\nSigned",
		 "insert_after": "custom_lead_status"},
		{"fieldname": "won_or_lost_date", "label": "Won Or Lost Date", "fieldtype": "Date", "insert_after": "custom_contract"},
		{"fieldname": "lost_reason", "label": "Lost Reason", "fieldtype": "Data", "insert_after": "won_or_lost_date"},
		{"fieldname": "detailed_reason", "label": "Detailed Reason", "fieldtype": "Small Text", "insert_after": "lost_reason"},
	]}, ignore_validate=True)
	for src in ("Website", "Campaign"):
		if not frappe.db.exists("Lead Source", src):
			frappe.get_doc({"doctype": "Lead Source", "source_name": src}).insert(ignore_permissions=True)
	frappe.db.commit()
	print("fixture ok")
