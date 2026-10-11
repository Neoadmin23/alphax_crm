// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Quotation Value by Business Unit BI"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			description: __("Defaults to one month back. Leave From/To Date blank to use Period Type + As Of Date instead."),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			description: __("Only used when From Date/To Date are blank."),
		},
		{
			fieldname: "period_type",
			label: __("Period Type"),
			fieldtype: "Select",
			options: "Daily\nWeekly\nMonthly\nQuarterly\nHalf-Yearly\nYearly",
			default: "Monthly",
			description: __("Only used when From Date/To Date are blank."),
		},
		{
			fieldname: "compare_mode",
			label: __("Compare Mode"),
			fieldtype: "Select",
			options: "None\nSame Period Last Year\nSame Quarter Last Year\nFull Last Year",
			default: "None",
		},
		{
			fieldname: "years_back",
			label: __("Years Back"),
			fieldtype: "Select",
			options: "1\n2\n3",
			default: "1",
		},
		{
			fieldname: "lead_owner",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "source",
			label: __("Source"),
			fieldtype: "Link",
			options: "Lead Source",
		},
		{
			fieldname: "city",
			label: __("City"),
			fieldtype: "Data",
		},
		{
			fieldname: "country",
			label: __("Country"),
			fieldtype: "Link",
			options: "Country",
		},
		{
			fieldname: "custom_business_line_",
			label: __("Business Unit"),
			fieldtype: "Select",
			options: "",
			description: __("Populated from the Business Unit values already in use on this site's Leads (there's no separate master list for it)."),
		},
		{
			fieldname: "custom_sub_service",
			label: __("Sub Service"),
			fieldtype: "Select",
			options: "",
			description: __("Sub services in use / defined for the Business Units."),
		},
	],
	chart_type: "bar",
	onload: function (report) {
		// Business Unit has no master doctype to search (see the filter's own
		// description), so its dropdown is filled in here from whatever
		// distinct values are actually on this site's Leads, instead of being
		// a free-text guess.
		frappe.call({
			method: "alphax_crm.crm.bi_report.get_business_unit_options",
			callback: function (r) {
				const filter = report.get_filter("custom_business_line_");
				if (!filter) return;
				const values = r.message || [];
				filter.df.options = [""].concat(values).join("\n");
				filter.refresh();
			},
		});
		frappe.call({
			method: "alphax_crm.crm.bi_report.get_sub_service_options",
			callback: function (r) {
				const filter = report.get_filter("custom_sub_service");
				if (!filter) return;
				filter.df.options = [""].concat(r.message || []).join("\n");
				filter.refresh();
			},
		});
	},
};
