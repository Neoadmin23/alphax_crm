// AlphaX CRM — live data-quality feedback on the Lead form.
frappe.ui.form.on("Lead", {
    refresh(frm) {
        alphax_wf_refresh(frm);
        alphax_dq_render(frm);
        frm.add_custom_button(__("Check Data Quality"), () => alphax_dq_render(frm, true), __("AlphaX"));
        frm.add_custom_button(__("Ask AI"), () => window.alphax_open_ai_assistant(window.alphax_ai_form_context(frm)), __("AlphaX"));
        if (!frm.is_new()) {
            frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm));
            frm.add_custom_button(__("Follow-up History"), () => window.alphax_followup_history(frm), __("View"));
            frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), __("More"));
            frm.add_custom_button(__("Call History"), () => window.alphax_call_history(frm), __("View"));
            frm.add_custom_button(__("Activity Monitor"), () => alphax_open_activity_monitor(frm), __("View"));
            alphax_activity_headline(frm);
            alphax_sales_ai_buttons(frm);
        }
    },
    onload_post_render(frm) {
        alphax_dq_bind(frm);
    },
    status(frm) {
        alphax_wf_postponed_prompt(frm);
    },
});

// ---------------------------------------------------------------------------
// Approved workflow on the form (crm/workflow.py): only approved stages in the
// Lead Stage dropdown, a Next Contact Date prompt for Postponed, and banners
// for anything waiting on the user's confirmation.
// ---------------------------------------------------------------------------
function alphax_wf_refresh(frm) {
    const wf = frappe.boot.alphax_workflow;
    if (wf && wf.enabled && wf.stages && wf.stages.length) {
        const current = frm.doc.status;
        const options = wf.stages.slice();
        if (current && !options.includes(current)) options.unshift(current); // legacy value stays visible
        frm.set_df_property("status", "options", options.join("\n"));
    }
    // own banner at the top of the form: the headline slot is used by the Data Quality / activity
    // banners and the v15 dashboard area lives inside the Connections tab
    frm.layout.wrapper.find(".ax-wf-banner").remove();
    const notes = [];
    if (frm.doc.alphax_proposed_action) {
        notes.push(["orange", `⚠ ${frappe.utils.escape_html(frm.doc.alphax_proposed_action)}. ${__("Use AlphaX AI → Confirm Lost Quotation, or extend the quotation.")}`]);
    }
    if (frm.doc.alphax_ai_suggested_stage) {
        notes.push(["blue", `✦ ${__("AI suggests moving this Lead to")} <b>${frappe.utils.escape_html(frm.doc.alphax_ai_suggested_stage)}</b>
            — ${frappe.utils.escape_html((frm.doc.alphax_ai_intent || "").split(" — ")[0])}. ${__("Use AlphaX AI → Apply Suggested Stage to confirm.")}`]);
    }
    notes.forEach(([color, html]) => {
        $(`<div class="ax-wf-banner form-message ${color}" style="margin-bottom:8px"><div>${html}</div></div>`).prependTo(frm.layout.wrapper);
    });
}

function alphax_wf_postponed_prompt(frm) {
    const wf = frappe.boot.alphax_workflow;
    if (!wf || !wf.require_next_contact || frm.doc.status !== wf.postponed) return;
    if (frm.__alphax_pp_prompting) return;
    frm.__alphax_pp_prompting = true;
    const d = new frappe.ui.Dialog({
        title: __("Postpone Lead"),
        fields: [
            { fieldname: "date", fieldtype: "Date", label: __("Next Contact Date"), reqd: 1,
              default: frappe.datetime.add_days(frappe.datetime.get_today(), 30) },
            { fieldname: "note", fieldtype: "Small Text", label: __("Why is it postponed? (added as a comment)") },
        ],
        primary_action_label: __("Postpone"),
        primary_action(v) {
            if (v.date < frappe.datetime.get_today()) {
                frappe.msgprint(__("The Next Contact Date must be today or later."));
                return;
            }
            frm.set_value("alphax_next_contact_date", v.date);
            if (v.note && !frm.is_new()) frappe.xcall("frappe.desk.form.utils.add_comment", {
                reference_doctype: "Lead", reference_name: frm.doc.name, content: frappe.utils.escape_html(v.note),
                comment_email: frappe.session.user, comment_by: frappe.session.user_fullname,
            });
            d.hide();
        },
    });
    d.onhide = () => { frm.__alphax_pp_prompting = false; };
    d.show();
}

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

// ---------------------------------------------------------------------------
// Sales AI (alphax_crm/ai/sales.py): next best action, website research,
// follow-up email drafts that a person approves before anything is sent.
// ---------------------------------------------------------------------------
function alphax_sales_ai_buttons(frm) {
    if (!frappe.boot.alphax_ai) return;
    const group = __("AlphaX AI");
    // return a real Promise: Frappe calls .finally() on it to re-enable the toolbar button
    const run = (method, args, busy, done) =>
        Promise.resolve(frappe.call({ method, args, freeze: true, freeze_message: busy })).then((r) => {
            frm.reload_doc();
            if (done) done(r.message || {});
        });

    frm.add_custom_button(__("Next Best Action"), () =>
        run("alphax_crm.ai.sales.api_next_action", { lead: frm.doc.name }, __("Thinking about the next step…"), (m) =>
            frappe.show_alert({ message: __("Next action: {0}", [frappe.utils.escape_html((m.alphax_ai_next_action || "").split("\n")[0])]), indicator: "green" }, 8)
        ), group);

    frm.add_custom_button(__("Research Website"), () => {
        if (!frm.doc.website) {
            frappe.msgprint(__("Add the lead's website first."));
            return;
        }
        run("alphax_crm.ai.sales.api_research_website", { lead: frm.doc.name }, __("Reading {0}…", [frappe.utils.escape_html(frm.doc.website)]),
            () => frappe.show_alert({ message: __("Company brief updated"), indicator: "green" }));
    }, group);

    frm.add_custom_button(__("Draft Follow-up Emails"), () => {
        if (!frm.doc.email_id) {
            frappe.msgprint(__("Add the lead's email address first."));
            return;
        }
        const d = new frappe.ui.Dialog({
            title: __("Draft Follow-up Emails"),
            fields: [
                { fieldname: "steps", fieldtype: "Int", label: __("Number of emails"), default: 3,
                  description: __("Sent on the days set in AlphaX CRM Settings, after you approve each one") },
                { fieldname: "purpose", fieldtype: "Select", label: __("Purpose"), options: "Follow-up\nRe-engagement", default: "Follow-up" },
                { fieldname: "language", fieldtype: "Select", label: __("Language"), options: "English\nArabic",
                  default: frm.doc.language === "ar" ? "Arabic" : "English" },
                { fieldname: "instruction", fieldtype: "Small Text", label: __("Anything to mention? (optional)") },
            ],
            primary_action_label: __("Create Drafts"),
            primary_action(v) {
                d.hide();
                frappe.call({
                    method: "alphax_crm.ai.sales.api_draft_followups",
                    args: { lead: frm.doc.name, ...v },
                    freeze: true,
                    freeze_message: __("Writing {0} emails…", [v.steps || 3]),
                }).then((r) => {
                    const names = r.message || [];
                    frappe.show_alert({ message: __("{0} drafts created. Review and approve them before they are sent.", [names.length]), indicator: "green" }, 8);
                    frappe.set_route("List", "AlphaX Email Draft", { reference_doctype: "Lead", reference_name: frm.doc.name });
                });
            },
        });
        d.show();
    }, group);

    frm.add_custom_button(__("AI Lead Brief"), () =>
        run("alphax_crm.ai.sales.api_lead_brief", { lead: frm.doc.name }, __("Summarising the history…"),
            () => frappe.show_alert({ message: __("AI brief updated"), indicator: "green" })), group);

    if (frm.doc.alphax_ai_suggested_stage) {
        frm.add_custom_button(__("Apply Suggested Stage ({0})", [__(frm.doc.alphax_ai_suggested_stage)]), () => {
            const stage = frm.doc.alphax_ai_suggested_stage;
            const wf = frappe.boot.alphax_workflow || {};
            const fields = [{ fieldtype: "HTML", options: `<p>${__("Move this Lead to <b>{0}</b>? All workflow rules still apply.", [frappe.utils.escape_html(stage)])}</p>
                <p class="text-muted small">${frappe.utils.escape_html(frm.doc.alphax_ai_intent || "")}</p>` }];
            if (stage === wf.postponed) fields.push({ fieldname: "next_contact_date", fieldtype: "Date", label: __("Next Contact Date"), reqd: 1 });
            frappe.prompt(fields, (v) => run("alphax_crm.ai.sales.apply_suggested_stage",
                { lead: frm.doc.name, next_contact_date: v.next_contact_date }, __("Updating…")), __("Confirm Stage"), __("Apply"));
        }, group);
    }

    if (frm.doc.status === "Quotation" || frm.doc.alphax_proposed_action) {
        frm.add_custom_button(__("Confirm Lost Quotation"), () => alphax_confirm_lost(frm), group);
    }

    frm.add_custom_button(__("Email Drafts"), () =>
        frappe.set_route("List", "AlphaX Email Draft", { reference_doctype: "Lead", reference_name: frm.doc.name }), __("View"));
}

function alphax_confirm_lost(frm) {
    frappe.call({ method: "alphax_crm.crm.workflow.lead_quotations", args: { lead: frm.doc.name } }).then((r) => {
        const rows = r.message || [];
        if (!rows.length) {
            frappe.msgprint(__("There is no open submitted quotation linked to this Lead."));
            return;
        }
        const d = new frappe.ui.Dialog({
            title: __("Confirm Lost Quotation"),
            fields: [
                { fieldname: "quotation", fieldtype: "Select", label: __("Quotation"), reqd: 1,
                  options: rows.map((q) => q.name), default: rows[0].name,
                  description: rows.map((q) => `${q.name}: ${format_currency(q.grand_total, q.currency)}, ${__("valid till")} ${frappe.datetime.str_to_user(q.valid_till) || "-"}`).join("<br>") },
                { fieldname: "reason", fieldtype: "Link", options: "Quotation Lost Reason", label: __("Lost Reason"), reqd: 1 },
                { fieldname: "detailed_reason", fieldtype: "Small Text", label: __("Details") },
            ],
            primary_action_label: __("Mark as Lost"),
            primary_action(v) {
                d.hide();
                Promise.resolve(frappe.call({ method: "alphax_crm.crm.workflow.confirm_lost_quotation", args: v, freeze: true }))
                    .then(() => { frm.reload_doc(); frappe.show_alert({ message: __("Marked as Lost Quotation"), indicator: "orange" }); });
            },
        });
        d.show();
    });
}
