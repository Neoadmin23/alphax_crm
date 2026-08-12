frappe.ui.form.on("Opportunity", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm));
        frm.add_custom_button(__("Follow-up History"), () => window.alphax_followup_history(frm), __("View"));
        frm.add_custom_button(
            __("Refresh AI Brief"),
            () => {
                frappe.call({
                    method: "alphax_crm.crm.opportunity.refresh_brief",
                    args: { opportunity: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Asking AlphaX AI..."),
                    callback: (r) => {
                        if (r.message) {
                            frm.reload_doc();
                            frappe.show_alert({ message: __("AI brief updated"), indicator: "green" });
                        }
                    },
                });
            },
            __("AlphaX")
        );
    },
});
