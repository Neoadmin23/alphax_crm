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
		custom_business_lead_unit: null,
	};

	const reload = () => alphax_bi_dashboard_load(page, state);

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
		fieldname: "custom_business_lead_unit",
		label: __("Business Unit"),
		fieldtype: "Select",
		options: "",
		description: __("Populated from the Business Unit values already in use on this site's Leads (there's no separate master list for it)."),
		change() {
			state.custom_business_lead_unit = this.get_value();
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
			const field = page.fields_dict.custom_business_lead_unit;
			if (!field) return;
			const values = r.message || [];
			field.df.options = [""].concat(values).join("\n");
			field.refresh();
		},
	});

	let tabs_html = `<div class="alphax-bi-tabbar">`;
	ALPHAX_BI_TABS.forEach(([id, label, color], i) => {
		tabs_html += `
			<div class="alphax-bi-tab${i === 0 ? " active" : ""}" data-tab="${id}" style="--tab-accent:${color};">
				<span class="alphax-bi-tab-dot"></span>${frappe.utils.escape_html(label)}
			</div>`;
	});
	tabs_html += `</div>`;

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

	page.main.html(`
		<div id="alphax-bi-root" style="padding: 0 2px 24px;">
			<div class="alphax-bi-hero">
				<div class="alphax-bi-hero-text">
					<div class="alphax-bi-hero-title">${__("AlphaX BI Dashboard")}</div>
					<div class="alphax-bi-hero-sub">${__("Every AlphaX BI report, one shared filter bar, side by side.")}</div>
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

	reload();
};

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
	$("#alphax-bi-last-update").text(__("Last updated: {0}").format(frappe.datetime.now_time()));
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
