frappe.ui.form.on("AlphaX Prospect", {
    setup(frm) {
        frm.set_query("status", () => ({ filters: { is_active: 1 } }));
    },
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm));
            frm.add_custom_button(__("Follow-up History"), () => window.alphax_followup_history(frm), __("View"));
            frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), __("More"));
            frm.add_custom_button(__("Call History"), () => window.alphax_call_history(frm), __("View"));
        }
        if (frm.doc.lead) {
            frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
        }
        if (frm.doc.status) {
            frappe.db.get_value("AlphaX Prospect Status", frm.doc.status, "behavior").then((r) => {
                const b = r.message && r.message.behavior;
                if (b && b !== "None") {
                    frm.dashboard.set_headline_alert(
                        __("Setting this status will: {0}", [b]),
                        b === "Convert to Lead" ? "green" : "blue"
                    );
                }
            });
        }
    },
});
