// AlphaX BI Dashboard — one master screen pulling together the whole
// "AlphaX ... (BI)" report family (Lead Stage Tracker, Pipeline Aging, Lost
// Reason Breakdown, Quotation Value by Business Unit, Stage Conversion,
// Sales Person Performance, Source Performance) behind a single shared
// filter bar and a row of tabs, instead of opening each report on its own
// from the Report List one at a time.
//
// One frappe.call fetches every report's (summary/chart/table) in a single
// round trip (alphax_crm.api.bi_dashboard.get_bi_dashboard_data); switching
// tabs afterwards is pure client-side show/hide, no extra server call,
// same pattern AlphaX Executive Dashboard already uses for its own charts
// (frappe.Chart, already bundled in the desk).

// Each tab carries a short accent color so the tab bar, its KPI cards and
// its chart read as one coordinated block per report, not an undifferentiated
// row of identical blue tiles.
const ALPHAX_BI_TABS = [
	["lead_stage_tracker", __("Lead Stage Tracker"), "#2490ef"],
	["pipeline_aging", __("Pipeline Aging"), "#7c3aed"],
	["stage_conversion", __("Stage Conversion"), "#0ea5a4"],
	["lost_reason_breakdown", __("Lost Reason Breakdown"), "#e24c4c"],
	["quotation_value_by_bu", __("Quotation Value by Business Unit"), "#f2994a"],
	["sales_person_performance", __("Sales Person Performance"), "#2ecc71"],
	["source_performance", __("Source Performance"), "#3b5bdb"],
];

frappe.pages["alphax-bi-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("AlphaX BI Dashboard"),
		single_column: true,
	});

	const state = {
		from_date: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		to_date: frappe.datetime.get_today(),
		as_of_date: frappe.datetime.get_today(),
		period_type: "Monthly",
		compare_mode: "None",
		years_back: "1",
		lead_owner: null,
		source: null,
		city: null,
		country: null,
		custom_business_line_: null,
		custom_sub_service: null,
	};

	const reload = () => {
		alphax_bi_dashboard_load(page, state);
		alphax_bi_explorer_load(state);
	};

	page.add_field({
		fieldname: "from_date",
		label: __("From Date"),
		fieldtype: "Date",
		default: state.from_date,
		description: __("Defaults to one month back. Leave From/To Date blank to use Period Type + As Of Date instead."),
		change() {
			state.from_date = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "to_date",
		label: __("To Date"),
		fieldtype: "Date",
		default: state.to_date,
		change() {
			state.to_date = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "as_of_date",
		label: __("As Of Date"),
		fieldtype: "Date",
		default: state.as_of_date,
		description: __("Only used when From Date/To Date are blank."),
		change() {
			state.as_of_date = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "period_type",
		label: __("Period Type"),
		fieldtype: "Select",
		options: "Daily\nWeekly\nMonthly\nQuarterly\nHalf-Yearly\nYearly",
		default: state.period_type,
		description: __("Only used when From Date/To Date are blank."),
		change() {
			state.period_type = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "compare_mode",
		label: __("Compare Mode"),
		fieldtype: "Select",
		options: "None\nSame Period Last Year\nSame Quarter Last Year\nFull Last Year",
		default: state.compare_mode,
		change() {
			state.compare_mode = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "years_back",
		label: __("Years Back"),
		fieldtype: "Select",
		options: "1\n2\n3",
		default: state.years_back,
		change() {
			state.years_back = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "lead_owner",
		label: __("Sales Person"),
		fieldtype: "Link",
		options: "User",
		change() {
			state.lead_owner = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "source",
		label: __("Source"),
		fieldtype: "Link",
		options: "Lead Source",
		change() {
			state.source = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "city",
		label: __("City"),
		fieldtype: "Data",
		change() {
			state.city = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "country",
		label: __("Country"),
		fieldtype: "Link",
		options: "Country",
		change() {
			state.country = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "custom_business_line_",
		label: __("Business Unit"),
		fieldtype: "Select",
		options: "",
		description: __("Populated from the Business Unit values already in use on this site's Leads (there's no separate master list for it)."),
		change() {
			state.custom_business_line_ = this.get_value();
			// Sub Service choices depend on the Business Unit, same as on the Lead form.
			state.custom_sub_service = null;
			const ss = page.fields_dict.custom_sub_service;
			if (ss) ss.set_value("");
			alphax_bi_load_sub_services(page, state.custom_business_line_);
			reload();
		},
	});
	page.add_field({
		fieldname: "custom_sub_service",
		label: __("Sub Service"),
		fieldtype: "Select",
		options: "",
		description: __("Sub services for the chosen Business Unit (all of them if none is chosen)."),
		change() {
			state.custom_sub_service = this.get_value();
			reload();
		},
	});
	page.set_primary_action(__("Refresh"), reload, "refresh");

	// Business Unit has no master doctype to search (see the filter's own
	// description), so its dropdown is filled in here from whatever
	// distinct values are actually on this site's Leads.
	frappe.call({
		method: "alphax_crm.crm.bi_report.get_business_unit_options",
		callback: function (r) {
			const field = page.fields_dict.custom_business_line_;
			if (!field) return;
			const values = r.message || [];
			field.df.options = [""].concat(values).join("\n");
			field.refresh();
		},
	});

	alphax_bi_load_sub_services(page, null);

	let tabs_html = `<div class="alphax-bi-tabbar">`;
	ALPHAX_BI_TABS.forEach(([id, label, color], i) => {
		tabs_html += `
			<div class="alphax-bi-tab${i === 0 ? " active" : ""}" data-tab="${id}" style="--tab-accent:${color};">
				<span class="alphax-bi-tab-dot"></span>${frappe.utils.escape_html(label)}
			</div>`;
	});
	tabs_html += `
		<div class="alphax-bi-tab" data-tab="explorer" style="--tab-accent:#0f766e;">
			<span class="alphax-bi-tab-dot"></span>${__("Pivot Explorer")}
		</div>
	</div>`;

	let panes_html = "";
	ALPHAX_BI_TABS.forEach(([id, label, color], i) => {
		panes_html += `
			<div class="alphax-bi-pane" id="alphax-bi-pane-${id}" style="display:${i === 0 ? "block" : "none"};">
				<div id="alphax-bi-kpis-${id}" class="alphax-bi-kpis" style="--pane-accent:${color};"></div>
				<div class="alphax-dash-card" style="margin-bottom:16px; --pane-accent:${color};">
					<div class="alphax-dash-card-title">${__("Chart")} — ${frappe.utils.escape_html(label)}</div>
					<div id="alphax-bi-chart-${id}"></div>
				</div>
				<div class="alphax-dash-card" style="--pane-accent:${color};">
					<div class="alphax-dash-card-title">${__("Detail")}</div>
					<div id="alphax-bi-table-${id}"></div>
				</div>
			</div>`;
	});

	panes_html += alphax_bi_explorer_pane_html();

	page.main.html(`
		<div id="alphax-bi-root" style="padding: 0 2px 24px;">
			<div class="alphax-bi-hero">
				<div class="alphax-bi-hero-text">
					<div class="alphax-bi-hero-title">${__("AlphaX BI Dashboard")}</div>
					<div class="alphax-bi-hero-sub">${__("One screen for all AlphaX BI reports. Set the filters once and every tab updates together.")}</div>
				</div>
				<div class="alphax-bi-hero-meta">
					<span id="alphax-bi-last-update">${__("Loading…")}</span>
				</div>
			</div>
			${tabs_html}
			<div id="alphax-bi-message" class="text-muted small" style="margin: 10px 2px 16px;"></div>
			${panes_html}
		</div>
		<style>
			.alphax-bi-hero {
				display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;
				background: linear-gradient(120deg, #1f3b73 0%, #2490ef 100%);
				color:#fff; border-radius: 12px; padding: 18px 22px; margin: 6px 0 16px;
				box-shadow: 0 6px 18px rgba(31,59,115,0.18);
			}
			.alphax-bi-hero-title { font-size: 20px; font-weight: 700; letter-spacing: .01em; }
			.alphax-bi-hero-sub { font-size: 12.5px; opacity: .85; margin-top: 3px; }
			.alphax-bi-hero-meta { font-size: 12px; opacity: .9; white-space: nowrap; }
			.alphax-dash-card {
				background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd);
				border-top: 3px solid var(--pane-accent, #2490ef);
				border-radius: 10px; padding: 16px;
				box-shadow: 0 1px 3px rgba(17,24,39,0.04);
				transition: box-shadow .15s ease;
			}
			.alphax-dash-card:hover { box-shadow: 0 4px 14px rgba(17,24,39,0.08); }
			.alphax-dash-card-title { font-weight: 600; margin-bottom: 10px; font-size: 13px; color: var(--text-muted, #8d99a6); text-transform: uppercase; letter-spacing: .03em; }
			.alphax-bi-tabbar { display:flex; flex-wrap:wrap; gap:4px; border-bottom: 1px solid var(--border-color, #d1d8dd); margin-bottom: 4px; }
			.alphax-bi-tab {
				display:flex; align-items:center; gap:7px;
				padding: 9px 14px; cursor: pointer; font-size: 13px; font-weight: 500;
				color: var(--text-muted, #8d99a6); border-bottom: 2px solid transparent;
				border-radius: 6px 6px 0 0; transition: background .12s ease, color .12s ease;
			}
			.alphax-bi-tab:hover { color: var(--text-color, #1a1a1a); background: var(--bg-light-gray, #f4f5f6); }
			.alphax-bi-tab.active { color: var(--text-color, #1a1a1a); border-bottom-color: var(--tab-accent, #2490ef); font-weight: 600; }
			.alphax-bi-tab-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tab-accent, #2490ef); flex: none; }
			.alphax-bi-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 16px 0; }
			.alphax-kpi {
				position: relative; overflow: hidden;
				border-radius: 10px; padding: 16px 16px 16px 18px; color: #fff;
				background: linear-gradient(135deg, var(--pane-accent, #2490ef), rgba(0,0,0,0.18));
				box-shadow: 0 2px 8px rgba(17,24,39,0.10);
			}
			.alphax-kpi.green { background: linear-gradient(135deg, #2ecc71, #1f9e57); }
			.alphax-kpi.red { background: linear-gradient(135deg, #e24c4c, #b93030); }
			.alphax-kpi.grey { background: linear-gradient(135deg, #8d99a6, #6b7680); }
			.alphax-kpi .alphax-kpi-value { font-size: 23px; font-weight: 700; line-height: 1.2; }
			.alphax-kpi .alphax-kpi-label { font-size: 12px; opacity: .88; margin-top: 4px; }
			.alphax-bi-table { width:100%; font-size: 13px; border-collapse: collapse; }
			.alphax-bi-table th, .alphax-bi-table td { padding: 7px 10px; border-bottom: 1px solid var(--border-color, #eaeef0); text-align: left; }
			.alphax-bi-table th { color: var(--text-muted, #8d99a6); font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: .02em; }
			.alphax-bi-table tbody tr:hover td { background: var(--bg-light-gray, #f8f9fb); }
		</style>
	`);

	$(wrapper).on("click", ".alphax-bi-tab", function () {
		const tab = $(this).data("tab");
		$(wrapper).find(".alphax-bi-tab").removeClass("active");
		$(this).addClass("active");
		$(wrapper).find(".alphax-bi-pane").hide();
		$(wrapper).find(`#alphax-bi-pane-${tab}`).show();
		const active_tab_data = window.alphax_bi_last_data && window.alphax_bi_last_data[tab];
		$("#alphax-bi-message").text((active_tab_data && active_tab_data.message) || "");
	});

	alphax_bi_explorer_init(state);
	reload();
};

function alphax_bi_load_sub_services(page, business_unit) {
	frappe.call({
		method: "alphax_crm.crm.bi_report.get_sub_service_options",
		args: { business_unit: business_unit || null },
		callback: function (r) {
			const field = page.fields_dict.custom_sub_service;
			if (!field) return;
			field.df.options = [""].concat(r.message || []).join("\n");
			field.refresh();
		},
	});
}

function alphax_bi_dashboard_load(page, state) {
	frappe.call({
		method: "alphax_crm.api.bi_dashboard.get_bi_dashboard_data",
		args: state,
		freeze: true,
		callback: (r) => {
			const data = r.message;
			if (!data) return;
			alphax_bi_dashboard_render(data);
		},
		error: () => {
			$("#alphax-bi-root").html(
				`<div class="text-muted" style="padding: 40px; text-align:center;">${__("Could not load the dashboard. You may need the Sales User, Sales Manager or System Manager role.")}</div>`
			);
		},
	});
}

function alphax_bi_dashboard_render(data) {
	// Stashed so the tab-click handler can restore a tab's status message
	// without re-fetching data just to switch tabs.
	window.alphax_bi_last_data = data;
	$("#alphax-bi-last-update").text(__("Last updated") + ": " + frappe.datetime.now_time());
	const messages = [];
	ALPHAX_BI_TABS.forEach(([id]) => {
		const tab = data[id];
		if (!tab) return;
		if (tab.error) {
			$(`#alphax-bi-kpis-${id}`).empty();
			$(`#alphax-bi-chart-${id}`).html(`<div class="text-muted small" style="padding:20px 0; text-align:center;">${frappe.utils.escape_html(tab.error)}</div>`);
			$(`#alphax-bi-table-${id}`).empty();
			return;
		}
		if (tab.message) messages.push(`${tab.label}: ${tab.message}`);
		alphax_bi_render_kpis(`alphax-bi-kpis-${id}`, tab.summary || []);
		alphax_bi_render_chart(`alphax-bi-chart-${id}`, tab.chart);
		alphax_bi_render_table(`alphax-bi-table-${id}`, tab.columns || [], tab.data || []);
	});
	// Keep the message strip short -- the active tab's own message is what
	// matters most, so show just that one plus a hint the others have more.
	const active_id = $(".alphax-bi-tab.active").data("tab") || ALPHAX_BI_TABS[0][0];
	const active_tab = data[active_id];
	$("#alphax-bi-message").text((active_tab && active_tab.message) || "");
}

function alphax_bi_render_kpis(el_id, summary) {
	const $el = $(`#${el_id}`).empty();
	summary.forEach((k) => {
		const value = k.datatype === "Currency" ? format_currency(k.value) : k.value;
		const cls = k.indicator === "green" ? "green" : k.indicator === "red" ? "red" : k.indicator === "blue" ? "" : "grey";
		$el.append(`
			<div class="alphax-kpi ${cls}">
				<div class="alphax-kpi-value">${frappe.utils.escape_html(String(value))}</div>
				<div class="alphax-kpi-label">${frappe.utils.escape_html(k.label)}</div>
			</div>
		`);
	});
}

function alphax_bi_render_chart(el_id, chart) {
	const el = document.getElementById(el_id);
	if (!el) return;
	el.innerHTML = "";
	if (!chart || !chart.data || !chart.data.labels || !chart.data.labels.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:30px 0; text-align:center;">${__("No data for this filter selection.")}</div>`;
		return;
	}
	new frappe.Chart(el, {
		data: chart.data,
		type: chart.type || "bar",
		height: 240,
		colors: ["#2490ef", "#2ecc71", "#e24c4c"],
	});
}

function alphax_bi_format_cell(value, col) {
	if (value === null || value === undefined || value === "") return "<span class=\"text-muted\">—</span>";
	const ft = col.fieldtype;
	if (ft === "Currency") return format_currency(value);
	if (ft === "Percent") return `${value}%`;
	if (ft === "Float") return typeof value === "number" ? value.toFixed(col.precision || 1) : frappe.utils.escape_html(String(value));
	return frappe.utils.escape_html(String(value));
}

function alphax_bi_render_table(el_id, columns, data) {
	const el = document.getElementById(el_id);
	if (!el) return;
	if (!data.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:20px 0; text-align:center;">${__("No data for this filter selection.")}</div>`;
		return;
	}
	let html = '<div style="overflow-x:auto;"><table class="alphax-bi-table"><thead><tr>';
	columns.forEach((c) => {
		html += `<th>${frappe.utils.escape_html(c.label)}</th>`;
	});
	html += "</tr></thead><tbody>";
	data.forEach((row) => {
		html += "<tr>";
		columns.forEach((c) => {
			html += `<td>${alphax_bi_format_cell(row[c.fieldname], c)}</td>`;
		});
		html += "</tr>";
	});
	html += "</tbody></table></div>";
	el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Pivot Explorer -- pick Rows / Columns / Measure / Chart type, like a
// Power BI / Excel pivot. Uses the same shared filter bar as the other tabs.
// ---------------------------------------------------------------------------
const ALPHAX_PIVOT_COLORS = ["#2490ef", "#2ecc71", "#e24c4c", "#f2994a", "#7c3aed", "#0ea5a4", "#3b5bdb", "#f472b6", "#84cc16", "#64748b"];
let alphax_pivot_ready = false;
let alphax_pivot_last = null;

function alphax_bi_explorer_pane_html() {
	return `
		<div class="alphax-bi-pane" id="alphax-bi-pane-explorer" style="display:none;">
			<div class="alphax-dash-card" style="margin: 16px 0; --pane-accent:#0f766e;">
				<div class="alphax-dash-card-title">${__("Build your own view")}</div>
				<div class="alphax-pivot-controls">
					<label>${__("Rows")}<select id="alphax-pv-rows" class="form-control input-sm"></select></label>
					<label>${__("Columns")}<select id="alphax-pv-cols" class="form-control input-sm"></select></label>
					<label>${__("Measure")}<select id="alphax-pv-measure" class="form-control input-sm"></select></label>
					<label>${__("Chart")}<select id="alphax-pv-chart" class="form-control input-sm">
						<option value="bar">${__("Bar")}</option>
						<option value="line">${__("Line")}</option>
						<option value="pie">${__("Pie")}</option>
						<option value="donut">${__("Donut")}</option>
						<option value="percentage">${__("Percentage")}</option>
					</select></label>
					<button class="btn btn-default btn-sm" id="alphax-pv-csv">${__("Download CSV")}</button>
				</div>
				<div class="text-muted small" id="alphax-pv-note" style="margin-top:8px;"></div>
			</div>
			<div class="alphax-dash-card" style="margin-bottom:16px; --pane-accent:#0f766e;">
				<div class="alphax-dash-card-title">${__("Chart")}</div>
				<div id="alphax-pv-chartbox"></div>
			</div>
			<div class="alphax-dash-card" style="--pane-accent:#0f766e;">
				<div class="alphax-dash-card-title">${__("Pivot table")}</div>
				<div id="alphax-pv-table"></div>
			</div>
		</div>
		<style>
			.alphax-pivot-controls { display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end; }
			.alphax-pivot-controls label { display:flex; flex-direction:column; font-size:12px; color: var(--text-muted, #8d99a6); gap:4px; min-width:150px; }
			.alphax-bi-table tr.alphax-pv-total td { font-weight:700; border-top:2px solid var(--border-color, #d1d8dd); }
		</style>`;
}

function alphax_bi_explorer_init(state) {
	frappe.call({
		method: "alphax_crm.api.bi_dashboard.get_pivot_options",
		callback: function (r) {
			const opts = r.message || { dimensions: [], measures: [] };
			const dims = opts.dimensions.map((d) => `<option value="${d.id}">${frappe.utils.escape_html(d.label)}</option>`).join("");
			const has = (id) => opts.dimensions.some((d) => d.id === id);
			$("#alphax-pv-rows").html(dims).val(has("source") ? "source" : (opts.dimensions[0] || {}).id);
			$("#alphax-pv-cols").html(`<option value="">${__("(none)")}</option>` + dims).val("");
			$("#alphax-pv-measure").html(opts.measures.map((m) => `<option value="${m.id}">${frappe.utils.escape_html(m.label)}</option>`).join(""));
			$("#alphax-pv-rows, #alphax-pv-cols, #alphax-pv-measure, #alphax-pv-chart").on("change", () => alphax_bi_explorer_load(state));
			$("#alphax-pv-csv").on("click", alphax_bi_explorer_csv);
			alphax_pivot_ready = true;
			alphax_bi_explorer_load(state);
		},
	});
}

function alphax_bi_explorer_load(state) {
	if (!alphax_pivot_ready) return;
	frappe.call({
		method: "alphax_crm.api.bi_dashboard.get_pivot_data",
		args: {
			rows_dim: $("#alphax-pv-rows").val(),
			cols_dim: $("#alphax-pv-cols").val() || null,
			measure: $("#alphax-pv-measure").val(),
			from_date: state.from_date,
			to_date: state.to_date,
			lead_owner: state.lead_owner,
			source: state.source,
			city: state.city,
			country: state.country,
			custom_business_line_: state.custom_business_line_,
			custom_sub_service: state.custom_sub_service,
		},
		callback: (r) => {
			alphax_pivot_last = r.message;
			alphax_bi_explorer_render(r.message);
		},
	});
}

function alphax_bi_explorer_render(d) {
	if (!d) return;
	const is_pct = $("#alphax-pv-measure").val() === "win_rate";
	$("#alphax-pv-note").text(
		d.total_leads + " " + __("leads created in the selected dates match the filters.") + " " +
		d.row_label + (d.col_label ? " × " + d.col_label : "")
	);
	const box = document.getElementById("alphax-pv-chartbox");
	box.innerHTML = "";
	if (!d.rows.length) {
		box.innerHTML = `<div class="text-muted small" style="padding:30px 0; text-align:center;">${__("No data for this filter selection.")}</div>`;
		$("#alphax-pv-table").empty();
		return;
	}
	let type = $("#alphax-pv-chart").val();
	const multi = d.cols && d.cols.length;
	if (multi && (type === "pie" || type === "donut")) type = "bar";
	const top = d.rows.slice(0, 25);
	const datasets = multi
		? d.cols.map((c, ci) => ({ name: String(c), values: top.map((_r, ri) => d.matrix[ri][ci]) }))
		: [{ name: d.measure_label, values: top.map((_r, ri) => d.matrix[ri][0]) }];
	new frappe.Chart(box, {
		data: { labels: top.map(String), datasets: datasets },
		type: type,
		height: 300,
		colors: ALPHAX_PIVOT_COLORS,
		barOptions: { stacked: multi && type === "bar" ? 1 : 0 },
	});

	const cols = multi ? d.cols : [d.measure_label];
	const fmt = (v) => (is_pct ? v + "%" : String(v));
	let max = 0;
	d.matrix.forEach((line) => line.forEach((v) => { if (v > max) max = v; }));
	let html = '<div style="overflow-x:auto;"><table class="alphax-bi-table"><thead><tr>';
	html += `<th>${frappe.utils.escape_html(d.row_label)}</th>`;
	cols.forEach((c) => (html += `<th style="text-align:right;">${frappe.utils.escape_html(String(c))}</th>`));
	if (multi && !is_pct) html += `<th style="text-align:right;">${__("Total")}</th>`;
	html += "</tr></thead><tbody>";
	const col_totals = cols.map(() => 0);
	d.rows.forEach((r, ri) => {
		html += `<tr><td>${frappe.utils.escape_html(String(r))}</td>`;
		let row_total = 0;
		d.matrix[ri].forEach((v, ci) => {
			row_total += v;
			col_totals[ci] += v;
			const alpha = max ? (0.08 + 0.42 * (v / max)).toFixed(2) : 0;
			html += `<td style="text-align:right; background: rgba(15,118,110,${v ? alpha : 0});">${fmt(v)}</td>`;
		});
		if (multi && !is_pct) html += `<td style="text-align:right; font-weight:700;">${row_total}</td>`;
		html += "</tr>";
	});
	if (!is_pct) {
		html += `<tr class="alphax-pv-total"><td>${__("Total")}</td>`;
		col_totals.forEach((v) => (html += `<td style="text-align:right;">${v}</td>`));
		if (multi) html += `<td style="text-align:right;">${col_totals.reduce((a, b) => a + b, 0)}</td>`;
		html += "</tr>";
	}
	html += "</tbody></table></div>";
	document.getElementById("alphax-pv-table").innerHTML = html;
}

function alphax_bi_explorer_csv() {
	const d = alphax_pivot_last;
	if (!d || !d.rows.length) return;
	const cols = d.cols && d.cols.length ? d.cols : [d.measure_label];
	const esc = (v) => '"' + String(v).replace(/"/g, '""') + '"';
	const lines = [[d.row_label].concat(cols).map(esc).join(",")];
	d.rows.forEach((r, ri) => lines.push([esc(r)].concat(d.matrix[ri]).join(",")));
	const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = "alphax_pivot.csv";
	a.click();
}
