// AlphaX CRM Settings — AI Assist section extras: test the configured local
// AI endpoint, and download a one-machine setup script (Windows/macOS/Linux)
// that installs Ollama, opens a secure tunnel, and registers the resulting
// URL back into this form automatically (see api/ai_setup.py for why a web
// button can't install software on an arbitrary PC, and what this does
// instead).
frappe.ui.form.on("AlphaX CRM Settings", {
    refresh(frm) {
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
            chat_path: frm.doc.ai_chat_path,
            model: frm.doc.ai_model,
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

function alphax_download_setup_script(os_name) {
    frappe.call({
        method: "alphax_crm.api.ai_setup.download_setup_script",
        args: { os_name },
        freeze: true,
        freeze_message: __("Preparing script…"),
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
                title: __("Setup Script Downloaded"),
                message: __(
                    "Run {0} as described in the comments at the top of the file, on the ONE PC or server you want as your shared AI server. When it finishes, it will fill in AI Base URL and Model on this form by itself — just refresh this page.",
                    [`<b>${frappe.utils.escape_html(res.filename)}</b>`]
                ),
                indicator: "blue",
            });
        },
    });
}
