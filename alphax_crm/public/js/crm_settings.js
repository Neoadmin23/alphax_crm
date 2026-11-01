// AlphaX CRM Settings — AI Assist section extras: test the configured local
// AI endpoint, and download a one-machine setup script (Windows/macOS/Linux)
// that installs Ollama, opens a secure tunnel, and registers the resulting
// URL back into this form automatically (see api/ai_setup.py for why a web
// button can't install software on an arbitrary PC, and what this does
// instead).
frappe.ui.form.on("AlphaX CRM Settings", {
    ai_preset(frm) {
        alphax_apply_preset(frm);
    },
    ai_model(frm) {
        alphax_render_model_info(frm);
    },
    ai_fast_model(frm) {
        alphax_render_model_info(frm);
    },
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
        frm.add_custom_button(__("Open Models Guide"), () => alphax_models_guide(frm), __("AI Assist"));
        frm.add_custom_button(__("Find Models on Server"), () => alphax_find_models(frm), __("AI Assist"));
        frm.add_custom_button(__("Test Model"), () => alphax_self_test(frm, "main"), __("AI Assist"));
        if (frm.doc.ai_fast_model) {
            frm.add_custom_button(__("Test Fast Model"), () => alphax_self_test(frm, "fast"), __("AI Assist"));
        }
        alphax_render_model_info(frm);
        alphax_selftest_indicators(frm);

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
                    { value: "large", label: __("Large (qwen3.8:27b) — all AI features, needs a 24GB GPU / 32GB RAM / 25GB disk") },
                ],
                default: "small",
                reqd: 1,
                description: __("The setup file checks the target machine's actual RAM and free disk space against these numbers before installing anything, and asks for confirmation if it falls short — this dropdown doesn't check THIS computer, only bakes in what to look for on the one that runs it."),
            },
        ],
        secondary_action_label: __("Which model? Open Models Guide"),
        secondary_action() {
            alphax_models_guide(cur_frm);
        },
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


// ---------------------------------------------------------------- open models guide / discovery / self-test
let alphax_catalogue_cache = null;
function alphax_catalogue() {
    if (alphax_catalogue_cache) return Promise.resolve(alphax_catalogue_cache);
    return frappe.xcall("alphax_crm.ai.models.get_catalogue").then((r) => (alphax_catalogue_cache = r));
}

const ALPHAX_STATUS_COLOR = { Passed: "green", Partial: "orange", Failed: "red", "Not tested": "gray" };
const ALPHAX_USE_COLOR = { main: "green", light: "blue", datacentre: "purple" };

function alphax_apply_preset(frm) {
    const name = frm.doc.ai_preset;
    if (!name || name === "Custom") return;
    alphax_catalogue().then((cat) => {
        const p = cat.presets[name];
        if (!p) return;
        const placeholders = Object.values(cat.presets).map((x) => x.base_url);
        // provider first: its change handler suggests a path, which the preset then overrides
        Promise.resolve(frm.set_value("ai_provider", p.provider)).then(() => {
            frm.set_value("ai_chat_path", p.chat_path);
            // hosted services have one fixed address; for self-hosted servers keep an address the admin
            // already typed and only replace empty/default/other-preset placeholders
            const cur = (frm.doc.ai_base_url || "").trim();
            if (p.fixed_url || !cur || cur === "http://localhost:11434" || placeholders.includes(cur)) {
                frm.set_value("ai_base_url", p.base_url);
            }
        });
        frappe.show_alert({ message: p.help, indicator: p.external ? "orange" : "green" }, 10);
        if (p.needs_key) frappe.show_alert({ message: __("This preset needs an API Key."), indicator: "blue" }, 8);
    });
}

function alphax_model_badge(info) {
    if (!info || !info.model) return "";
    const esc = frappe.utils.escape_html;
    let html = `<b>${esc(info.model)}</b>: `;
    if (info.known) {
        html += `${esc(info.known)} · ${esc(info.licence || "")} · ${__("Arabic")}: ${esc(info.arabic || "")} · `
            + `<span class="indicator-pill ${ALPHAX_USE_COLOR[info.use_code] || "gray"}">${esc(info.use || "")}</span>`;
    } else {
        html += `<span class="text-muted">${__("not in the Open Models Guide — run Test Model to check it")}</span>`;
    }
    if (info.free_tier) html += ` <span class="indicator-pill orange">${__("Free tier · External")}</span>`;
    return html;
}

function alphax_render_model_info(frm) {
    const field = frm.get_field("ai_model_info");
    if (!field) return;
    const base = frm.doc.ai_base_url || "";
    const calls = [frm.doc.ai_model, frm.doc.ai_fast_model].map((m) =>
        m ? frappe.xcall("alphax_crm.ai.models.describe_model", { model: m, base_url: base }) : Promise.resolve(null));
    Promise.all(calls).then(([main, fast]) => {
        const rows = [];
        if (main) rows.push(__("Model") + " — " + alphax_model_badge(main));
        if (fast) rows.push(__("Fast Model") + " — " + alphax_model_badge(fast));
        field.$wrapper.html(rows.length ? `<div class="ax-model-info small" style="line-height:2">${rows.join("<br>")}</div>` : "");
    });
}

function alphax_selftest_indicators(frm) {
    // the main model's self-test verdict sits next to the form title
    const st = frm.doc.ai_selftest_status;
    if (frm.doc.ai_enabled && st) frm.page.set_indicator(`${__("Model test")}: ${__(st)}`, ALPHAX_STATUS_COLOR[st] || "gray");
}

function alphax_models_guide(frm) {
    alphax_catalogue().then((cat) => {
        const esc = frappe.utils.escape_html;
        const d = new frappe.ui.Dialog({
            title: __("Open Models Guide"),
            size: "extra-large",
            fields: [
                { fieldname: "use", fieldtype: "Select", label: __("Show"),
                    options: [{ value: "", label: __("All models") }].concat(
                        Object.entries(cat.uses).map(([value, label]) => ({ value, label }))),
                    change: () => render() },
                { fieldname: "intro", fieldtype: "HTML" },
                { fieldname: "table", fieldtype: "HTML" },
            ],
        });
        d.fields_dict.intro.$wrapper.html(`<div class="small text-muted" style="margin-bottom:8px">${__(
            "Free to download and use; each model runs on your own GPU server (Ollama or vLLM) and AlphaX connects to it. "
            + "Ratings are guidance; Test Model is the real check on your server. Use 27B-class models or larger as the main model; "
            + "small models are fine as Fast Model for spell check and translation.")}</div>`);
        function render() {
            const filter = d.get_value("use");
            const rows = cat.models.filter((m) => !filter || m.use === filter).map((m) => `
                <tr data-key="${esc(m.key)}">
                    <td><b>${esc(m.name)}</b>${m.recommended ? ` <span class="indicator-pill green">${__("Recommended")}</span>` : ""}
                        <div class="text-muted small">${esc(m.vendor)} · ${esc(m.params)} · ${esc(m.context)} ${__("context")}</div>
                        <div class="small">${esc(m.note || "")}</div></td>
                    <td class="small">${esc(m.licence)}</td>
                    <td class="small">${esc(m.gpu)}</td>
                    <td class="small">${esc(m.arabic)}</td>
                    <td><span class="indicator-pill ${ALPHAX_USE_COLOR[m.use] || "gray"}">${esc(m.use_label)}</span></td>
                    <td class="small"><code>${esc(m.ollama || "—")}</code><br><span class="text-muted">vLLM: ${esc(m.hf)}</span>
                        <br><span class="text-muted">${__("tool parser")}: ${esc(m.vllm_tool_parser)}</span></td>
                    <td style="white-space:nowrap">
                        ${m.ollama || m.hf.includes("/") ? `<button class="btn btn-xs btn-default ax-use" data-target="ai_model">${__("Use as Model")}</button><br>
                        <button class="btn btn-xs btn-default ax-use" data-target="ai_fast_model" style="margin-top:4px">${__("Use as Fast Model")}</button>` : ""}
                    </td>
                </tr>`).join("");
            d.fields_dict.table.$wrapper.html(`<div style="max-height:60vh;overflow:auto"><table class="table table-bordered ax-models-guide">
                <thead><tr><th>${__("Model")}</th><th>${__("Licence")}</th><th>${__("GPU size")}</th><th>${__("Arabic")}</th>
                <th>${__("Suitable for")}</th><th>${__("Name to use")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`);
            d.fields_dict.table.$wrapper.find(".ax-use").on("click", function () {
                const key = $(this).closest("tr").data("key");
                const m = cat.models.find((x) => x.key === key);
                const vllm = frm.doc.ai_provider === "OpenAI Compatible";
                const name = vllm && m.hf.includes("/") ? m.hf : (m.ollama || m.hf);
                frm.set_value($(this).data("target"), name);
                frappe.show_alert({ message: __("{0} set to {1}. Save, then run Test Model.", [__($(this).data("target") === "ai_model" ? "Model" : "Fast Model"), name]), indicator: "green" });
                d.hide();
            });
        }
        render();
        d.show();
    });
}

function alphax_find_models(frm) {
    if (!frm.doc.ai_base_url) {
        frappe.msgprint(__("Enter the AI Base URL first."));
        return;
    }
    frappe.call({
        method: "alphax_crm.ai.models.list_server_models",
        args: { base_url: frm.doc.ai_base_url, provider: frm.doc.ai_provider },
        freeze: true,
        freeze_message: __("Reading the models installed on the server…"),
    }).then((r) => {
        const res = r.message || {};
        if (!res.ok) {
            frappe.msgprint({ title: __("Find Models on Server"), message: frappe.utils.escape_html(res.message || ""), indicator: "red" });
            return;
        }
        const esc = frappe.utils.escape_html;
        const d = new frappe.ui.Dialog({
            title: __("Models on {0}", [res.url.replace(/\/(api\/tags|v1\/models|models)$/, "")]),
            size: "large",
            fields: [
                { fieldname: "search", fieldtype: "Data", label: __("Filter"), change: () => render() },
                { fieldname: "summary", fieldtype: "HTML" },
                { fieldname: "list", fieldtype: "HTML" },
            ],
        });
        d.fields_dict.summary.$wrapper.html(`<div class="small text-muted">${esc(res.message)}</div>`);
        function render() {
            const q = (d.get_value("search") || "").toLowerCase();
            const rows = res.models.filter((m) => !q || m.model.toLowerCase().includes(q)).slice(0, 300).map((m) => `
                <tr data-model="${esc(m.model)}">
                    <td><code>${esc(m.model)}</code>${m.free_tier ? ` <span class="indicator-pill orange">${__("Free tier · External")}</span>` : ""}</td>
                    <td class="small">${m.known ? `<b>${esc(m.known)}</b><br>${esc(m.use)} · ${__("Arabic")}: ${esc(m.arabic)}`
                        : `<span class="text-muted">${__("not in the guide")}</span>`}</td>
                    <td style="white-space:nowrap"><button class="btn btn-xs btn-primary ax-pick" data-target="ai_model">${__("Use as Model")}</button>
                        <button class="btn btn-xs btn-default ax-pick" data-target="ai_fast_model">${__("Use as Fast Model")}</button></td>
                </tr>`).join("");
            d.fields_dict.list.$wrapper.html(rows ? `<div style="max-height:55vh;overflow:auto"><table class="table table-bordered ax-server-models">
                <thead><tr><th>${__("Installed model")}</th><th>${__("Open Models Guide")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
                : `<p class="text-muted">${__("No models found. On Ollama run: ollama pull qwen3.8:27b")}</p>`);
            d.fields_dict.list.$wrapper.find(".ax-pick").on("click", function () {
                const model = $(this).closest("tr").data("model");
                const target = $(this).data("target");
                frm.set_value(target, String(model));
                frappe.show_alert({ message: __("Filled in {0}. Save, then run Test Model.", [String(model)]), indicator: "green" });
                d.hide();
            });
        }
        render();
        d.show();
    });
}

function alphax_self_test(frm, target) {
    const go = () => frappe.call({
        method: "alphax_crm.ai.models.run_self_test",
        args: { target },
        freeze: true,
        freeze_message: __("Testing the model: 4 checks, one in Arabic…"),
    }).then((r) => {
        const res = r.message || {};
        const esc = frappe.utils.escape_html;
        const rows = (res.checks || []).map((c) => `<tr><td>${c.ok ? "✅" : "❌"}</td><td><b>${esc(__(c.name))}</b></td>
            <td class="small">${esc(c.detail || "")}</td><td class="small text-muted">${c.seconds} s</td></tr>`).join("");
        const explain = {
            Passed: __("This model can run every AlphaX AI feature, including automatic ones."),
            Partial: __("Usable, but some checks failed: review drafts carefully and consider a larger model."),
            Failed: target === "main"
                ? __("Automatic AI (classification, next best action, intent detection, reminders, sequences, Ask AI) is paused for this model.")
                : __("The Fast Model will not be used; the main model takes over spell check and translation."),
        }[res.status] || "";
        frappe.msgprint({
            title: __("Model Self-Test: {0}", [esc(res.model || "")]),
            indicator: ALPHAX_STATUS_COLOR[res.status] || "gray",
            message: `<p><span class="indicator-pill ${ALPHAX_STATUS_COLOR[res.status] || "gray"}">${esc(__(res.status || ""))}</span> ${explain}</p>
                <table class="table table-bordered ax-selftest">${rows}</table>`,
        });
        frm.reload_doc();
    });
    if (frm.is_dirty()) {
        frm.save().then(go);
    } else {
        go();
    }
}
