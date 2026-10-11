// AlphaX CRM — the "Ask AI" assistant dialog, shared across every doctype
// that wires up a button to it (loaded once via app_include_js, called from
// each doctype's own list/form JS — see alphax_prelead_list.js, lead.js,
// prelead.js, opportunity.js). Answers can come back with a data table and
// a chart (frappe.ui's own Chart library — no external script — see
// AlphaX CRM > api/ai_query.py for how a question becomes a
// permission-checked query instead of free-form SQL).
//
// Previously this self-injected a floating "Ask AI" circle on every screen
// on page load. That depended on frappe.ready() to know when it was safe to
// touch the DOM/session — and on this site frappe.ready never fires at all
// (confirmed live: a 20-second poll for it never succeeded, even though the
// rest of the desk worked fine the whole time). A toolbar button sidesteps
// that entirely: it only ever runs from a click, by which point the page
// is unquestionably already loaded and interactive — there is nothing left
// to wait for.
(function () {
    console.log("[AlphaX CRM] ai_assistant.js loaded");

    if (window.alphax_open_ai_assistant) return; // already defined by an earlier load

    // Call this from a list's onload (listview.page.add_inner_button) or a
    // form's refresh (frm.add_custom_button). `context` is optional —
    // {doctype, name, label} — and is what lets "summarize this" or "why is
    // this stale" mean something without the user having to name the record.
    window.alphax_open_ai_assistant = function (context) {
        alphax_ai_open_dialog(context || null);
    };

    // Shared helper so every form's "Ask AI" button builds its context the
    // same way, rather than each doctype's own JS re-deriving it slightly
    // differently. A brand-new, unsaved doc has no real name yet, so it's
    // passed as general doctype-level context instead of a specific record.
    window.alphax_ai_form_context = function (frm) {
        if (!frm || frm.is_new()) {
            return { doctype: frm ? frm.doctype : null, name: null, label: frm ? frm.doctype : "" };
        }
        return { doctype: frm.doctype, name: frm.docname, label: `${frm.doctype} ${frm.docname}` };
    };

    // Same idea for a list view: no specific record, just "I'm looking at
    // the Lead list" style context.
    window.alphax_ai_list_context = function (doctype) {
        return { doctype, name: null, label: __("{0} list", [doctype]) };
    };

    function alphax_ai_open_dialog(context) {
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
