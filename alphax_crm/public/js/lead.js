// AlphaX CRM — live data-quality feedback on the Lead form.
frappe.ui.form.on("Lead", {
    refresh(frm) {
        alphax_dq_render(frm);
        frm.add_custom_button(__("Check Data Quality"), () => alphax_dq_render(frm, true), __("AlphaX"));
        if (!frm.is_new()) {
            frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm));
            frm.add_custom_button(__("Follow-up History"), () => window.alphax_followup_history(frm), __("View"));
            frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), __("More"));
            frm.add_custom_button(__("Call History"), () => window.alphax_call_history(frm), __("View"));
            frm.add_custom_button(__("Activity Monitor"), () => alphax_open_activity_monitor(frm), __("View"));
            alphax_activity_headline(frm);
        }
    },
    onload_post_render(frm) {
        alphax_dq_bind(frm);
    },
});

function alphax_dq_bind(frm) {
    // Re-check as the user edits, debounced.
    if (frm.__alphax_dq_bound) return;
    frm.__alphax_dq_bound = true;
    frm.$wrapper.on("change awesomplete-selectcomplete", "input, select, textarea", () => {
        clearTimeout(frm.__alphax_dq_t);
        frm.__alphax_dq_t = setTimeout(() => alphax_dq_render(frm), 500);
    });
}

function alphax_dq_render(frm, verbose) {
    if (frm.is_new() && !verbose && !frm.doc.lead_name) return;
    frappe.call({
        method: "alphax_crm.crm.data_quality.check",
        args: { doc: frm.doc },
        callback: (r) => {
            const d = r.message;
            if (!d) return;
            const color = d.issues.length ? "red" : (d.warnings.length ? "orange" : "green");
            const label = `Data Quality: ${d.score}%` +
                (d.issues.length ? ` — ${d.issues.length} to fix` : "") +
                (d.warnings.length ? ` — ${d.warnings.length} recommended` : "");
            frm.dashboard.clear_headline();
            frm.dashboard.set_headline_alert(label, color);

            // Highlight offending fields.
            (frm.__alphax_dq_marked || []).forEach((f) => frm.set_df_property(f, "description", ""));
            frm.__alphax_dq_marked = [];
            d.issues.concat(d.warnings).forEach((it) => {
                if (frm.fields_dict[it.field]) {
                    frm.set_df_property(it.field, "description",
                        `<span style="color:${it.kind === "invalid" ? "#b91c1c" : "#b45309"}">⚠ ${frappe.utils.escape_html(it.reason)}</span>`);
                    frm.__alphax_dq_marked.push(it.field);
                }
            });

            if (verbose) {
                const lines = d.issues.map((i) => `• <b>${frappe.utils.escape_html(i.label)}</b> ${frappe.utils.escape_html(i.reason)}`)
                    .concat(d.warnings.map((w) => `• ${frappe.utils.escape_html(w.label)} ${frappe.utils.escape_html(w.reason)} <i>(recommended)</i>`));
                frappe.msgprint({
                    title: __("Data Quality — {0}%", [d.score]),
                    message: lines.length ? lines.join("<br>") : __("All configured checks passed."),
                    indicator: color,
                });
            }
        },
    });
}

// ---- Activity monitor helpers (on-screen) ----
function alphax_activity_headline(frm) {
    const on = frm.doc.alphax_last_activity;
    const idle = frm.doc.alphax_idle_days;
    if (!on && (idle === undefined || idle === null)) return;
    let txt = __("Last activity");
    if (frm.doc.alphax_last_activity_type) txt += `: ${frm.doc.alphax_last_activity_type}`;
    if (frm.doc.alphax_last_activity_by) txt += ` — ${frm.doc.alphax_last_activity_by}`;
    if (on) txt += ` · ${frappe.datetime.comment_when(on)}`;
    if (idle !== undefined && idle !== null) txt += ` · ${__("idle {0}d", [idle])}`;
    const color = idle >= 5 ? "red" : idle >= 3 ? "orange" : "green";
    frm.dashboard.add_indicator(txt, color);
}

// On-screen status selector -> open the Activity Monitor for chosen status(es).
function alphax_open_activity_monitor(frm) {
    frappe.db.get_doc("DocType", "Lead").then((d) => {
        const f = (d.fields || []).find((x) => x.fieldname === "status");
        const opts = (f && f.options ? f.options.split("\n") : []).filter(Boolean);
        const dlg = new frappe.ui.Dialog({
            title: __("Last Activity by Status"),
            fields: [
                { fieldtype: "MultiSelectPills", fieldname: "status", label: __("Status"),
                  get_data: () => opts.map((o) => ({ value: o, description: "" })),
                  default: frm.doc.status ? [frm.doc.status] : [] },
                { fieldtype: "Int", fieldname: "idle_over_days", label: __("Idle Over (days)") },
            ],
            primary_action_label: __("Open Report"),
            primary_action(v) {
                dlg.hide();
                frappe.route_options = {
                    status: v.status && v.status.length ? v.status : undefined,
                    idle_over_days: v.idle_over_days || 0,
                    only_monitored: v.status && v.status.length ? 0 : 1,
                };
                frappe.set_route("query-report", "AlphaX Lead Activity Monitor");
            },
        });
        dlg.show();
    });
}
