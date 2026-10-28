// AlphaX CRM Settings — AI Assist section extras: test the configured local
// AI endpoint, and download a one-machine setup script (Windows/macOS/Linux)
// that installs Ollama, opens a secure tunnel, and registers the resulting
// URL back into this form automatically (see api/ai_setup.py for why a web
// button can't install software on an arbitrary PC, and what this does
// instead).
frappe.ui.form.on("AlphaX CRM Settings", {
    ai_provider(frm) {
        // suggest the matching chat path when the server type changes
        if (frm.doc.ai_provider === "OpenAI Compatible" && (!frm.doc.ai_chat_path || frm.doc.ai_chat_path === "/api/chat")) {
            frm.set_value("ai_chat_path", "/v1/chat/completions");
        } else if (frm.doc.ai_provider === "Ollama" && (!frm.doc.ai_chat_path || frm.doc.ai_chat_path.includes("chat/completions"))) {
            frm.set_value("ai_chat_path", "/api/chat");
        }
    },
    refresh(frm) {
        frm.add_custom_button(__("Run Health Check"), () => alphax_health_check()).addClass("btn-primary");
        frm.add_custom_button(__("Automation Log"), () => frappe.set_route("List", "AlphaX Automation Log"), __("View"));
        frm.add_custom_button(__("Test AI Connection"), () => alphax_test_ai_connection(frm), __("AI Assist"));

        ["windows", "mac", "linux"].forEach((os_name) => {
            const labels = { windows: __("Windows"), mac: __("macOS"), linux: __("Linux") };
            frm.add_custom_button(
                labels[os_name],
                () => alphax_download_setup_script(os_name),
                __("Download AI Server Setup Script")
            );
        });

        frm.add_custom_button(__("Revoke Old Scripts (New Token)"), () => {
            frappe.confirm(
                __("Any setup script downloaded before this will stop working. Continue?"),
                () => {
                    frappe.call({
                        method: "alphax_crm.api.ai_setup.regenerate_setup_token",
                        freeze: true,
                        callback: () => frappe.show_alert({ message: __("Setup token regenerated."), indicator: "green" }),
                    });
                }
            );
        }, __("AI Assist"));

        alphax_render_ai_usage(frm);
        frappe.realtime.off("alphax_ai_endpoint_registered");
        frappe.realtime.on("alphax_ai_endpoint_registered", (data) => {
            frappe.show_alert({
                message: __("A server just registered itself as your AI endpoint ({0}). Reloading…", [data.base_url]),
                indicator: "green",
            });
            frm.reload_doc();
        });
    },
});

function alphax_test_ai_connection(frm) {
    frappe.call({
        method: "alphax_crm.api.ai_setup.test_ai_connection",
        args: {
            base_url: frm.doc.ai_base_url,
            provider: frm.doc.ai_provider,
            chat_path: frm.doc.ai_chat_path,
            model: frm.doc.ai_model,
            // ai_api_key / ai_cf_access_client_secret are Password fields —
            // the browser only ever holds a masked placeholder for those, so
            // they're deliberately left out here; the server falls back to
            // its own saved values for both. Client Id is a plain Data
            // field, so an unsaved edit can still be tried before Save.
            cf_access_client_id: frm.doc.ai_cf_access_client_id,
        },
        freeze: true,
        freeze_message: __("Testing connection…"),
        callback: (r) => {
            const res = r.message || {};
            frappe.msgprint({
                title: __("AI Connection Test"),
                message: frappe.utils.escape_html(res.message || ""),
                indicator: res.ok ? "green" : "red",
            });
        },
    });
}

// Model size is picked here, in the GUI, and baked into the generated
// script — the machine that runs it is never asked to choose anything.
const ALPHAX_HOW_TO_RUN = {
    windows: __("Just double-click {0} on that PC. A black window will show progress and close itself when done — no PowerShell, no typing."),
    mac: __("The first time, right-click {0} and choose \"Open\" (macOS blocks unsigned downloaded scripts on a plain double-click). After that, double-clicking it works directly — it opens Terminal and runs itself."),
    linux: __("Open a terminal on that machine and run: bash {0}"),
};

function alphax_download_setup_script(os_name) {
    const d = new frappe.ui.Dialog({
        title: __("Choose a Model Size"),
        fields: [
            {
                fieldname: "model_size",
                fieldtype: "Select",
                label: __("Model Size"),
                options: [
                    { value: "small", label: __("Small (llama3.2:3b) — fast, needs 8GB RAM / 5GB disk") },
                    { value: "medium", label: __("Medium (llama3.1:8b) — better quality, needs 16GB RAM / 10GB disk") },
                ],
                default: "small",
                reqd: 1,
                description: __("The setup file checks the target machine's actual RAM and free disk space against these numbers before installing anything, and asks for confirmation if it falls short — this dropdown doesn't check THIS computer, only bakes in what to look for on the one that runs it."),
            },
        ],
        primary_action_label: __("Download"),
        primary_action(values) {
            d.hide();
            frappe.call({
                method: "alphax_crm.api.ai_setup.download_setup_script",
                args: { os_name, model_size: values.model_size },
                freeze: true,
                freeze_message: __("Preparing setup file…"),
                callback: (r) => {
                    const res = r.message;
                    if (!res) return;
                    const blob = new Blob([res.content], { type: "text/plain" });
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = res.filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                    frappe.msgprint({
                        title: __("Setup File Downloaded"),
                        message: (ALPHAX_HOW_TO_RUN[os_name] || "{0}").replace(
                            "{0}",
                            `<b>${frappe.utils.escape_html(res.filename)}</b>`
                        ) + "<br><br>" + __("When it finishes, it fills in AI Base URL and Model on this form by itself — just refresh this page."),
                        indicator: "blue",
                    });
                },
            });
        },
    });
    d.show();
}

// Today's AI usage under AI Governance (calls, tokens vs. the daily limit, failures).
function alphax_render_ai_usage(frm) {
    const field = frm.get_field("ai_usage_html");
    if (!field || !frm.doc.ai_enabled) return;
    frappe.call({
        method: "alphax_crm.ai.engine.get_usage",
        callback: (r) => {
            const u = r.message || {};
            const limit = u.budget ? `${format_number(u.tokens, null, 0)} / ${format_number(u.budget, null, 0)}` : `${format_number(u.tokens, null, 0)} (${__("no limit")})`;
            field.$wrapper.html(`<div class="text-muted small" style="margin-top:8px">
                <b>${__("Usage today")}</b><br>
                ${__("AI calls")}: ${u.calls || 0} · ${__("Tokens")}: ${limit}<br>
                ${__("Failed")}: ${u.failed || 0} · ${__("Blocked")}: ${u.blocked || 0}<br>
                ${__("Server")}: ${frappe.utils.escape_html(u.provider || "")} · ${frappe.utils.escape_html(u.url || "")}<br>
                <a href="/app/alphax-ai-log">${__("Open AI Log")}</a></div>`);
        },
    });
}

// Health check: configuration, data and runtime against the approved workflow spec.
function alphax_health_check(result) {
    const show = (res) => {
        const icon = { ok: "🟢", warn: "🟠", fail: "🔴" };
        const order = { fail: 0, warn: 1, ok: 2 };
        const checks = (res.checks || []).slice().sort((a, b) => order[a.status] - order[b.status]);
        const rows = checks.map((c) => `<tr>
            <td style="white-space:nowrap">${icon[c.status] || ""}</td>
            <td><span class="text-muted small">${frappe.utils.escape_html(c.area)}</span><br><b>${frappe.utils.escape_html(c.title)}</b></td>
            <td class="small">${frappe.utils.escape_html(c.detail || "")}</td>
            <td>${c.fix ? `<button class="btn btn-xs btn-default ax-fix" data-fix="${c.fix}">${__("Fix")}</button>` : ""}</td></tr>`).join("");
        const s = res.summary || {};
        const d = new frappe.ui.Dialog({
            title: __("AlphaX Health Check"),
            size: "extra-large",
            fields: [{ fieldname: "body", fieldtype: "HTML" }],
            primary_action_label: __("Run Again"),
            primary_action() { d.hide(); alphax_health_check(); },
        });
        d.fields_dict.body.$wrapper.html(`
            <p>${icon.fail} ${__("Problems")}: ${s.fail || 0} · ${icon.warn} ${__("Warnings")}: ${s.warn || 0} · ${icon.ok} ${__("OK")}: ${s.ok || 0}</p>
            <div style="max-height:65vh;overflow:auto"><table class="table table-sm">
            <thead><tr><th></th><th>${__("Check")}</th><th>${__("Details")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`);
        d.fields_dict.body.$wrapper.find(".ax-fix").on("click", function () {
            const fix = $(this).attr("data-fix");
            frappe.confirm(__("Apply this fix to AlphaX CRM Settings?"), () =>
                frappe.call({ method: "alphax_crm.crm.health.apply_fix", args: { fix }, freeze: true }).then((r) => {
                    d.hide();
                    cur_frm && cur_frm.reload_doc();
                    show(r.message || {});
                }));
        });
        d.show();
    };
    if (result) return show(result);
    frappe.call({ method: "alphax_crm.crm.health.run_health_check", freeze: true, freeze_message: __("Checking…") })
        .then((r) => show(r.message || {}));
}
