(function () {
  "use strict";
  var API = "/api/method/";
  var TABS = [
    ["perf", "Lead Performance", "#2563eb"],
    ["lead_stage_tracker", "Lead Stage Tracker", "#2490ef"],
    ["pipeline_aging", "Pipeline Aging", "#7c3aed"],
    ["stage_conversion", "Stage Conversion", "#0ea5a4"],
    ["lost_reason_breakdown", "Lost Reason Breakdown", "#e24c4c"],
    ["quotation_value_by_bu", "Quotation Value by Business Unit", "#f2994a"],
    ["sales_person_performance", "Sales Person Performance", "#2ecc71"],
    ["source_performance", "Source Performance", "#3b5bdb"],
    ["explorer", "Pivot Explorer", "#0f766e"]
  ];
  var THEMES = {
    corporate: ["#2490ef", "#1f3b73", "#5ab0ff", "#7c3aed", "#0ea5a4", "#f2994a", "#e24c4c", "#2ecc71"],
    sunset: ["#ff7e5f", "#feb47b", "#e84a5f", "#ffcd3c", "#c44569", "#f8a5c2", "#ff9f43", "#ee5253"],
    forest: ["#2d6a4f", "#52b788", "#95d5b2", "#40916c", "#74c69d", "#1b4332", "#b7e4c7", "#588157"],
    neon: ["#00f5d4", "#f15bb5", "#fee440", "#9b5de5", "#00bbf9", "#ff006e", "#8338ec", "#3a86ff"],
    mono: ["#1f2937", "#4b5563", "#6b7280", "#9ca3af", "#d1d5db", "#374151", "#111827", "#e5e7eb"],
    rainbow: ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#e84393"]
  };
  var DEFAULT_FX = { type: "auto", theme: "corporate", style: "flat", anim: "smooth", legend: "bottom", mode: "light", labels: false, grid: true, round: true };
  var fx = Object.assign({}, DEFAULT_FX);
  try { var saved = JSON.parse(localStorage.getItem("axw_fx") || "null"); if (saved) fx = Object.assign(fx, saved); } catch (e) {}

  var root = document.getElementById("axw-root");
  if (!root || typeof Chart === "undefined") {
    if (root) root.insertAdjacentHTML("beforeend", '<div class="axw-empty">Chart library could not be loaded (cdn.jsdelivr.net blocked?).</div>');
    return;
  }
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var PERIODS = [["Daily", "Daily"], ["Weekly", "Weekly"], ["Monthly", "Monthly"], ["Quarterly", "Quarterly"], ["Half-Yearly", "Half-yearly"]];
  var YEAR_COLORS = ["#94a3b8", "#8b5cf6", "#0f9488", "#2563eb"];
  var perf = { period: "Monthly", data: null, ready: false };
  var nf = function (v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString(); };
  var fdate = function (iso) { var d = new Date(iso + "T00:00:00"); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }); };
  var fshort = function (iso) { var d = new Date(iso + "T00:00:00"); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }); };
  var activeTab = TABS[0][0], lastData = null, pivotLast = null, charts = {}, pivotReady = false;

  // ------------------------------------------------------------ API helper
  function call(method, args) {
    var qs = Object.keys(args || {}).filter(function (k) { return args[k] !== null && args[k] !== undefined && args[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(args[k]); }).join("&");
    return fetch(API + method + (qs ? "?" + qs : ""), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (r.status === 401 || r.status === 403) throw { auth: true };
        if (!r.ok) throw { http: r.status };
        return r.json();
      }).then(function (j) { return j.message; });
  }
  function showError(e) {
    var box = $("axw-panes");
    if (e && e.auth) {
      box.innerHTML = '<div class="axw-card axw-login">Please <a href="/login?redirect-to=' + encodeURIComponent(location.pathname) + '">log in</a> with a Sales User, Sales Manager or System Manager account to see this dashboard.</div>';
    } else {
      box.innerHTML = '<div class="axw-card axw-empty">Could not load the dashboard (' + esc((e && (e.http || e.message)) || "error") + '). Check the Error Log.</div>';
    }
  }

  // --------------------------------------------------------------- filters
  function today(offsetMonths) {
    var d = new Date(); if (offsetMonths) d.setMonth(d.getMonth() + offsetMonths);
    var m = ("0" + (d.getMonth() + 1)).slice(-2), day = ("0" + d.getDate()).slice(-2);
    return d.getFullYear() + "-" + m + "-" + day;
  }
  $("axw-from").value = today(-1); $("axw-to").value = today(0);
  function fill(id, values, first) {
    var cur = $(id).value;
    $(id).innerHTML = '<option value="">' + first + "</option>" + (values || []).map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + "</option>"; }).join("");
    if (cur && (values || []).indexOf(cur) >= 0) $(id).value = cur;
  }
  function filters() {
    return {
      from_date: $("axw-from").value, to_date: $("axw-to").value, as_of_date: $("axw-to").value || today(0),
      period_type: "Monthly", compare_mode: "None", years_back: "1",
      lead_owner: $("axw-owner").value, source: $("axw-source").value, city: $("axw-city").value, country: $("axw-country").value,
      custom_business_line_: $("axw-bu").value, custom_sub_service: $("axw-ss").value
    };
  }
  function loadOptions(thenLoad) {
    call("alphax_crm.api.bi_dashboard.get_web_filter_options", { business_unit: $("axw-bu").value }).then(function (o) {
      if (!$("axw-bu").options.length) fill("axw-bu", o.business_units, "All");
      fill("axw-ss", o.sub_services, "All");
      if (!$("axw-owner").options.length) {
        fill("axw-owner", o.owners, "All"); fill("axw-source", o.sources, "All");
        fill("axw-country", o.countries, "All"); fill("axw-city", o.cities, "All");
      }
      if (thenLoad) loadAll();
    }).catch(showError);
  }

  // ----------------------------------------------------------------- tabs
  var tabsHtml = "", panesHtml = "";
  TABS.forEach(function (t, i) {
    tabsHtml += '<div class="axw-tab' + (i ? "" : " active") + '" data-tab="' + t[0] + '" style="--tab:' + t[2] + '"><span class="axw-dot"></span>' + esc(t[1]) + "</div>";
    if (t[0] === "perf") {
      panesHtml += '<div class="axw-pane" id="axw-pane-perf" style="--pane:' + t[2] + ';display:block">' + perfPaneHtml() + "</div>";
    } else if (t[0] === "explorer") {
      panesHtml += '<div class="axw-pane" id="axw-pane-explorer" style="--pane:' + t[2] + ';display:none">' +
        '<div class="axw-card"><div class="axw-tools">' +
        '<label>Rows<select id="pv-rows"></select></label><label>Columns<select id="pv-cols"></select></label>' +
        '<label>Measure<select id="pv-measure"></select></label><button class="axw-btn axw-btn-ghost" id="pv-csv">Download CSV</button></div>' +
        '<div class="axw-msg" id="pv-note"></div></div>' +
        '<div class="axw-card"><h3>Chart</h3><div class="axw-chartbox"><canvas id="axw-chart-explorer"></canvas></div></div>' +
        '<div class="axw-card"><h3>Pivot table</h3><div class="axw-table-wrap" id="axw-table-explorer"></div></div></div>';
    } else {
      panesHtml += '<div class="axw-pane" id="axw-pane-' + t[0] + '" style="--pane:' + t[2] + ';display:' + (i ? "none" : "block") + '">' +
        '<div class="axw-kpis" id="axw-kpis-' + t[0] + '"></div>' +
        '<div class="axw-grid2"><div class="axw-card"><h3>Chart</h3><div class="axw-chartbox"><canvas id="axw-chart-' + t[0] + '"></canvas></div></div>' +
        '<div class="axw-card"><h3>Detail</h3><div class="axw-table-wrap" id="axw-table-' + t[0] + '"></div>' +
        '<div style="margin-top:8px"><button class="axw-btn axw-btn-ghost" data-csv="' + t[0] + '">Download CSV</button></div></div></div></div>';
    }
  });
  $("axw-tabs").innerHTML = tabsHtml; $("axw-panes").innerHTML = panesHtml;
  $("axw-tabs").addEventListener("click", function (ev) {
    var el = ev.target.closest(".axw-tab"); if (!el) return;
    activeTab = el.getAttribute("data-tab");
    [].forEach.call(document.querySelectorAll(".axw-tab"), function (x) { x.classList.toggle("active", x === el); });
    [].forEach.call(document.querySelectorAll(".axw-pane"), function (x) { x.style.display = x.id === "axw-pane-" + activeTab ? "block" : "none"; });
    var d = lastData && lastData[activeTab];
    $("axw-msg").textContent = (d && d.message) || "";
    root.classList.toggle("axw-on-perf", activeTab === "perf");
    // charts sized while hidden render at 0 width: redraw the now-visible one
    if (activeTab === "perf") renderPerf(); else if (activeTab === "explorer") renderPivot(); else if (lastData) renderReport(activeTab);
  });

  // --------------------------------------------------------------- charts
  function hexToRgba(h, a) { var n = parseInt(h.slice(1), 16); return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")"; }
  function colorsFor(n) { var base = THEMES[fx.theme] || THEMES.corporate, out = []; for (var i = 0; i < n; i++) out.push(base[i % base.length]); return out; }
  var labelPlugin = {
    id: "axwLabels",
    afterDatasetsDraw: function (chart) {
      if (!fx.labels) return;
      var ctx = chart.ctx; ctx.save(); ctx.font = "600 11px sans-serif"; ctx.textAlign = "center"; ctx.fillStyle = fx.mode === "dark" ? "#e8eef7" : "#18202b";
      chart.data.datasets.forEach(function (ds, di) {
        chart.getDatasetMeta(di).data.forEach(function (el, i) {
          var v = ds.data[i]; if (v === null || v === undefined || v === 0) return;
          var p = el.tooltipPosition ? el.tooltipPosition() : { x: el.x, y: el.y };
          ctx.fillText(Number(v).toLocaleString(), p.x, p.y - 6);
        });
      });
      ctx.restore();
    }
  };
  var glowPlugin = {
    id: "axwGlow",
    beforeDatasetsDraw: function (chart) { if (fx.style === "glow") { chart.ctx.save(); chart.ctx.shadowColor = "rgba(0,0,0,.35)"; chart.ctx.shadowBlur = 14; chart.ctx.shadowOffsetX = 4; chart.ctx.shadowOffsetY = 6; } },
    afterDatasetsDraw: function (chart) { if (fx.style === "glow") chart.ctx.restore(); }
  };
  function paint(color, kind) {
    return function (c) {
      if (fx.style !== "gradient" || !c.chart.chartArea) return color;
      var a = c.chart.chartArea, g = c.chart.ctx.createLinearGradient(0, a.top, 0, a.bottom);
      g.addColorStop(0, color); g.addColorStop(1, hexToRgba(color, kind === "line" ? 0.08 : 0.45)); return g;
    };
  }
  function animation() {
    return { off: false, fast: { duration: 350 }, smooth: { duration: 900, easing: "easeOutQuart" }, slow: { duration: 1800, easing: "easeOutBounce" } }[fx.anim];
  }
  function drawChart(key, labels, datasets, defType) {
    var canvas = $("axw-chart-" + key); if (!canvas) return;
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
    if (!labels.length) { canvas.parentNode.innerHTML = '<div class="axw-empty">No data for this filter selection.</div>'; return; }
    var type = fx.type === "auto" ? defType : fx.type;
    var round = ["pie", "doughnut", "polarArea"].indexOf(type) >= 0;
    var dark = fx.mode === "dark", txt = dark ? "#c8d3e3" : "#4b5a70", gridc = dark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.07)";
    var sets;
    if (round) {
      var cols = colorsFor(labels.length);
      sets = [{ label: datasets[0].name, data: datasets[0].values, backgroundColor: cols.map(function (c) { return fx.style === "gradient" ? hexToRgba(c, .85) : c; }), borderColor: dark ? "#18222f" : "#fff", borderWidth: 2 }];
    } else {
      var palette = colorsFor(datasets.length);
      sets = datasets.map(function (d, i) {
        var col = palette[i], isLine = type === "line" || type === "radar";
        return { label: d.name, data: d.values, backgroundColor: isLine ? (fx.style === "flat" ? hexToRgba(col, .15) : paint(col, "line")) : (fx.style === "gradient" ? paint(col, "bar") : col),
          borderColor: col, borderWidth: isLine ? 3 : 0, borderRadius: (!isLine && fx.round) ? 6 : 0, fill: isLine, tension: .35, pointRadius: isLine ? 4 : 0, pointBackgroundColor: col };
      });
    }
    var opts = { responsive: true, maintainAspectRatio: false, animation: animation(),
      plugins: { legend: { display: fx.legend !== "none" && (round || sets.length > 1), position: fx.legend === "none" ? "bottom" : fx.legend, labels: { color: txt } } } };
    if (!round && type !== "radar") {
      opts.scales = { x: { grid: { display: fx.grid, color: gridc }, ticks: { color: txt }, stacked: false }, y: { beginAtZero: true, grid: { display: fx.grid, color: gridc }, ticks: { color: txt } } };
    }
    charts[key] = new Chart(canvas.getContext("2d"), { type: type, data: { labels: labels, datasets: sets }, options: opts, plugins: [glowPlugin, labelPlugin] });
  }

  // -------------------------------------------------------------- reports
  function fmt(v, col) {
    if (v === null || v === undefined || v === "") return '<span style="opacity:.4">—</span>';
    var ft = col.fieldtype;
    if (ft === "Currency") return Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (ft === "Percent") return Number(v).toFixed(1) + "%";
    if (ft === "Float" && typeof v === "number") return v.toFixed(col.precision || 1);
    if (ft === "Int") return Number(v).toLocaleString();
    return esc(v);
  }
  function renderTable(el, columns, rows) {
    if (!rows.length) { el.innerHTML = '<div class="axw-empty">No data for this filter selection.</div>'; return; }
    var h = "<table><thead><tr>" + columns.map(function (c) { return "<th>" + esc(c.label) + "</th>"; }).join("") + "</tr></thead><tbody>";
    rows.forEach(function (r) {
      h += "<tr>" + columns.map(function (c) { var num = ["Currency", "Percent", "Float", "Int"].indexOf(c.fieldtype) >= 0; return '<td class="' + (num ? "num" : "") + '">' + fmt(r[c.fieldname], c) + "</td>"; }).join("") + "</tr>";
    });
    el.innerHTML = h + "</tbody></table>";
  }
  function renderReport(id) {
    var d = lastData && lastData[id]; if (!d) return;
    var kp = $("axw-kpis-" + id), tb = $("axw-table-" + id);
    if (d.error) { kp.innerHTML = ""; tb.innerHTML = '<div class="axw-empty">' + esc(d.error) + "</div>"; return; }
    kp.innerHTML = (d.summary || []).map(function (k) {
      var cls = k.indicator === "green" ? "green" : k.indicator === "red" ? "red" : k.indicator === "blue" ? "" : "grey";
      var val = k.datatype === "Currency" ? Number(k.value).toLocaleString(undefined, { maximumFractionDigits: 0 }) : k.value;
      return '<div class="axw-kpi ' + cls + '"><b>' + esc(val) + "</b><span>" + esc(k.label) + "</span></div>";
    }).join("");
    renderTable(tb, d.columns || [], d.data || []);
    var ch = d.chart;
    // the chart canvas may have been replaced by an empty-state message earlier
    var box = $("axw-pane-" + id).querySelector(".axw-chartbox");
    if (!$("axw-chart-" + id)) box.innerHTML = '<canvas id="axw-chart-' + id + '"></canvas>';
    if (ch && ch.data && ch.data.labels) drawChart(id, ch.data.labels, (ch.data.datasets || []).map(function (s) { return { name: s.name, values: s.values }; }), ({ pie: "pie", donut: "doughnut", line: "line", bar: "bar" }[ch.type] || "bar"));
    else drawChart(id, [], [], "bar");
  }
  function loadAll() {
    $("axw-updated").textContent = "Loading…";
    call("alphax_crm.api.bi_dashboard.get_bi_dashboard_data", filters()).then(function (data) {
      lastData = data;
      TABS.forEach(function (t) { if (t[0] !== "explorer" && t[0] !== "perf") renderReport(t[0]); });
      var d = data[activeTab]; $("axw-msg").textContent = (d && d.message) || "";
      $("axw-updated").textContent = "Last updated: " + new Date().toLocaleTimeString();
    }).catch(showError);
    loadPivot();
    loadPerf();
  }

  // ---------------------------------------------------------- pivot explorer
  function initPivot() {
    call("alphax_crm.api.bi_dashboard.get_pivot_options", {}).then(function (o) {
      var dims = o.dimensions.map(function (d) { return '<option value="' + d.id + '">' + esc(d.label) + "</option>"; }).join("");
      $("pv-rows").innerHTML = dims; $("pv-cols").innerHTML = '<option value="">(none)</option>' + dims;
      $("pv-measure").innerHTML = o.measures.map(function (m) { return '<option value="' + m.id + '">' + esc(m.label) + "</option>"; }).join("");
      if (o.dimensions.some(function (d) { return d.id === "source"; })) $("pv-rows").value = "source";
      ["pv-rows", "pv-cols", "pv-measure"].forEach(function (id) { $(id).addEventListener("change", loadPivot); });
      $("pv-csv").addEventListener("click", pivotCsv);
      pivotReady = true; loadPivot();
    }).catch(function () {});
  }
  function loadPivot() {
    if (!pivotReady) return;
    var f = filters();
    call("alphax_crm.api.bi_dashboard.get_pivot_data", {
      rows_dim: $("pv-rows").value, cols_dim: $("pv-cols").value, measure: $("pv-measure").value,
      from_date: f.from_date, to_date: f.to_date, lead_owner: f.lead_owner, source: f.source, city: f.city, country: f.country,
      custom_business_line_: f.custom_business_line_, custom_sub_service: f.custom_sub_service
    }).then(function (d) { pivotLast = d; renderPivot(); }).catch(function () {});
  }
  function renderPivot() {
    var d = pivotLast; if (!d) return;
    $("pv-note").textContent = d.total_leads + " leads created in the selected dates match the filters. " + d.row_label + (d.col_label ? " × " + d.col_label : "");
    var multi = d.cols && d.cols.length, top = d.rows.slice(0, 25);
    var ds = multi ? d.cols.map(function (c, ci) { return { name: String(c), values: top.map(function (_r, ri) { return d.matrix[ri][ci]; }) }; })
      : [{ name: d.measure_label, values: top.map(function (_r, ri) { return d.matrix[ri][0]; }) }];
    var box = $("axw-pane-explorer").querySelector(".axw-chartbox");
    if (!$("axw-chart-explorer")) box.innerHTML = '<canvas id="axw-chart-explorer"></canvas>';
    drawChart("explorer", top.map(String), ds, "bar");
    var pct = $("pv-measure").value === "win_rate", cols = multi ? d.cols : [d.measure_label], max = 0;
    d.matrix.forEach(function (l) { l.forEach(function (v) { if (v > max) max = v; }); });
    var h = "<table><thead><tr><th>" + esc(d.row_label) + "</th>" + cols.map(function (c) { return '<th style="text-align:right">' + esc(c) + "</th>"; }).join("") + (multi && !pct ? '<th style="text-align:right">Total</th>' : "") + "</tr></thead><tbody>";
    var tot = cols.map(function () { return 0; });
    d.rows.forEach(function (r, ri) {
      var rt = 0; h += "<tr><td>" + esc(r) + "</td>";
      d.matrix[ri].forEach(function (v, ci) { rt += v; tot[ci] += v; h += '<td class="num" style="background:rgba(15,118,110,' + (v && max ? (0.08 + 0.42 * v / max).toFixed(2) : 0) + ')">' + v + (pct ? "%" : "") + "</td>"; });
      h += (multi && !pct ? '<td class="num"><b>' + rt + "</b></td>" : "") + "</tr>";
    });
    if (!pct) h += "<tr><td><b>Total</b></td>" + tot.map(function (v) { return '<td class="num"><b>' + v + "</b></td>"; }).join("") + (multi ? '<td class="num"><b>' + tot.reduce(function (a, b) { return a + b; }, 0) + "</b></td>" : "") + "</tr>";
    $("axw-table-explorer").innerHTML = h + "</tbody></table>";
  }
  function download(name, lines) {
    var blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" }), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
  }
  var q = function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; };
  function pivotCsv() {
    var d = pivotLast; if (!d || !d.rows.length) return;
    var cols = d.cols && d.cols.length ? d.cols : [d.measure_label];
    download("alphax_pivot.csv", [[d.row_label].concat(cols).map(q).join(",")].concat(d.rows.map(function (r, i) { return [q(r)].concat(d.matrix[i]).join(","); })));
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-csv]"); if (!b) return;
    var d = lastData && lastData[b.getAttribute("data-csv")]; if (!d || !d.data.length) return;
    download(b.getAttribute("data-csv") + ".csv", [d.columns.map(function (c) { return q(c.label); }).join(",")].concat(d.data.map(function (r) { return d.columns.map(function (c) { return q(r[c.fieldname]); }).join(","); })));
  });

  // ------------------------------------------------------ effects panel
  function applyFxToUi() {
    $("fx-type").value = fx.type; $("fx-theme").value = fx.theme; $("fx-style").value = fx.style; $("fx-anim").value = fx.anim;
    $("fx-legend").value = fx.legend; $("fx-mode").value = fx.mode; $("fx-labels").checked = !!fx.labels; $("fx-grid").checked = !!fx.grid; $("fx-round").checked = !!fx.round;
    root.setAttribute("data-theme", fx.mode);
  }
  function fxChanged() {
    fx = { type: $("fx-type").value, theme: $("fx-theme").value, style: $("fx-style").value, anim: $("fx-anim").value, legend: $("fx-legend").value,
      mode: $("fx-mode").value, labels: $("fx-labels").checked, grid: $("fx-grid").checked, round: $("fx-round").checked };
    try { localStorage.setItem("axw_fx", JSON.stringify(fx)); } catch (e) {}
    root.setAttribute("data-theme", fx.mode);
    if (lastData && activeTab !== "perf") TABS.forEach(function (t) { if (t[0] !== "explorer" && t[0] === activeTab) renderReport(t[0]); });
    if (activeTab === "perf") renderPerf();
    if (activeTab === "explorer") renderPivot();
  }
  ["fx-type", "fx-theme", "fx-style", "fx-anim", "fx-legend", "fx-mode", "fx-labels", "fx-grid", "fx-round"].forEach(function (id) { $(id).addEventListener("change", fxChanged); });
  $("fx-reset").addEventListener("click", function () { fx = Object.assign({}, DEFAULT_FX); applyFxToUi(); fxChanged(); });
  $("axw-fx-toggle").addEventListener("click", function () { $("axw-fx").hidden = !$("axw-fx").hidden; });
  applyFxToUi();

  // ------------------------------------------------- lead performance tab
  function badge(v, suffix) {
    if (v === null || v === undefined) return '<span class="axw-badge na">N/A</span>';
    var up = v > 0, flat = v === 0;
    return '<span class="axw-badge ' + (flat ? "flat" : up ? "up" : "down") + '">' + (flat ? "■" : up ? "▲" : "▼") + " " + Math.abs(v).toFixed(1) + "%" + (suffix ? " " + esc(suffix) : "") + "</span>";
  }
  function perfPaneHtml() {
    var pills = PERIODS.map(function (p) { return '<button class="axw-pill' + (p[0] === perf.period ? " on" : "") + '" data-period="' + p[0] + '">' + p[1] + "</button>"; }).join("");
    return '<div class="axw-perf">' +
      '<div class="axw-perf-head"><div><div class="axw-eyebrow">AlphaX · CRM Analytics</div><h2>Lead performance</h2><p>One report. Every reporting period.</p></div>' +
      '<div class="axw-perf-actions"><button class="axw-btn axw-btn-ghost" id="pf-csv">Download summary</button><button class="axw-btn axw-btn-ghost" id="pf-print">Print</button></div></div>' +
      '<div class="axw-pills" id="pf-pills">' + pills + "</div>" +
      '<div class="axw-perf-filters"><label>Report through<input type="date" id="pf-through"></label>' +
      '<label>Status<select id="pf-status"><option value="">All statuses</option></select></label>' +
      '<label>Current stage<select id="pf-stage"><option value="">All stages</option></select></label>' +
      '<div class="axw-perf-range" id="pf-range"></div></div>' +
      '<div class="axw-perf-body" id="pf-body"><div class="axw-empty">Loading…</div></div></div>';
  }
  function perfParams() {
    var f = filters();
    return { period: perf.period, report_through: $("pf-through").value, years_back: 3, lead_owner: f.lead_owner, source: f.source, city: f.city,
      country: f.country, custom_business_line_: f.custom_business_line_, custom_sub_service: f.custom_sub_service,
      status: $("pf-status").value, current_stage: $("pf-stage").value };
  }
  function loadPerf() {
    if (!perf.ready) return;
    $("pf-body").classList.add("loading");
    call("alphax_crm.api.lead_performance.get_lead_performance", perfParams()).then(function (d) {
      perf.data = d; $("pf-body").classList.remove("loading"); renderPerf();
      $("axw-updated").textContent = "Last updated: " + new Date().toLocaleTimeString();
    }).catch(function (e) { $("pf-body").classList.remove("loading"); if (e && e.auth) showError(e); else $("pf-body").innerHTML = '<div class="axw-card axw-empty">Could not load Lead performance (' + esc((e && (e.http || e.message)) || "error") + "). Check the Error Log.</div>"; });
  }
  function initPerf() {
    $("pf-through").value = today(0);
    call("alphax_crm.api.lead_performance.get_lead_options", {}).then(function (o) {
      var opt = function (arr) { return arr.map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + "</option>"; }).join(""); };
      $("pf-stage").innerHTML = '<option value="">All stages</option>' + opt(o.stages || []);
      $("pf-status").innerHTML = '<option value="">All statuses</option>' + opt(o.statuses || []);
    }).catch(function () {});
    $("pf-pills").addEventListener("click", function (ev) {
      var b = ev.target.closest(".axw-pill"); if (!b) return;
      perf.period = b.getAttribute("data-period");
      [].forEach.call(document.querySelectorAll(".axw-pill"), function (x) { x.classList.toggle("on", x === b); });
      loadPerf();
    });
    ["pf-through", "pf-status", "pf-stage"].forEach(function (id) { $(id).addEventListener("change", loadPerf); });
    $("pf-csv").addEventListener("click", perfCsv);
    $("pf-print").addEventListener("click", function () { window.print(); });
    $("pf-body").addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-drill]"); if (el) drill(el.getAttribute("data-drill"), el.getAttribute("data-stage"), el.getAttribute("data-year"));
    });
    perf.ready = true;
  }
  function barList(items, cls, kind, max) {
    max = max || Math.max.apply(null, items.map(function (i) { return i.v; }).concat([1]));
    return '<div class="axw-bars ' + cls + '">' + items.map(function (i, n) {
      return '<div class="axw-barrow" data-drill="' + kind + '" data-stage="' + esc(i.k) + '" title="Click to see the leads"><span class="lbl">' + esc(i.k) + '</span><span class="track"><span class="fill" style="width:' +
        (i.v ? Math.max(2, 100 * i.v / max) : 0) + "%;animation-delay:" + (n * 60) + 'ms"></span></span><b>' + nf(i.v) + "</b></div>";
    }).join("") + "</div>";
  }
  function kpi(cls, icon, label, value, sub, drillKind) {
    return '<div class="axw-pk ' + cls + '"' + (drillKind ? ' data-drill="' + drillKind + '" title="Click to see the leads"' : "") + '><div class="ic">' + icon + '</div><div class="lb">' + label + '</div><div class="vl">' + value + '</div><div class="sb">' + sub + "</div></div>";
  }
  function insights(d) {
    var out = [], c = d.current, cur = d.years[d.years.length - 1], prev = d.years[d.years.length - 2];
    if (d.yoy_new_leads !== null && prev && prev.has_data)
      out.push(["📈", "New leads are <b>" + (d.yoy_new_leads >= 0 ? "up " : "down ") + Math.abs(d.yoy_new_leads).toFixed(1) + "%</b> vs " + prev.year + " (" + nf(cur.new_leads) + " vs " + nf(prev.new_leads) + ")."]);
    if (c.won + c.lost > 0) out.push(["🏆", "Win rate on closed deals this period: <b>" + (100 * c.won / (c.won + c.lost)).toFixed(0) + "%</b> (" + c.won + " won, " + c.lost + " lost)."]);
    if (d.pipeline.length) { var big = d.pipeline.slice().sort(function (a, b) { return b.count - a.count; })[0]; out.push(["🧭", "Largest open stage is <b>" + esc(big.stage) + "</b> with " + nf(big.count) + " of " + nf(d.open_total) + " open leads."]); }
    if (d.aging.length) { var old = d.aging.slice().sort(function (a, b) { return b.avg_days - a.avg_days; })[0]; if (old.avg_days > 0) out.push(["⏳", "<b>" + esc(old.stage) + "</b> leads wait longest: avg " + old.avg_days + " days, oldest " + old.max_days + "."]); }
    if (d.lost_reasons.length) out.push(["⚠️", "Top lost reason: <b>" + esc(d.lost_reasons[0].reason) + "</b> (" + d.lost_reasons[0].count + ")."]);
    var f = (d.funnel || []).filter(function (x) { return x.step_pct !== null; });
    if (f.length) { var worst = f.slice().sort(function (a, b) { return a.step_pct - b.step_pct; })[0]; out.push(["🔻", "Biggest funnel drop-off: into <b>" + esc(worst.stage) + "</b> (" + worst.step_pct + "% continue)."]); }
    return out.length ? out : [["ℹ️", "No activity found for this period and filter selection."]];
  }
  function renderPerf() {
    var d = perf.data; if (!d) return;
    var c = d.current, cur = d.years[d.years.length - 1], money = d.quotation.currency + " ";
    $("pf-range").textContent = PERIODS.filter(function (p) { return p[0] === d.period; })[0][1] + " summary · " + fshort(d.start) + " – " + fdate(d.end) + " · " + d.days + (d.days === 1 ? " day" : " days");
    var h = '<div class="axw-pkpis">' +
      kpi("k1", "👥", "New leads", nf(c.new_leads), d.yoy_new_leads === null ? '<span class="axw-badge na">N/A</span> vs last year' : badge(d.yoy_new_leads) + " vs " + d.years[d.years.length - 2].year, "new") +
      kpi("k2", "🔀", "Total stage entries", nf(c.total_entries), "Lead–stage pairs in period", "") +
      kpi("k3", "🏁", "Won / Lost", '<span class="g">' + nf(c.won) + '</span> / <span class="r" data-drill="lost">' + nf(c.lost) + "</span>", c.won + c.lost ? "Win rate " + (100 * c.won / (c.won + c.lost)).toFixed(0) + "% of closed" : "No closed deals in period", "") +
      kpi("k4", "💰", "Quotation value", money + nf(Math.round(d.quotation.value)), "Average " + money + nf(Math.round(d.quotation.avg)) + " · " + d.quotation.count + " quotations", "") + "</div>";

    h += '<div class="axw-grid-2">' +
      '<div class="axw-card"><h3 class="plain">Stage entries in selected period</h3>' +
      barList(d.stages.map(function (s) { return { k: s, v: c.stages[s] || 0 }; }), "blue", "stage") +
      '<p class="axw-note">Distinct leads per destination stage. Re-entry to the same stage counts once. Click a bar to see the leads.</p></div>' +
      '<div class="axw-card"><h3 class="plain">Same-period comparison · previous ' + (d.years.length - 1) + ' years</h3><div class="axw-chartbox short"><canvas id="pf-cmp"></canvas></div>' +
      '<p class="axw-note">Selected year plus previous years · equal elapsed period length. “No data” = nothing recorded for that year.</p></div></div>';

    h += '<div class="axw-grid-2">' +
      '<div class="axw-card"><h3 class="plain">Lead-to-Won funnel <small>(leads created in period)</small></h3>' + funnelHtml(d.funnel) + "</div>" +
      '<div class="axw-card axw-insights"><h3 class="plain">Key insights</h3><ul>' + insights(d).map(function (i) { return "<li><span>" + i[0] + "</span><div>" + i[1] + "</div></li>"; }).join("") + "</ul></div></div>";

    var cols = d.stages.length;
    h += '<div class="axw-card"><h3 class="plain">Combined summary</h3><div class="axw-table-wrap"><table class="axw-sum"><thead><tr><th>Period</th>' +
      d.stages.map(function (s) { return '<th class="r">' + esc(s) + "</th>"; }).join("") + '<th class="r">Total stage entries</th><th class="r">New leads</th><th class="r">YoY leads</th></tr></thead><tbody>';
    d.years.forEach(function (y, i) {
      var last = i === d.years.length - 1, nd = !y.has_data;
      h += '<tr class="' + (last ? "cur" : "") + '"><td>' + fshort(y.start) + " – " + fdate(y.end) + "</td>" +
        d.stages.map(function (s) { return '<td class="r' + (nd ? " nd" : "") + '">' + (nd ? "No data" : '<a data-drill="stage" data-stage="' + esc(s) + '" data-year="' + y.year + '">' + nf(y.stages[s] || 0) + "</a>"); }).join("") +
        '<td class="r"><b>' + (nd ? "—" : nf(y.total_entries)) + '</b></td><td class="r">' + (nd ? "—" : '<a data-drill="new" data-year="' + y.year + '">' + nf(y.new_leads) + "</a>") + '</td><td class="r">' + (nd || i === 0 ? "—" : badge(y.yoy_leads)) + "</td></tr>";
    });
    h += "</tbody></table></div></div>";

    var maxAvg = Math.max.apply(null, d.aging.map(function (a) { return a.avg_days; }).concat([1]));
    h += '<div class="axw-grid-2">' +
      '<div class="axw-card"><h3 class="plain">Current pipeline by stage</h3><div class="axw-sub">Snapshot · ' + fdate(d.report_through) + " · independent of the period tab · " + nf(d.open_total) + " open leads</div>" +
      barList(d.pipeline.map(function (p) { return { k: p.stage, v: p.count }; }), "teal", "pipeline") + '<p class="axw-note">Won and Lost excluded from open pipeline.</p></div>' +
      '<div class="axw-card"><h3 class="plain">Stage aging</h3><div class="axw-sub">Current snapshot · days since most recent stage entry</div>' +
      '<table class="axw-sum"><thead><tr><th>Current stage</th><th class="r">Leads</th><th class="r">Avg days</th><th class="r">Max days</th></tr></thead><tbody>' +
      (d.aging.length ? d.aging.map(function (a) { return "<tr><td>" + esc(a.stage) + '</td><td class="r">' + nf(a.count) + '</td><td class="r"><span class="heat" style="--h:' + (a.avg_days / maxAvg).toFixed(2) + '">' + a.avg_days + '</span></td><td class="r">' + a.max_days + "</td></tr>"; }).join("") : '<tr><td colspan="4" class="nd">No open leads</td></tr>') +
      "</tbody></table></div></div>";

    h += '<div class="axw-grid-2">' +
      '<div class="axw-card"><h3 class="plain">Quotation value by payment type</h3><table class="axw-sum"><thead><tr><th>Payment type</th><th class="r">Count</th><th class="r">Value (' + esc(d.quotation.currency) + ')</th><th>Share</th></tr></thead><tbody>' +
      (d.quotation.types.length ? d.quotation.types.map(function (t) { var sh = d.quotation.value ? 100 * t.value / d.quotation.value : 0; return "<tr><td>" + esc(t.payment_type) + '</td><td class="r">' + t.count + '</td><td class="r">' + nf(Math.round(t.value)) + '</td><td><span class="mini"><i style="width:' + sh.toFixed(0) + '%"></i></span></td></tr>'; }).join("") +
        '<tr class="tot"><td>Total</td><td class="r">' + d.quotation.count + '</td><td class="r">' + nf(Math.round(d.quotation.value)) + "</td><td></td></tr>" : '<tr><td colspan="4" class="nd">No quotations issued in this period</td></tr>') +
      '</tbody></table><p class="axw-note">Submitted quotations dated in the selected period · ' + esc(d.quotation.currency) + ". Payment type = the quotation’s Payment Terms Template.</p></div>" +
      '<div class="axw-card"><h3 class="plain">Lost reasons</h3>' + (d.lost_reasons.length ? barList(d.lost_reasons.map(function (r) { return { k: r.reason, v: r.count }; }), "purple", "lost") : '<div class="axw-empty small">No leads entered Lost in this period.</div>') +
      '<p class="axw-note">Leads first entering Lost in selected period.</p></div></div>';
    $("pf-body").innerHTML = h;
    drawPerfCompare(d);
  }
  function funnelHtml(f) {
    if (!f || !f.length) return '<div class="axw-empty small">No leads were created in this period.</div>';
    var base = f[0].count || 1;
    return '<div class="axw-funnel">' + f.map(function (s, i) {
      return '<div class="fn" data-drill="stage" data-stage="' + esc(s.stage) + '"><div class="fb" style="width:' + Math.max(8, 100 * s.count / base) + '%;--i:' + i + '"><span>' + esc(s.stage) + "</span><b>" + nf(s.count) + "</b></div>" +
        '<div class="fp">' + (s.pct_of_leads === null ? "" : s.pct_of_leads + "% of leads") + (s.step_pct !== null ? " · " + s.step_pct + "% of previous" : "") + "</div></div>";
    }).join("") + "</div>";
  }
  var endLabels = { id: "axwEnd", afterDatasetsDraw: function (chart) {
    var ctx = chart.ctx; ctx.save(); ctx.font = "600 11px sans-serif"; ctx.fillStyle = fx.mode === "dark" ? "#e8eef7" : "#18202b"; ctx.textBaseline = "middle";
    chart.data.datasets.forEach(function (ds, di) { chart.getDatasetMeta(di).data.forEach(function (el, i) { var v = ds.data[i]; if (v === null || v === undefined) return; ctx.fillText(Number(v).toLocaleString(), el.x + 5, el.y); }); });
    ctx.restore(); } };
  function drawPerfCompare(d) {
    var canvas = $("pf-cmp"); if (!canvas) return;
    if (charts.pfcmp) { charts.pfcmp.destroy(); delete charts.pfcmp; }
    var dark = fx.mode === "dark", txt = dark ? "#c8d3e3" : "#4b5a70", n = d.years.length, off = 4 - n;
    var sets = d.years.map(function (y, i) {
      var v = function (x) { return y.has_data ? x : null; };
      return { label: String(y.year) + (y.has_data ? "" : " (no data)"), data: [v(y.new_leads), v(y.total_entries), v(y.won)], backgroundColor: YEAR_COLORS[i + off], borderRadius: fx.round ? 5 : 0, barPercentage: .9, categoryPercentage: .8 };
    });
    charts.pfcmp = new Chart(canvas.getContext("2d"), { type: "bar", data: { labels: ["New leads", "Stage entries", "Won"], datasets: sets },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: animation(), layout: { padding: { right: 34 } },
        plugins: { legend: { position: "top", align: "start", labels: { color: txt, usePointStyle: true, boxWidth: 8 } } },
        scales: { x: { beginAtZero: true, grid: { display: fx.grid, color: dark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)" }, ticks: { color: txt } }, y: { grid: { display: false }, ticks: { color: txt, font: { weight: "600" } } } } },
      plugins: [endLabels] });
  }
  function perfCsv() {
    var d = perf.data; if (!d) return;
    var f = perfParams(), L = [];
    L.push(q("AlphaX Lead performance")); L.push([q("Period"), q(d.period)].join(","));
    L.push([q("Window"), q(d.start + " to " + d.end), q(d.days + " days")].join(","));
    L.push([q("Report through"), q(d.report_through)].join(","));
    ["lead_owner", "source", "city", "country", "custom_business_line_", "custom_sub_service", "status", "current_stage"].forEach(function (k) { L.push([q(k), q(f[k] || "All")].join(",")); });
    L.push(""); L.push([q("Period"), q("Year")].concat(d.stages.map(q), [q("Total stage entries"), q("New leads"), q("YoY leads %")]).join(","));
    d.years.forEach(function (y) { L.push([q(y.start + " to " + y.end), y.year].concat(d.stages.map(function (s) { return y.has_data ? (y.stages[s] || 0) : q("No data"); }), [y.has_data ? y.total_entries : q("No data"), y.has_data ? y.new_leads : q("No data"), y.yoy_leads === null ? q("N/A") : y.yoy_leads]).join(",")); });
    L.push(""); L.push([q("Open pipeline stage"), q("Leads"), q("Avg days"), q("Max days")].join(","));
    d.pipeline.forEach(function (p, i) { var a = d.aging[i] || {}; L.push([q(p.stage), p.count, a.avg_days, a.max_days].join(",")); });
    L.push(""); L.push([q("Payment type"), q("Count"), q("Value " + d.quotation.currency)].join(","));
    d.quotation.types.forEach(function (t) { L.push([q(t.payment_type), t.count, t.value].join(",")); });
    L.push(""); L.push([q("Lost reason"), q("Leads")].join(","));
    d.lost_reasons.forEach(function (r) { L.push([q(r.reason), r.count].join(",")); });
    download("alphax_lead_performance.csv", L);
  }
  function drill(kind, stage, year) {
    if (!kind) return;
    var p = perfParams(); p.kind = kind; if (stage) p.stage = stage; if (year) p.year = year; delete p.years_back;
    var m = $("axw-modal"); m.hidden = false;
    var title = { "new": "New leads", stage: "Entered " + (stage || ""), pipeline: "Open leads in " + (stage || ""), lost: "Lost leads" }[kind] || "Leads";
    $("axw-modal-title").textContent = title; $("axw-modal-body").innerHTML = '<div class="axw-empty">Loading…</div>';
    call("alphax_crm.api.lead_performance.get_lead_drill", p).then(function (r) {
      var cols = [["name", "Lead"], ["lead_name", "Name"], ["company_name", "Company"], ["lead_owner", "Sales person"], ["source", "Source"], ["city", "City"], ["status", "Stage"], ["creation", "Created"]]
        .filter(function (c) { return r.rows.some(function (x) { return x[c[0]]; }); });
      $("axw-modal-sub").textContent = r.total + " lead" + (r.total === 1 ? "" : "s") + " · " + r.start + " → " + r.end + (r.total > r.rows.length ? " · showing first " + r.rows.length : "");
      $("axw-modal-body").innerHTML = r.rows.length ? '<table class="axw-sum"><thead><tr>' + cols.map(function (c) { return "<th>" + c[1] + "</th>"; }).join("") + "</tr></thead><tbody>" +
        r.rows.map(function (x) { return "<tr>" + cols.map(function (c) { var v = x[c[0]]; if (c[0] === "name") v = '<a href="/app/lead/' + encodeURIComponent(v) + '" target="_blank" rel="noopener">' + esc(v) + "</a>"; else v = esc(c[0] === "creation" && v ? String(v).slice(0, 10) : v); return "<td>" + (v || "") + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table>" : '<div class="axw-empty">No leads.</div>';
    }).catch(function () { $("axw-modal-body").innerHTML = '<div class="axw-empty">Could not load the leads.</div>'; });
  }
  root.insertAdjacentHTML("beforeend", '<div class="axw-modal" id="axw-modal" hidden><div class="axw-modal-box"><div class="axw-modal-head"><div><b id="axw-modal-title"></b><small id="axw-modal-sub"></small></div><button class="axw-btn axw-btn-ghost" id="axw-modal-x">Close</button></div><div class="axw-modal-body" id="axw-modal-body"></div></div></div>');
  $("axw-modal-x").addEventListener("click", function () { $("axw-modal").hidden = true; });
  $("axw-modal").addEventListener("click", function (ev) { if (ev.target === $("axw-modal")) $("axw-modal").hidden = true; });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") $("axw-modal").hidden = true; });

  // -------------------------------------------------------------- wiring
  ["axw-from", "axw-to", "axw-owner", "axw-source", "axw-city", "axw-country", "axw-ss"].forEach(function (id) { $(id).addEventListener("change", loadAll); });
  $("axw-bu").addEventListener("change", function () { $("axw-ss").value = ""; loadOptions(true); });
  $("axw-refresh").addEventListener("click", loadAll);
  $("axw-clear").addEventListener("click", function () {
    ["axw-owner", "axw-source", "axw-city", "axw-country", "axw-bu", "axw-ss"].forEach(function (id) { $(id).value = ""; });
    $("axw-from").value = today(-1); $("axw-to").value = today(0); loadOptions(true);
  });
  root.classList.add("axw-on-perf");
  initPerf(); loadOptions(true); initPivot();
})();
