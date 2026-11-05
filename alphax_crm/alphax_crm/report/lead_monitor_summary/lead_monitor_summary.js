
/*
 * Lead Monitor Summary
 * Aggregated Lead Data Quality Monitor for Sales Managers.
 *
 * Features:
 * - Dynamic dropdown options
 * - Group-by analysis
 * - Follow-up health filtering
 * - Quick views
 * - Click-through to Lead Data Quality Monitor
 * - Conditional formatting
 */

frappe.query_reports["Lead Monitor Summary"] =
	frappe.query_reports["Lead monitor summary"] = {

		// =============================================================
		// FILTERS
		// =============================================================

		filters: [
			{
				fieldname: "group_by",
				label: __("Group By"),
				fieldtype: "Select",
				options:
					"Lead Owner\nLead Stage\nLead Status\nWorkflow State\nSource\nAging Bucket\nCreated Month",
				default: "Lead Owner",
				reqd: 1
			},
			{
				fieldname: "year",
				label: __("Year"),
				fieldtype: "Int",
				default: new Date().getFullYear()
			},
			{
				fieldname: "lead_owner",
				label: __("Sales Team (Lead Owner)"),
				fieldtype: "Link",
				options: "User"
			},
			{
				fieldname: "followup_health",
				label: __("Follow-up Health"),
				fieldtype: "Select",
				options: "\nCritical\nStale\nActive\nClosed"
			},
			{
				fieldname: "workflow_state",
				label: __("Workflow State"),
				fieldtype: "Select",
				options: ""
			},
			{
				fieldname: "lead_stage",
				label: __("Lead Stage"),
				fieldtype: "Select",
				options: ""
			},
			{
				fieldname: "lead_status",
				label: __("Lead Status"),
				fieldtype: "Select",
				options: ""
			}
		],


		// =============================================================
		// ONLOAD
		// =============================================================

		onload: function (report) {

			// ---------------------------------------------------------
			// FILTER STYLING
			// ---------------------------------------------------------

			if (!document.getElementById("lms-style")) {

				const st = document.createElement("style");
				st.id = "lms-style";

				st.textContent = `
				.lms-filters {
					display: grid !important;
					grid-template-columns: repeat(4, minmax(0, 1fr));
					gap: 10px 14px;
					align-items: end;
					width: 100%;
				}

				@media (max-width: 1100px) {
					.lms-filters {
						grid-template-columns: repeat(3, minmax(0, 1fr));
					}
				}

				@media (max-width: 640px) {
					.lms-filters {
						grid-template-columns: repeat(2, minmax(0, 1fr));
					}
				}

				.lms-filters > .frappe-control {
					position: relative;
					width: auto !important;
					max-width: none !important;
					min-width: 0;
					margin: 16px 0 0 0 !important;
					padding: 0 !important;
					float: none !important;
					flex: none !important;
				}

				.lms-filters > .frappe-control[data-label]:not([data-fieldtype="Check"])::before {
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

				.lms-filters > .frappe-control[data-fieldtype="Check"] {
					padding-bottom: 6px !important;
				}

				.lms-filters .form-control::placeholder {
					color: transparent;
				}

				.lms-filters .frappe-control [class*="placeholder"] {
					display: none !important;
				}

				.lms-filters .frappe-control .help-box {
					display: none;
				}

				.lms-drill {
					cursor: pointer;
					font-weight: 600;
					text-decoration: underline;
				}

				.lms-drill:hover {
					opacity: 0.75;
				}
			`;

				document.head.appendChild(st);
			}

			const first = (report.filters || [])[0];

			if (first && first.$wrapper) {
				first.$wrapper.parent().addClass("lms-filters");
			}

			(report.filters || []).forEach((filter) => {
				if (filter.$wrapper) {
					filter.$wrapper.attr("data-label", filter.df.label);
				}
			});


			// ---------------------------------------------------------
			// FIELD METADATA
			// ---------------------------------------------------------

			const has_custom_lead_status = frappe.meta.has_field(
				"Lead",
				"custom_lead_status"
			);


			// ---------------------------------------------------------
			// GENERIC DROPDOWN LOADER
			// ---------------------------------------------------------

			const load_field_options = (filter_name, field_name) => {

				const filter = report.get_filter(filter_name);

				if (!filter) {
					console.error(
						"LMS: Filter not found:",
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
						"LMS: Lead field not found:",
						field_name
					);
					return;
				}


				// Select field: use DocType metadata.

				if (field_meta.fieldtype === "Select") {

					const options = (field_meta.options || "")
						.split("\n")
						.map(value => value.trim())
						.filter(Boolean);

					if (!options.length) {
						console.warn(
							"LMS: No Select options found:",
							field_name
						);
						return;
					}

					filter.df.options = "\n" + options.join("\n");
					filter.refresh();

					console.log(
						"LMS: Metadata options loaded:",
						filter_name,
						options
					);

					return;
				}


				// Other field types: fetch distinct existing values.

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
								"LMS: No values found:",
								field_name
							);
							return;
						}

						filter.df.options = "\n" + values.join("\n");
						filter.refresh();

						console.log(
							"LMS: Database options loaded:",
							filter_name,
							values
						);
					},

					error: (error) => {
						console.error(
							"LMS: Failed loading options:",
							field_name,
							error
						);
					}
				});
			};


			// ---------------------------------------------------------
			// LEAD STAGE
			// Summary Python filter key: lead_stage
			// Database field: Lead.status
			// ---------------------------------------------------------

			load_field_options(
				"lead_stage",
				"status"
			);


			// ---------------------------------------------------------
			// LEAD STATUS
			// Summary Python filter key: lead_status
			// Database field: Lead.custom_lead_status
			// ---------------------------------------------------------

			if (has_custom_lead_status) {

				load_field_options(
					"lead_status",
					"custom_lead_status"
				);

			} else {

				// Without the custom field, the Python report falls back
				// to the standard Lead.status field.

				load_field_options(
					"lead_status",
					"status"
				);

				// Avoid displaying two filters for the same field.
				report.toggle_filter_display(
					"lead_stage",
					true
				);
			}


			// ---------------------------------------------------------
			// WORKFLOW STATE
			// ---------------------------------------------------------

			const set_workflow_options = (states) => {

				const filter = report.get_filter("workflow_state");

				if (!filter || !states.length) {
					return;
				}

				filter.df.options = "\n" + states.join("\n");
				filter.refresh();

				console.log(
					"LMS: Workflow states loaded:",
					states
				);
			};


			const load_workflow_fallback = () => {

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
						load_workflow_fallback();
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
								load_workflow_fallback();
							}
						},

						error: load_workflow_fallback
					});
				},

				error: load_workflow_fallback
			});


			// =========================================================
			// QUICK VIEWS
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

					__("Quick Views")
				);
			};


			quick("By Sales Person", {
				group_by: "Lead Owner"
			});

			quick("By Lead Stage", {
				group_by: "Lead Stage"
			});

			quick("By Source", {
				group_by: "Source"
			});

			quick("By Workflow State", {
				group_by: "Workflow State"
			});

			quick("By Aging Bucket", {
				group_by: "Aging Bucket"
			});

			quick("Monthly Trend", {
				group_by: "Created Month"
			});


			// Clear filters button.

			report.page.add_inner_button(
				__("Clear Filters"),

				() => {

					clear_all();

					setTimeout(() => {
						report.refresh();
					}, 300);
				},

				__("Quick Views")
			);


			// =========================================================
			// DRILL-DOWN: SUMMARY -> LEAD DATA QUALITY MONITOR
			// =========================================================

			const FIELD_FOR = {

				"Lead Owner": "lead_owner",

				// Summary lead_stage -> list report status.
				"Lead Stage": "status",

				// Summary lead_status -> list report lead_status.
				"Lead Status": has_custom_lead_status
					? "lead_status"
					: "status",

				"Workflow State": "workflow_state",

				"Source": "source",

				"Aging Bucket": "aging_bucket"
			};


			report.page.main
				.off("click.lms")
				.on(
					"click.lms",
					".lms-drill",
					function (event) {

						event.preventDefault();

						const $link = $(this);

						const group = $link.attr("data-g");
						const health = $link.attr("data-h");

						const group_by = report.get_filter_value(
							"group_by"
						);

						const options = {
							scope: "All Leads"
						};


						// -------------------------------------------------
						// Carry over active report filters.
						// -------------------------------------------------

						[
							"year",
							"lead_owner",
							"lead_stage",
							"lead_status",
							"workflow_state"
						].forEach((key) => {

							const value = report.get_filter_value(key);

							if (value) {

								// Translate summary filters to list filters.
								if (key === "lead_stage") {
									options.status = value;
								} else if (
									key === "lead_status" &&
									!has_custom_lead_status
								) {
									options.status = value;
								} else {
									options[key] = value;
								}
							}
						});


						// Carry over follow-up health.
						const current_health = report.get_filter_value(
							"followup_health"
						);

						if (current_health) {
							options.followup_health = current_health;
						}


						// -------------------------------------------------
						// Apply clicked group.
						// -------------------------------------------------

						if (group && group !== "TOTAL") {

							// Created Month: use date range.
							if (group_by === "Created Month") {

								const year = parseInt(
									group.slice(0, 4),
									10
								);

								const month = parseInt(
									group.slice(5, 7),
									10
								);

								const last_day = new Date(
									year,
									month,
									0
								).getDate();

								options.year = year;

								options.from_date =
									group + "-01";

								options.to_date =
									group +
									"-" +
									String(last_day).padStart(2, "0");

							} else if (FIELD_FOR[group_by]) {

								const target_field = FIELD_FOR[group_by];

								options[target_field] = group;
							}
						}


						// -------------------------------------------------
						// Apply clicked health column.
						// -------------------------------------------------

						if (health) {
							options.followup_health = health;
						}


						// -------------------------------------------------
						// DQ drill-down.
						// -------------------------------------------------

						if ($link.attr("data-dq")) {

							options.open_only = 1;
							options.dq_to = 99.99;
						}


						console.log(
							"LMS: Drill-down route options:",
							options
						);


						frappe.route_options = options;

						frappe.set_route(
							"query-report",
							"Lead Data Quality Monitor"
						);
					}
				);
		},


		// =============================================================
		// FORMATTER
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


			const is_total = data.grp === "TOTAL";


			const colour = (color) => {
				return `<span style="color:${color};font-weight:600">${value}</span>`;
			};


			const escape_html = frappe.utils.escape_html;


			const link = (text, health, extra) => {

				const group = is_total
					? ""
					: escape_html(String(data.grp || ""));

				return `
				<a
					class="lms-drill"
					data-g="${group}"
					data-h="${health || ""}"
					${extra || ""}
				>
					${text}
				</a>
			`;
			};


			// ---------------------------------------------------------
			// GROUP COLUMN
			// ---------------------------------------------------------

			if (column.fieldname === "grp") {

				if (is_total) {
					return `<b>${__("TOTAL")}</b>`;
				}

				if (
					data.grp === "Unassigned" ||
					data.grp === "(none)"
				) {
					return escape_html(data.grp);
				}

				return link(
					escape_html(data.grp),
					""
				);
			}


			// ---------------------------------------------------------
			// TOTAL ROW
			// ---------------------------------------------------------

			if (is_total) {

				if (column.fieldname === "total") {
					return `<b>${link(value, "")}</b>`;
				}

				if (
					column.fieldname === "critical" &&
					data.critical > 0
				) {
					return `<b>${link(value, "Critical")}</b>`;
				}

				if (
					column.fieldname === "stale" &&
					data.stale > 0
				) {
					return `<b>${link(value, "Stale")}</b>`;
				}

				return `<b>${value}</b>`;
			}


			// ---------------------------------------------------------
			// GROUP ROWS
			// ---------------------------------------------------------

			const unlinkable =
				data.grp === "Unassigned" ||
				data.grp === "(none)";


			if (
				column.fieldname === "total" &&
				!unlinkable
			) {
				return link(value, "");
			}


			if (column.fieldname === "critical") {

				return data.critical > 0
					? `<span style="color:#d92d20;font-weight:600">${unlinkable
						? value
						: link(value, "Critical")
					}</span>`
					: value;
			}


			if (column.fieldname === "stale") {

				return data.stale > 0
					? `<span style="color:#dc6803;font-weight:600">${unlinkable
						? value
						: link(value, "Stale")
					}</span>`
					: value;
			}


			if (column.fieldname === "active") {
				return colour("#039855");
			}


			if (column.fieldname === "closed") {
				return colour("#667085");
			}


			if (
				column.fieldname === "crit_pct" &&
				data.crit_pct >= 30
			) {
				return colour("#d92d20");
			}


			if (
				column.fieldname === "blocked" &&
				data.blocked > 0
			) {
				return colour("#b42318");
			}


			if (
				column.fieldname === "low_dq" &&
				data.low_dq > 0
			) {
				return colour("#d92d20");
			}


			return value;
		}
	};
