
// Lead Data Quality Monitor
// Lead list with dynamic filters, quick filters and colour formatting.

var ldqm_is_manager = function () {
	return (
		frappe.session.user === "Administrator" ||
		frappe.user.has_role("Sales Manager") ||
		frappe.user.has_role("System Manager")
	);
};

frappe.query_reports["Lead Data Quality Monitor"] = {
	filters: [
		// Row 1
		{
			fieldname: "search",
			label: __("Search"),
			fieldtype: "Data"
		},
		{
			fieldname: "lead_owner",
			label: __("Lead Owner"),
			fieldtype: "Link",
			options: "User"
		},
		{
			fieldname: "lead_status",
			label: __("Lead Status"),
			fieldtype: "Select",
			options: ""
		},
		{
			fieldname: "status",
			label: __("Lead Stage"),
			fieldtype: "Select",
			options: ""
		},
		{
			fieldname: "workflow_state",
			label: __("Workflow State"),
			fieldtype: "Select",
			options: ""
		},
		{
			fieldname: "source",
			label: __("Source"),
			fieldtype: "Link",
			options: "Lead Source"
		},

		// Row 2
		{
			fieldname: "aging_bucket",
			label: __("Aging Bucket"),
			fieldtype: "Select",
			options: "\n0-7 Days\n8-15 Days\n16-30 Days\n31-60 Days\n61-90 Days\n90+ Days"
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: new Date().getFullYear()
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date"
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date"
		},
		{
			fieldname: "dq_from",
			label: __("DQ From %"),
			fieldtype: "Float"
		},
		{
			fieldname: "dq_to",
			label: __("DQ To %"),
			fieldtype: "Float"
		},

		// Row 3
		{
			fieldname: "idle_days",
			label: __("Minimum Idle Days"),
			fieldtype: "Int"
		},
		{
			fieldname: "stale_after_days",
			label: __("Stale After (Days)"),
			fieldtype: "Int",
			default: 14
		},
		{
			fieldname: "open_only",
			label: __("Open Leads Only"),
			fieldtype: "Check"
		},
		{
			fieldname: "followup_health",
			label: __("Follow-up Health"),
			fieldtype: "Select",
			options: "\nCritical\nStale\nStale or Critical\nActive\nClosed",
			description: __(
				"Stale = idle longer than the Stale After days; Critical = idle longer than twice that"
			)
		},
		{
			fieldname: "scope",
			label: __("Show"),
			fieldtype: "Select",
			options: "My Leads First\nMy Leads Only\nAll Leads",
			default: "My Leads First"
		}
	],

	onload: function (report) {

		// =========================================================
		// FILTER STYLING
		// =========================================================

		if (!document.getElementById("ldqm-style")) {
			const st = document.createElement("style");
			st.id = "ldqm-style";

			st.textContent = `
				.ldqm-filters {
					display: grid !important;
					grid-template-columns: repeat(6, minmax(0, 1fr));
					gap: 10px 14px;
					align-items: end;
					width: 100%;
				}

				@media (max-width: 1100px) {
					.ldqm-filters {
						grid-template-columns: repeat(3, minmax(0, 1fr));
					}
				}

				@media (max-width: 640px) {
					.ldqm-filters {
						grid-template-columns: repeat(2, minmax(0, 1fr));
					}
				}

				.ldqm-filters > .frappe-control {
					position: relative;
					width: auto !important;
					max-width: none !important;
					min-width: 0;
					margin: 16px 0 0 0 !important;
					padding: 0 !important;
					float: none !important;
					flex: none !important;
				}

				.ldqm-filters > .frappe-control[data-label]:not([data-fieldtype="Check"])::before {
					content: attr(data-label);
					position: absolute;
					top: -16px;
					left: 0;
					right: 0;
					line-height: 14px;
					font-size: 11px;
					font-weight: 500;
					color: var(--text-muted);
					pointer-events: none;
					white-space: nowrap;
					overflow: hidden;
					text-overflow: ellipsis;
				}

				.ldqm-filters > .frappe-control[data-fieldtype="Check"] {
					padding-bottom: 6px !important;
				}

				.ldqm-filters .form-control::placeholder {
					color: transparent;
				}

				.ldqm-filters .frappe-control [class*="placeholder"] {
					display: none !important;
				}

				.ldqm-filters .frappe-control .help-box {
					display: none;
				}

				.ldqm-drill {
					cursor: pointer;
					font-weight: 600;
					text-decoration: underline;
				}
			`;

			document.head.appendChild(st);
		}

		const first = (report.filters || [])[0];

		if (first && first.$wrapper) {
			first.$wrapper.parent().addClass("ldqm-filters");
		}

		(report.filters || []).forEach((filter) => {
			if (filter.$wrapper) {
				filter.$wrapper.attr("data-label", filter.df.label);
			}
		});


		// =========================================================
		// DYNAMIC FILTER OPTIONS
		// =========================================================

		// Generic option loader.
		// Select fields use DocType metadata.
		// Other fields use values already present in Lead records.

		const load_field_options = (filter_name, field_name) => {

			const filter = report.get_filter(filter_name);

			if (!filter) {
				console.error(
					"LDQM: Report filter not found:",
					filter_name
				);
				return;
			}

			const field_meta = frappe.meta.get_docfield(
				"Lead",
				field_name
			);

			if (!field_meta) {
				console.error(
					"LDQM: Lead field metadata not found:",
					field_name
				);
				return;
			}

			// Case 1: Select field - load configured options.
			if (field_meta.fieldtype === "Select") {

				const options = (field_meta.options || "")
					.split("\n")
					.map(value => value.trim())
					.filter(Boolean);

				if (!options.length) {
					console.warn(
						"LDQM: No Select options configured:",
						field_name
					);
					return;
				}

				filter.df.options = "\n" + options.join("\n");
				filter.refresh();

				console.log(
					"LDQM: Loaded metadata options:",
					filter_name,
					options
				);

				return;
			}

			// Case 2: Other field types - fetch distinct existing values.
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Lead",
					fields: [field_name],
					group_by: field_name,
					order_by: field_name + " asc",
					limit_page_length: 100
				},
				callback: (response) => {

					const values = (response.message || [])
						.map(row => row[field_name])
						.filter(Boolean);

					if (!values.length) {
						console.warn(
							"LDQM: No values found:",
							field_name
						);
						return;
					}

					filter.df.options = "\n" + values.join("\n");
					filter.refresh();

					console.log(
						"LDQM: Loaded database options:",
						filter_name,
						values
					);
				},
				error: (error) => {
					console.error(
						"LDQM: Failed loading options:",
						field_name,
						error
					);
				}
			});
		};


		// ---------------------------------------------------------
		// Lead Stage -> Lead.status
		// ---------------------------------------------------------

		load_field_options("status", "status");


		// ---------------------------------------------------------
		// Lead Status -> Lead.custom_lead_status
		// ---------------------------------------------------------

		if (frappe.meta.has_field("Lead", "custom_lead_status")) {

			load_field_options(
				"lead_status",
				"custom_lead_status"
			);

		} else {

			report.toggle_filter_display("lead_status", true);

			console.warn(
				"LDQM: custom_lead_status does not exist on Lead."
			);
		}


		// ---------------------------------------------------------
		// Workflow State -> Active Lead Workflow
		// ---------------------------------------------------------

		const set_workflow_options = (states) => {

			const filter = report.get_filter("workflow_state");

			if (!filter || !states.length) {
				return;
			}

			filter.df.options = "\n" + states.join("\n");
			filter.refresh();

			console.log(
				"LDQM: Workflow states loaded:",
				states
			);
		};

		const load_workflow_state_fallback = () => {
			load_field_options(
				"workflow_state",
				"workflow_state"
			);
		};

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Workflow",
				filters: {
					document_type: "Lead",
					is_active: 1
				},
				fields: ["name"],
				limit_page_length: 1
			},
			callback: (response) => {

				const workflows = response.message || [];
				const workflow_name = workflows.length
					? workflows[0].name
					: null;

				if (!workflow_name) {
					load_workflow_state_fallback();
					return;
				}

				frappe.call({
					method: "frappe.client.get",
					args: {
						doctype: "Workflow",
						name: workflow_name
					},
					callback: (result) => {

						const states = (
							result.message &&
								result.message.states
								? result.message.states
								: []
						)
							.map(row => row.state)
							.filter(Boolean);

						if (states.length) {
							set_workflow_options(states);
						} else {
							load_workflow_state_fallback();
						}
					},
					error: load_workflow_state_fallback
				});
			},
			error: load_workflow_state_fallback
		});


		// =========================================================
		// QUICK FILTERS
		// =========================================================

		const clear_all = () => {

			report.filters.forEach((filter) => {

				const default_value = filter.df.default;

				if (
					default_value !== undefined &&
					default_value !== null &&
					default_value !== ""
				) {
					filter.set_value(default_value);
				} else {
					filter.set_value(
						filter.df.fieldtype === "Check" ? 0 : ""
					);
				}
			});
		};


		const quick = (label, values) => {

			report.page.add_inner_button(
				__(label),
				() => {

					clear_all();

					setTimeout(() => {

						Object.keys(values).forEach((key) => {
							report.set_filter_value(
								key,
								values[key]
							);
						});

						report.refresh();

					}, 300);
				},
				__("Quick Filters")
			);
		};


		quick("My Leads Only", {
			scope: "My Leads Only"
		});

		quick("Critical Leads", {
			followup_health: "Critical"
		});

		quick("Stale / Critical", {
			followup_health: "Stale or Critical"
		});

		quick("Open Leads", {
			open_only: 1
		});

		quick("Low Data Quality (<50%)", {
			open_only: 1,
			dq_to: 49.99
		});

		quick("Older than 90 Days", {
			open_only: 1,
			aging_bucket: "90+ Days"
		});

		quick("New (last 7 days)", {
			aging_bucket: "0-7 Days"
		});

		quick("This Year", {
			year: new Date().getFullYear()
		});


		// Clear Filters button.
		report.page.add_inner_button(
			__("Clear Filters"),
			() => {
				clear_all();

				setTimeout(() => {
					report.refresh();
				}, 300);
			},
			__("Quick Filters")
		);


		// =========================================================
		// MANAGER SHORTCUT
		// =========================================================

		if (ldqm_is_manager()) {

			report.page.add_inner_button(
				__("Open Lead Monitor Summary"),
				() => {

					frappe.db.get_value(
						"Report",
						{
							report_name: "Lead Monitor Summary"
						},
						"name"
					).then((response) => {

						const real_name =
							response &&
							response.message &&
							response.message.name;

						if (real_name) {

							frappe.set_route(
								"query-report",
								real_name
							);

						} else {

							frappe.msgprint(
								__(
									"Report 'Lead Monitor Summary' was not found. Please create it first."
								)
							);
						}
					});
				}
			);
		}
	},


	// =============================================================
	// ROW FORMATTER
	// =============================================================

	formatter: function (
		value,
		row,
		column,
		data,
		default_formatter
	) {

		value = default_formatter(
			value,
			row,
			column,
			data
		);

		if (!data) {
			return value;
		}

		const colour = (color) => {
			return `<span style="color:${color};font-weight:600">${value}</span>`;
		};


		// Own lead marker.
		if (
			column.fieldname === "is_mine" &&
			data.is_mine
		) {
			return `<span style="color:#f79009;font-weight:700">${value}</span>`;
		}


		// Lead owner.
		if (
			column.fieldname === "lead_owner" &&
			data.lead_owner === frappe.session.user
		) {
			return colour("#175cd3");
		}


		// Follow-up health.
		if (column.fieldname === "followup_health") {

			const map = {
				Critical: "#d92d20",
				Stale: "#dc6803",
				Active: "#039855",
				Closed: "#667085"
			};

			return colour(
				map[data.followup_health] || "inherit"
			);
		}


		// Data quality level.
		if (column.fieldname === "dq_level") {

			const map = {
				Low: "#d92d20",
				Medium: "#dc6803",
				High: "#039855"
			};

			return colour(
				map[data.dq_level] || "inherit"
			);
		}


		// Old leads.
		if (
			column.fieldname === "aging_bucket" &&
			data.aging_bucket === "90+ Days"
		) {
			return colour("#d92d20");
		}


		// Idle days.
		if (
			column.fieldname === "alphax_idle_days" &&
			data.alphax_idle_days > 28
		) {
			return colour("#d92d20");
		}

		return value;
	}
};
