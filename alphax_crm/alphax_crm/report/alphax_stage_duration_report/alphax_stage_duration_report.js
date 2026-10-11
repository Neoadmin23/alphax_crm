// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Stage Duration Report"] = {
	filters: [
		{
			fieldname: "reference_doctype",
			label: __("Record Type"),
			fieldtype: "Select",
			options: "\nLead\nAlphaX PreLead\nOpportunity",
		},
		{
			fieldname: "field_label",
			label: __("Tracked Field"),
			fieldtype: "Select",
			options: "\nLead Status\nLead Stage\nWorkflow State",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],
};
