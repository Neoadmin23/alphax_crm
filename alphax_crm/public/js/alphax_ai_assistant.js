// AlphaX CRM — global AI Assistant: a floating "Ask AI" button available on
// every desk screen (loaded via app_include_js, not a per-doctype script).
// Auto-detects which record/list the user is currently looking at and sends
// that as context, so "summarize this" or "why is this stale" means
// something without the user having to say which record. Answers can come
// back with a data table and a chart (frappe.ui's own Chart library — no
// external script — see AlphaX CRM > api/ai_query.py for how a question
// becomes a permission-checked query instead of free-form SQL).
(function () {
    if (window.alphax_ai_assistant_loaded) return;
    window.alphax_ai_assistant_loaded = true;

    frappe.ready(() => {
        if (frappe.session.user === "Guest") return;
        alphax_ai_inject_button();
    });

    function alphax_ai_inject_button() {
        const $btn = $(`
            <div id="alphax-ai-fab" title="${__("Ask AI")}" style="
                position: fixed; right: 24px; bottom: 24px; z-index: 1000;
                width: 52px; height: 52px; border-radius: 50%;
                background: var(--primary, #2490ef); color: #fff;
                display: flex; align-items: center; justify-content: center;
                box-shadow: 0 2px 8px rgba(0,0,0,.25); cursor: pointer;
                font-size: 22px;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2a7 7 0 0 0-7 7c0 2.6 1.3 4.5 3 5.8V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.2c1.7-1.3 3-3.2 3-5.8a7 7 0 0 0-7-7z"/>
                    <path d="M9 21h6"/>
                </svg>
            </div>
        `);
        $("body").append($btn);
        $btn.on("click", () => alphax_ai_open_dialog());
    }

    function alphax_ai_current_context() {
        const route = frappe.get_route();
        if (route && route[0] === "Form" && route[1] && route[2]) {
            return { doctype: route[1], name: route[2], label: `${route[1]} ${route[2]}` };
        }
        if (route && route[0] === "List" && route[1]) {
            return { doctype: route[1], name: null, label: `${route[1]} list` };
        }
        return null;
    }

    function alphax_ai_open_dialog() {
        const context = alphax_ai_current_context();
        const d = new frappe.ui.Dialog({
            title: __("Ask AI"),
            size: "large",
            fields: [
                {
                    fieldname: "context_note",
                    fieldtype: "HTML",
                    options: context
                        ? `<p class="text-muted small">${__("Currently viewing")}: <b>${frappe.utils.escape_html(context.label)}</b> — ${__("you can ask about this, or anything else in the CRM.")}</p>`
                        : `<p class="text-muted small">${__("Ask about leads, opportunities, pre-leads, pipeline value, overdue follow-ups, stage durations — anything in the CRM.")}</p>`,
                },
                { fieldname: "conversation", fieldtype: "HTML", options: '<div id="alphax-ai-conversation" style="max-height: 50vh; overflow-y: auto; margin-bottom: 10px;"></div>' },
                {
                    fieldname: "question",
                    fieldtype: "Small Text",
                    label: __("Your question"),
                    description: __("e.g. \"How many leads by source this month?\", \"Show overdue follow-ups\", \"Pipeline value by stage\""),
                },
            ],
            primary_action_label: __("Ask"),
            primary_action() {
                const q = (d.get_value("question") || "").trim();
                if (!q) return;
                alphax_ai_ask(d, q, context);
            },
        });
        d.show();
        d.$wrapper.find(".modal-dialog").css("max-width", "700px");
    }

    function alphax_ai_append(d, role, html) {
        const $box = d.$wrapper.find("#alphax-ai-conversation");
        const align = role === "user" ? "right" : "left";
        const bg = role === "user" ? "#eef4ff" : "#f6f6f6";
        $box.append(`
            <div style="text-align:${align}; margin: 6px 0;">
                <div style="display:inline-block; max-width: 90%; background:${bg}; border-radius: 10px; padding: 8px 12px; text-align:left;">
                    ${html}
                </div>
            </div>
        `);
        $box.scrollTop($box[0].scrollHeight);
    }

    function alphax_ai_render_table(columns, rows) {
        const head = columns.map((c) => `<th>${frappe.utils.escape_html(String(c))}</th>`).join("");
        const body = rows
            .slice(0, 20)
            .map((r) => `<tr>${r.map((v) => `<td>${frappe.utils.escape_html(v == null ? "" : String(v))}</td>`).join("")}</tr>`)
            .join("");
        return `<div style="overflow-x:auto; margin-top:8px;">
            <table class="table table-bordered table-sm" style="font-size:12px;">
                <thead><tr>${head}</tr></thead><tbody>${body}</tbody>
            </table>
            ${rows.length > 20 ? `<div class="text-muted small">${__("Showing first 20 of {0} rows", [rows.length])}</div>` : ""}
        </div>`;
    }

    function alphax_ai_render_chart(container_id, chart) {
        if (!chart || !chart.labels || !chart.labels.length) return;
        setTimeout(() => {
            const el = document.getElementById(container_id);
            if (!el || typeof frappe.Chart === "undefined") return;
            try {
                new frappe.Chart(el, {
                    title: chart.title || "",
                    data: { labels: chart.labels, datasets: [{ values: chart.values }] },
                    type: chart.type === "line" ? "line" : "bar",
                    height: 220,
                    colors: ["#2490ef"],
                });
            } catch (e) {
                // Chart rendering is a nice-to-have; a failure here should never
                // hide the text answer/table that already rendered above it.
            }
        }, 50);
    }

    function alphax_ai_ask(d, question, context) {
        alphax_ai_append(d, "user", frappe.utils.escape_html(question));
        d.set_value("question", "");
        const loading_id = "alphax-ai-loading-" + frappe.utils.get_random(6);
        alphax_ai_append(d, "ai", `<span id="${loading_id}" class="text-muted">${__("Thinking…")}</span>`);

        frappe.call({
            method: "alphax_crm.api.ai_query.ask",
            args: {
                question,
                context_doctype: context ? context.doctype : null,
                context_name: context ? context.name : null,
            },
            callback: (r) => {
                const res = r.message || {};
                const $loading = d.$wrapper.find("#" + loading_id).closest("div").parent();
                let html = `<div>${frappe.utils.escape_html(res.answer || "")}</div>`;
                let chart_div_id = null;
                if (res.table && res.table.rows && res.table.rows.length) {
                    html += alphax_ai_render_table(res.table.columns, res.table.rows);
                }
                if (res.chart && res.chart.labels && res.chart.labels.length) {
                    chart_div_id = "alphax-ai-chart-" + frappe.utils.get_random(6);
                    html += `<div id="${chart_div_id}" style="margin-top:10px;"></div>`;
                }
                $loading.html(`<div style="display:inline-block; max-width:100%; background:#f6f6f6; border-radius:10px; padding:8px 12px; text-align:left;">${html}</div>`);
                if (chart_div_id) alphax_ai_render_chart(chart_div_id, res.chart);
                d.$wrapper.find("#alphax-ai-conversation").scrollTop(d.$wrapper.find("#alphax-ai-conversation")[0].scrollHeight);
            },
            error: () => {
                const $loading = d.$wrapper.find("#" + loading_id);
                $loading.text(__("Something went wrong reaching the AI server."));
            },
        });
    }
})();
