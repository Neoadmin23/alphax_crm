// AlphaX AI on Quotation: draft a polite expiry reminder (a person approves it before sending).
frappe.ui.form.on("Quotation", {
    refresh(frm) {
        if (frm.doc.docstatus !== 1 || !frappe.boot.alphax_ai) return;
        frm.add_custom_button(__("Draft Expiry Reminder"), () => {
            frappe.prompt(
                [{ fieldname: "language", fieldtype: "Select", label: __("Language"), options: "\nEnglish\nArabic", description: __("Leave blank to match the lead’s language.") }],
                (v) => frappe.call({
                    method: "alphax_crm.ai.sales.api_draft_quotation_reminder",
                    args: { quotation: frm.doc.name, language: v.language },
                    freeze: true,
                    freeze_message: __("Writing the reminder…"),
                }).then((r) => r.message && frappe.set_route("Form", "AlphaX Email Draft", r.message)),
                __("Draft Expiry Reminder"),
                __("Draft")
            );
        }, __("AlphaX AI"));
    },
});
