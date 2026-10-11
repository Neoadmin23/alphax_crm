// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Pipeline Aging BI"] = {
	filters: [
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			description: __("Reconstructs the pipeline as it stood on this date, from each Lead's logged Lead Stage history."),
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
