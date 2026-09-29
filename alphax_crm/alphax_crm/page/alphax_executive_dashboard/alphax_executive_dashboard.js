// AlphaX Executive Dashboard — a single management-facing screen: KPI
// tiles, open pipeline by stage, lead source breakdown, a 6-month trend,
// and a top-5 leaderboard. Built as a custom Desk Page (not the stock
// Number Card / Dashboard Chart widgets) so the layout and styling can be
// distinct rather than the same tile grid every other Frappe dashboard
// uses — charts render with frappe.Chart, already bundled in the desk, so
// nothing extra needs to load.
frappe.pages["alphax-executive-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("AlphaX Executive Dashboard"),
		single_column: true,
	});

	const state = { from_date: null, to_date: null, territory: null };

	page.add_field({
		fieldname: "from_date",
		label: __("From"),
		fieldtype: "Date",
		change() {
			state.from_date = this.get_value();
			alphax_dashboard_load(page, state);
		},
	});
	page.add_field({
		fieldname: "to_date",
		label: __("To"),
		fieldtype: "Date",
		default: frappe.datetime.get_today(),
		change() {
			state.to_date = this.get_value();
			alphax_dashboard_load(page, state);
		},
	});
	page.add_field({
		fieldname: "territory",
		label: __("Territory"),
		fieldtype: "Link",
		options: "Territory",
		change() {
			state.territory = this.get_value();
			alphax_dashboard_load(page, state);
		},
	});
	page.set_primary_action(__("Refresh"), () => alphax_dashboard_load(page, state), "refresh");

	page.main.html(`
		<div id="alphax-dash-root" style="padding: 4px 2px 24px;">
			<div id="alphax-dash-kpis" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 22px;"></div>
			<div style="display:grid; grid-template-columns: 1.3fr 1fr; gap: 16px; margin-bottom: 16px;">
				<div class="alphax-dash-card">
					<div class="alphax-dash-card-title">${__("Open Pipeline by Stage")}</div>
					<div id="alphax-dash-pipeline-chart"></div>
				</div>
				<div class="alphax-dash-card">
					<div class="alphax-dash-card-title">${__("Top Lead Sources (period)")}</div>
					<div id="alphax-dash-source-chart"></div>
				</div>
			</div>
			<div class="alphax-dash-card" style="margin-bottom:16px;">
				<div class="alphax-dash-card-title">${__("6-Month Trend: New PreLeads vs Deals Won")}</div>
				<div id="alphax-dash-trend-chart"></div>
			</div>
			<div class="alphax-dash-card">
				<div class="alphax-dash-card-title">${__("Top 5 — Won Value (period)")}</div>
				<div id="alphax-dash-leaderboard"></div>
			</div>
		</div>
		<style>
			.alphax-dash-card {
				background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd);
				border-radius: 10px; padding: 16px;
			}
			.alphax-dash-card-title { font-weight: 600; margin-bottom: 10px; font-size: 13px; color: var(--text-muted, #8d99a6); text-transform: uppercase; letter-spacing: .03em; }
			.alphax-kpi {
				border-radius: 10px; padding: 16px; color: #fff;
				background: linear-gradient(135deg, #2490ef, #1b6fc9);
			}
			.alphax-kpi.alert { background: linear-gradient(135deg, #e24c4c, #b93030); }
			.alphax-kpi .alphax-kpi-value { font-size: 24px; font-weight: 700; line-height: 1.2; }
			.alphax-kpi .alphax-kpi-label { font-size: 12px; opacity: .85; margin-top: 4px; }
			#alphax-dash-leaderboard table { width:100%; font-size: 13px; }
			#alphax-dash-leaderboard td, #alphax-dash-leaderboard th { padding: 6px 10px; }
		</style>
	`);

	alphax_dashboard_load(page, state);
};

function alphax_dashboard_load(page, state) {
	frappe.call({
		method: "alphax_crm.api.dashboard.get_dashboard_data",
		args: { from_date: state.from_date, to_date: state.to_date, territory: state.territory },
		freeze: true,
		callback: (r) => {
			const data = r.message;
			if (!data) return;
			alphax_dashboard_render(data);
		},
		error: (r) => {
			$("#alphax-dash-root").html(
				`<div class="text-muted" style="padding: 40px; text-align:center;">${__("Could not load the dashboard. You may need the Sales Manager role.")}</div>`
			);
		},
	});
}

function alphax_dashboard_render(data) {
	const $kpis = $("#alphax-dash-kpis").empty();
	(data.kpis || []).forEach((k) => {
		const value = k.is_currency ? format_currency(k.value) : k.value;
		$kpis.append(`
			<div class="alphax-kpi ${k.alert ? "alert" : ""}">
				<div class="alphax-kpi-value">${frappe.utils.escape_html(String(value))}</div>
				<div class="alphax-kpi-label">${frappe.utils.escape_html(k.label)}</div>
			</div>
		`);
	});

	alphax_dashboard_chart("alphax-dash-pipeline-chart", data.pipeline_chart, "bar");
	alphax_dashboard_chart("alphax-dash-source-chart", data.source_chart, "bar");
	alphax_dashboard_trend_chart("alphax-dash-trend-chart", data.trend_chart);
	alphax_dashboard_leaderboard(data.leaderboard || []);
}

function alphax_dashboard_chart(el_id, chart, type) {
	const el = document.getElementById(el_id);
	if (!el) return;
	el.innerHTML = "";
	if (!chart || !chart.labels || !chart.labels.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:30px 0; text-align:center;">${__("No data in this period.")}</div>`;
		return;
	}
	new frappe.Chart(el, {
		data: { labels: chart.labels, datasets: [{ values: chart.values }] },
		type,
		height: 220,
		colors: ["#2490ef"],
	});
}

function alphax_dashboard_trend_chart(el_id, chart) {
	const el = document.getElementById(el_id);
	if (!el) return;
	el.innerHTML = "";
	if (!chart || !chart.labels || !chart.labels.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:30px 0; text-align:center;">${__("No data.")}</div>`;
		return;
	}
	new frappe.Chart(el, {
		data: {
			labels: chart.labels,
			datasets: [
				{ name: __("New PreLeads"), values: chart.preleads },
				{ name: __("Deals Won"), values: chart.won },
			],
		},
		type: "line",
		height: 240,
		colors: ["#2490ef", "#2ecc71"],
		lineOptions: { regionFill: 0, hideDots: 0 },
	});
}

function alphax_dashboard_leaderboard(rows) {
	const $el = $("#alphax-dash-leaderboard").empty();
	if (!rows.length) {
		$el.html(`<div class="text-muted small" style="padding:10px 0;">${__("No won deals in this period.")}</div>`);
		return;
	}
	let html = `<table><thead><tr>
		<th>${__("Owner")}</th><th>${__("Deals Won")}</th><th>${__("Value")}</th>
	</tr></thead><tbody>`;
	rows.forEach((r) => {
		html += `<tr>
			<td>${frappe.utils.escape_html(r.owner)}</td>
			<td>${r.count}</td>
			<td>${format_currency(r.value)}</td>
		</tr>`;
	});
	html += "</tbody></table>";
	$el.html(html);
}
