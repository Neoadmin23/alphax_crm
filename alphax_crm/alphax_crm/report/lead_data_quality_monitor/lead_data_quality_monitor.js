// Lead Data Quality Monitor - filters, quick-filter buttons, colour formatting
frappe.query_reports["Lead Data Quality Monitor"] = {
	filters: [
		// Row 1 - who / what
		{ fieldname: "search", label: __("Search"), fieldtype: "Data" },
		{ fieldname: "lead_owner", label: __("Lead Owner"), fieldtype: "Link", options: "User" },
		{ fieldname: "lead_stage", label: __("Lead Stage"), fieldtype: "Select", options: "" },
		{ fieldname: "lead_status", label: __("Lead Status"), fieldtype: "Select", options: "" },
		{ fieldname: "workflow_state", label: __("Workflow State"), fieldtype: "Select", options: "" },
		{ fieldname: "source", label: __("Source"), fieldtype: "Link", options: "Lead Source" },
		// Row 2 - when
		{ fieldname: "aging_bucket", label: __("Aging Bucket"), fieldtype: "Select",
		  options: "\n0-7 Days\n8-15 Days\n16-30 Days\n31-60 Days\n61-90 Days\n90+ Days" },
		{ fieldname: "year", label: __("Year"), fieldtype: "Int" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "dq_from", label: __("DQ From %"), fieldtype: "Float" },
		{ fieldname: "dq_to", label: __("DQ To %"), fieldtype: "Float" },
		// Row 3 - activity + toggles
		{ fieldname: "idle_days", label: __("Minimum Idle Days"), fieldtype: "Int" },
		{ fieldname: "stale_after_days", label: __("Stale After (Days)"), fieldtype: "Int", default: 14 },
		{ fieldname: "open_only", label: __("Open Leads Only"), fieldtype: "Check" },
		{ fieldname: "stale_only", label: __("Stale / Critical Only"), fieldtype: "Check" },
	],

	onload: function (report) {
		if (!document.getElementById("ldqm-style")) {
			const st = document.createElement("style");
			st.id = "ldqm-style";
			st.textContent =
				".page-form .frappe-control[data-fieldtype='Check'] { margin-top: 6px; }" +
				".page-form .frappe-control[data-fieldtype='Check'] .help-box { display: none; }";
			document.head.appendChild(st);
		}
		// Fill Stage / Status dropdowns with the values that actually exist on your leads
		const load_options = (filter_name, field) => {
			frappe.call({
				method: "frappe.client.get_list",
				args: { doctype: "Lead", fields: [field], group_by: field, order_by: field + " asc", limit_page_length: 100 },
				callback: (r) => {
					const f = report.get_filter(filter_name);
					const vals = (r.message || []).map((d) => d[field]).filter(Boolean);
					if (f && vals.length) {
						f.df.options = "\n" + vals.join("\n");
						f.refresh();
					}
				},
			});
		};
		// Workflow State: only the states defined in the active Lead workflow
		// (falls back to the states actually used on leads if the user cannot read Workflow)
		const set_ws_options = (vals) => {
			const f = report.get_filter("workflow_state");
			if (f && vals.length) {
				f.df.options = "\n" + vals.join("\n");
				f.refresh();
			}
		};
		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Workflow", filters: { document_type: "Lead", is_active: 1 }, fields: ["name"], limit_page_length: 1 },
			callback: (r) => {
				const wf = r.message && r.message[0] && r.message[0].name;
				if (!wf) return load_options("workflow_state", "workflow_state");
				frappe.call({
					method: "frappe.client.get",
					args: { doctype: "Workflow", name: wf },
					callback: (res) => {
						const states = ((res.message && res.message.states) || []).map((s) => s.state);
						if (states.length) set_ws_options(states);
						else load_options("workflow_state", "workflow_state");
					},
				});
			},
			error: () => load_options("workflow_state", "workflow_state"),
		});

		load_options("lead_stage", "status");
		load_options("lead_status", "custom_lead_status");

		// One-click quick filters
		const clear_all = () => {
			report.filters.forEach((f) => {
				const n = f.df.fieldname;
				if (n === "stale_after_days") f.set_value(14);
				else f.set_value(f.df.fieldtype === "Check" ? 0 : "");
			});
		};
		const quick = (label, values) => {
			report.page.add_inner_button(
				__(label),
				() => {
					clear_all();
					setTimeout(() => {
						Object.keys(values).forEach((k) => report.set_filter_value(k, values[k]));
						report.refresh();
					}, 300);
				},
				__("Quick Filters")
			);
		};
		quick("Open Leads", { open_only: 1 });
		quick("Stale / Critical", { open_only: 1, stale_only: 1 });
		quick("Low Data Quality (<50%)", { open_only: 1, dq_to: 49.99 });
		quick("Older than 90 Days", { open_only: 1, aging_bucket: "90+ Days" });
		quick("New (last 7 days)", { aging_bucket: "0-7 Days" });
		quick("This Year", { year: new Date().getFullYear() });
		report.page.add_inner_button(__("Clear Filters"), () => { clear_all(); setTimeout(() => report.refresh(), 300); }, __("Quick Filters"));
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		const colour = (c) => `<span style="color:${c};font-weight:600">${value}</span>`;

		if (column.fieldname === "followup_health") {
			const map = { Critical: "#d92d20", Stale: "#dc6803", Active: "#039855", Closed: "#667085" };
			return colour(map[data.followup_health] || "inherit");
		}
		if (column.fieldname === "dq_level") {
			const map = { Low: "#d92d20", Medium: "#dc6803", High: "#039855" };
			return colour(map[data.dq_level] || "inherit");
		}
		if (column.fieldname === "aging_bucket" && data.aging_bucket === "90+ Days") {
			return colour("#d92d20");
		}
		if (column.fieldname === "alphax_idle_days" && data.alphax_idle_days > 28) {
			return colour("#d92d20");
		}
		return value;
	},
};
