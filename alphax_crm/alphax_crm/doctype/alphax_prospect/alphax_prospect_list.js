// AlphaX CRM — Prospect list: the data-entry workbench.
// Smart Import (upload → auto-convert → dump into Prospect, Lead, or Smart
// Lead), status colors, bulk conversion to Lead for users who hold that
// permission.
frappe.listview_settings["AlphaX Prospect"] = {
    get_indicator(doc) {
        const map = {
            New: "blue",
            Contacted: "orange",
            Interested: "green",
            "Not Interested": "gray",
            Invalid: "red",
            Converted: "purple",
        };
        return [__(doc.status), map[doc.status] || "gray", "status,=,"+doc.status];
    },

    onload(listview) {
        listview.page.add_inner_button(__("Smart Import"), () => alphax_pick_file(listview), __("AlphaX"));

        if (frappe.model.can_create("Lead")) {
            listview.page.add_actions_menu_item(__("Convert to Lead"), () => {
                const names = listview.get_checked_items(true);
                if (!names.length) return;
                frappe.confirm(__("Convert {0} prospect(s) to Leads?", [names.length]), () => {
                    frappe.call({
                        method: "alphax_crm.api.prospect.convert_to_lead",
                        args: { names },
                        freeze: true,
                        freeze_message: __("Converting…"),
                        callback: (r) => {
                            const res = r.message || {};
                            let html = `<p><b>${(res.converted || []).length}</b> ${__("leads created.")}</p>`;
                            if (res.failed && res.failed.length) {
                                html += `<p class="text-danger">${__("Failed")}:</p><ul>`;
                                res.failed.forEach((x) => {
                                    html += `<li>${frappe.utils.escape_html(x.prospect)}: ${frappe.utils.escape_html(x.reason)}</li>`;
                                });
                                html += "</ul>";
                            }
                            frappe.msgprint({
                                title: __("Conversion Result"),
                                message: html,
                                indicator: res.failed && res.failed.length ? "orange" : "green",
                            });
                            listview.refresh();
                        },
                    });
                });
            }, false);
        }

        frappe.realtime.on("alphax_lead_import_done", (summary) => {
            alphax_show_summary(summary);
            listview.refresh();
        });
    },
};

// Doctype -> human label shown in the "Import As" selector.
const ALPHAX_IMPORT_TARGET_LABELS = {
    "AlphaX Prospect": __("Prospects — calling list, operator qualifies to Lead"),
    "Lead": __("Leads — create directly"),
    "AlphaX Smart Lead": __("Smart Leads — canonical entry, auto-maps to a Lead"),
};

function alphax_pick_file(listview) {
    new frappe.ui.FileUploader({
        allow_multiple: false,
        restrictions: { allowed_file_types: [".csv", ".tsv", ".xlsx"] },
        folder: "Home/Attachments",
        on_success(file) {
            alphax_scan_and_confirm(listview, file.file_url);
        },
    });
}

function alphax_scan_and_confirm(listview, file_url, import_as, existing_dialog) {
    frappe.call({
        method: "alphax_crm.api.lead_import.scan_file",
        args: { file_url, import_as },
        freeze: true,
        freeze_message: __("Scanning file…"),
        callback: (r) => {
            if (existing_dialog) existing_dialog.hide();
            alphax_confirm_import(listview, file_url, r.message);
        },
    });
}

function alphax_confirm_import(listview, file_url, scan) {
    const missing = scan.missing_masters || {};
    const doctypes = Object.keys(missing);
    const fields = [];

    let summary_html = `<p><b>${scan.total_rows}</b> ${__("rows found.")}<br>
        ${__("Mapped fields")}: ${frappe.utils.escape_html(scan.mapped_fields.join(", "))}</p>`;
    const derived = scan.derived_fields || {};
    if (Object.keys(derived).length) {
        const lines = Object.keys(derived)
            .map((f) => `${frappe.utils.escape_html(f)} ← ${frappe.utils.escape_html(derived[f].join(" → "))}`)
            .join("<br>");
        summary_html += `<p><b>${__("Auto-converted columns")}</b>:<br>
            <span class="text-muted">${lines}</span></p>`;
    }
    if (scan.unmapped_columns.length) {
        summary_html += `<p class="text-muted">${__("Ignored columns (no matching field)")}:
            ${frappe.utils.escape_html(scan.unmapped_columns.join(", "))}</p>`;
    }
    fields.push({ fieldtype: "HTML", options: summary_html });

    const available = scan.available_targets && scan.available_targets.length
        ? scan.available_targets
        : [scan.import_as];
    const target_options = available.map((dt) => ({
        value: dt,
        label: ALPHAX_IMPORT_TARGET_LABELS[dt] || dt,
    }));
    fields.push({
        fieldname: "import_as",
        label: __("Import As"),
        fieldtype: "Select",
        options: target_options,
        default: scan.import_as,
        reqd: 1,
        read_only: target_options.length === 1 ? 1 : 0,
    });

    if (doctypes.length) {
        fields.push({
            fieldtype: "HTML",
            options: `<div class="alert alert-warning">${__(
                "Some values in the file do not exist as master records yet. Choose what to do for each:"
            )}</div>`,
        });
        doctypes.forEach((dt, i) => {
            const info = missing[dt];
            fields.push({
                fieldtype: "HTML",
                options: `<p><b>${frappe.utils.escape_html(dt)}</b>
                    (${__("used in")}: ${frappe.utils.escape_html(info.fields.join(", "))})<br>
                    <span class="text-muted">${frappe.utils.escape_html(info.values.join(" · "))}</span></p>`,
            });
            fields.push({
                fieldname: `decision_${i}`,
                label: __("Action for {0}", [dt]),
                fieldtype: "Select",
                options: [
                    { value: "create", label: __("Yes — create automatically") },
                    { value: "skip", label: __("No — skip (leave field blank)") },
                ],
                default: "create",
            });
        });
    }

    fields.push({
        fieldname: "default_source",
        label: __("Default Source (applied to rows without one)"),
        fieldtype: "Link",
        options: "Lead Source",
    });
    fields.push({
        fieldname: "skip_duplicates",
        label: __("Skip duplicates (matching email or mobile in Leads, Prospects, or Smart Leads)"),
        fieldtype: "Check",
        default: 1,
    });
    fields.push({
        fieldname: "run_ai",
        label: __("Run AI classification on imported leads (one background job per lead)"),
        fieldtype: "Check",
        default: 0,
        depends_on: 'eval:doc.import_as=="Lead"',
    });

    const d = new frappe.ui.Dialog({
        title: doctypes.length ? __("Missing Master Data") : __("Confirm Import"),
        fields,
        size: "large",
        primary_action_label: __("Import"),
        primary_action(values) {
            const decisions = {};
            doctypes.forEach((dt, i) => (decisions[dt] = values[`decision_${i}`] || "skip"));
            d.hide();
            frappe.call({
                method: "alphax_crm.api.lead_import.run_import",
                args: {
                    file_url,
                    decisions: JSON.stringify(decisions),
                    skip_duplicates: values.skip_duplicates ? 1 : 0,
                    run_ai: values.run_ai ? 1 : 0,
                    default_source: values.default_source || null,
                    import_as: values.import_as,
                },
                freeze: true,
                freeze_message: __("Importing…"),
                callback: (r) => {
                    if (r.message && r.message.queued) {
                        frappe.msgprint(
                            __("Large file ({0} rows) — import queued in background. You will be notified when it completes.", [
                                r.message.total_rows,
                            ])
                        );
                    } else {
                        alphax_show_summary(r.message);
                        listview.refresh();
                    }
                },
            });
        },
    });

    // Switching the target re-scans against that doctype's own fields, since
    // missing masters and name-field mapping depend on which one is picked.
    if (target_options.length > 1) {
        d.fields_dict.import_as.df.onchange = () => {
            const chosen = d.get_value("import_as");
            if (chosen && chosen !== scan.import_as) {
                alphax_scan_and_confirm(listview, file_url, chosen, d);
            }
        };
    }

    d.show();
}

function alphax_show_summary(s) {
    const noun_map = {
        "AlphaX Prospect": __("prospects created."),
        "AlphaX Smart Lead": __("smart leads created."),
        "Lead": __("leads created."),
    };
    let html = `<p><b>${s.inserted}</b> ${noun_map[s.target] || __("records created.")}</p>`;
    const created = s.created_masters || {};
    Object.keys(created).forEach((dt) => {
        html += `<p>${__("Created {0}", [frappe.utils.escape_html(dt)])}:
            ${frappe.utils.escape_html(created[dt].join(", "))}</p>`;
    });
    if (s.skipped && s.skipped.length) {
        html += `<p class="text-muted">${__("Skipped {0} duplicate row(s)", [s.skipped.length])}:
            ${s.skipped.map((x) => __("row {0}", [x.row])).join(", ")}</p>`;
    }
    if (s.failed && s.failed.length) {
        html += `<p class="text-danger">${__("Failed rows")}:</p><ul>`;
        s.failed.forEach((x) => {
            html += `<li>${__("Row {0}", [x.row])}: ${frappe.utils.escape_html(x.reason)}</li>`;
        });
        html += "</ul>";
    }
    frappe.msgprint({
        title: __("Smart Import Result"),
        message: html,
        indicator: s.failed && s.failed.length ? "orange" : "green",
    });
}
