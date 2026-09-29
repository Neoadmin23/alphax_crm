// AlphaX CRM — PreLead list: the data-entry workbench.
// Smart Import (upload → auto-convert → dump into PreLead, Lead, or Smart
// Lead), status colors, bulk conversion to Lead for users who hold that
// permission.
frappe.listview_settings["AlphaX PreLead"] = {
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
        listview.page.add_inner_button(__("Import Logs"), () => frappe.set_route("List", "AlphaX Import Log"), __("AlphaX"));
        if (frappe.user.has_role("Sales Manager") || frappe.user.has_role("System Manager")) {
            listview.page.add_inner_button(__("Executive Dashboard"), () => frappe.set_route("alphax-executive-dashboard"), __("AlphaX"));
        }

        if (frappe.model.can_create("Lead")) {
            listview.page.add_actions_menu_item(__("Convert to Lead"), () => {
                const names = listview.get_checked_items(true);
                if (!names.length) return;
                frappe.confirm(__("Convert {0} pre-lead(s) to Leads?", [names.length]), () => {
                    frappe.call({
                        method: "alphax_crm.crm.prelead.bulk_convert_to_lead",
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
    "AlphaX PreLead": __("PreLeads — calling list, operator qualifies to Lead"),
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

function alphax_scan_and_confirm(listview, file_url, import_as, existing_dialog, column_map) {
    frappe.call({
        method: "alphax_crm.api.lead_import.scan_file",
        args: { file_url, import_as, column_map: column_map ? JSON.stringify(column_map) : undefined },
        freeze: true,
        freeze_message: __("Scanning file…"),
        callback: (r) => {
            if (existing_dialog) existing_dialog.hide();
            alphax_confirm_import(listview, file_url, r.message, column_map || null);
        },
    });
}

function alphax_confirm_import(listview, file_url, scan, column_map) {
    const missing = scan.missing_masters || {};
    const doctypes = Object.keys(missing);
    const fields = [];

    let summary_html = `<p><b>${scan.total_rows}</b> ${__("rows found.")}<br>
        ${__("Mapped fields")}: ${frappe.utils.escape_html(scan.mapped_fields.join(", "))}</p>`;
    const header_notices = scan.header_notices || [];
    if (header_notices.length) {
        const lines = header_notices
            .map((n) => __("Column {0}: {1} → \"{2}\"", [
                n.column,
                n.from ? `"${frappe.utils.escape_html(n.from)}"` : __("(blank)"),
                frappe.utils.escape_html(n.to),
            ]))
            .join("<br>");
        summary_html += `<div class="alert alert-warning">${__(
            "Some column headers in the file were blank or repeated — the second one would otherwise silently overwrite the first, so they were renamed automatically:"
        )}<br>${lines}<br>${__("Check Correct Columns to point any of these at the right field.")}</div>`;
    }
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
    if (column_map) {
        summary_html += `<p class="text-success">${__("Columns corrected manually — see Correct Columns to review or change.")}</p>`;
    }
    fields.push({ fieldtype: "HTML", options: summary_html });
    fields.push({
        fieldtype: "Button",
        fieldname: "correct_columns_btn",
        label: __("Correct Columns…"),
        click() {
            alphax_correct_columns(listview, file_url, scan, column_map);
        },
    });

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
        label: __("Skip duplicates (matching email or mobile in Leads, PreLeads, or Smart Leads)"),
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
                    column_map: column_map ? JSON.stringify(column_map) : undefined,
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

// Manual column-correction step: one row per column in the file, each with
// a dropdown of every importable field on the target doctype (pre-filled
// with AlphaX's best guess, or the user's previous correction), plus the
// column's own header text and a sample value so a column in a language or
// layout Smart Import doesn't recognize can still be pointed at the right
// field — entirely inside the app, no need to edit the file first.
function alphax_correct_columns(listview, file_url, scan, existing_column_map) {
    const headers = scan.raw_headers || [];
    const suggestions = scan.column_suggestions || {};
    const samples = scan.column_samples || {};
    const importable = scan.importable_fields || [];

    const field_options = [{ value: "", label: __("-- Skip this column --") }].concat(
        importable.map((f) => ({
            value: f.fieldname,
            label: f.reqd ? `${f.label} *` : f.label,
        }))
    );

    const fields = [
        {
            fieldtype: "HTML",
            options: `<p class="text-muted">${__(
                "Pick which field each column in your file should fill. Fields marked * are required — leaving one unmapped will fail every row unless it can be filled another way."
            )}</p>`,
        },
    ];

    headers.forEach((h, i) => {
        const current = (existing_column_map && Object.prototype.hasOwnProperty.call(existing_column_map, h))
            ? (existing_column_map[h] || "")
            : (suggestions[h] || "");
        const sample = samples[h];
        fields.push({ fieldtype: "Section Break" });
        fields.push({
            fieldtype: "HTML",
            options: `<div style="padding-top:6px">
                <b>${frappe.utils.escape_html(h)}</b>
                ${sample ? `<div class="text-muted small">${__("e.g.")} "${frappe.utils.escape_html(String(sample).slice(0, 60))}"</div>` : ""}
            </div>`,
        });
        fields.push({ fieldtype: "Column Break" });
        fields.push({
            fieldname: `col_${i}`,
            fieldtype: "Select",
            options: field_options,
            default: current,
        });
    });

    const d = new frappe.ui.Dialog({
        title: __("Correct Columns"),
        fields,
        size: "large",
        primary_action_label: __("Apply & Re-check"),
        primary_action(values) {
            const column_map = {};
            headers.forEach((h, i) => {
                column_map[h] = values[`col_${i}`] || "";
            });
            const reqd_fieldnames = importable.filter((f) => f.reqd).map((f) => f.fieldname);
            const mapped_fieldnames = new Set(Object.values(column_map).filter(Boolean));
            const missing_reqd = reqd_fieldnames.filter((fn) => !mapped_fieldnames.has(fn) && fn !== "status");
            const proceed = () => {
                d.hide();
                alphax_scan_and_confirm(listview, file_url, scan.import_as, null, column_map);
            };
            if (missing_reqd.length) {
                const labels = importable.filter((f) => missing_reqd.includes(f.fieldname)).map((f) => f.label);
                frappe.confirm(
                    __("No column is mapped to required field(s): {0}. Rows may fail to import. Continue anyway?", [
                        labels.join(", "),
                    ]),
                    proceed
                );
            } else {
                proceed();
            }
        },
    });
    d.show();
}

function alphax_show_summary(s) {
    const noun_map = {
        "AlphaX PreLead": __("pre-leads created."),
        "AlphaX Smart Lead": __("smart leads created."),
        "Lead": __("leads created."),
    };
    let html = `<p><b>${s.inserted}</b> ${noun_map[s.target] || __("records created.")}</p>`;
    const created = s.created_masters || {};
    Object.keys(created).forEach((dt) => {
        html += `<p>${__("Created {0}", [frappe.utils.escape_html(dt)])}:
            ${frappe.utils.escape_html(created[dt].join(", "))}</p>`;
    });
    if (s.merged && s.merged.length) {
        html += `<p class="text-muted">${__("Merged {0} row(s) into an earlier match in this same file (same email/mobile/phone) instead of dropping their extra data", [s.merged.length])}:
            ${s.merged.map((x) => __("row {0} → {1}", [x.row, x.into])).join(", ")}</p>`;
    }
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
    if (s.log_file_url) {
        html += `<p><a href="${s.log_file_url}" target="_blank" class="btn btn-sm btn-default">
            ${__("Download Result Excel (status + error per row)")}</a>
            ${s.log_name ? `<span class="text-muted small" style="margin-left:8px">${__("Log")}: ${frappe.utils.escape_html(s.log_name)}</span>` : ""}
            </p>`;
    }
    frappe.msgprint({
        title: __("Smart Import Result"),
        message: html,
        indicator: s.failed && s.failed.length ? "orange" : "green",
    });
}
