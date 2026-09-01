frappe.ui.form.on("AlphaX Smart Lead", {
    setup(frm) {
        frm.set_query("cost_center", "service_dimensions", () => ({ filters: { is_group: 0 } }));
    },
    email(frm) {
        window.alphax_check_smart_lead_duplicate(frm);
    },
    mobile_no(frm) {
        window.alphax_check_smart_lead_duplicate(frm);
    },
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Create / Update Lead"), () => {
                frappe.call({
                    method: "alphax_crm.crm.smart_lead.sync_to_lead",
                    args: { smart_lead: frm.docname },
                    freeze: true, freeze_message: __("Mapping to ERPNext Lead..."),
                    callback: (r) => {
                        if (r.message) {
                            frappe.show_alert({ message: __("Lead {0} updated", [r.message]), indicator: "green" });
                            frm.reload_doc();
                        }
                    },
                });
            }).addClass("btn-primary");
            if (frm.doc.lead) {
                frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead), __("View"));
            }
        }
        frm.add_custom_button(__("Verify National Address"), () => {
            frappe.call({
                method: "alphax_crm.crm.smart_lead.verify_national_address",
                args: { smart_lead: frm.docname, short_address: frm.doc.na_short_address, cr_number: frm.doc.cr_number },
            }).then((r) => {
                const m = r.message || {};
                frappe.msgprint({ title: __("National Address"), message: m.message || __("Done"),
                    indicator: m.ok ? "green" : "orange" });
            });
        }, __("Tools"));

        // split total hint
        const rows = frm.doc.service_dimensions || [];
        if (rows.length) {
            const total = rows.reduce((s, r) => s + (r.split_percent || 0), 0);
            frm.dashboard.set_headline_alert(
                __("Service dimensions: {0} · split total {1}%", [rows.length, total]),
                total === 100 || total === 0 ? "green" : "orange"
            );
        }
    },
});

// Live duplicate check — fires on email/mobile blur, non-blocking. Checks
// Lead, AlphaX PreLead, and AlphaX Smart Lead by email or mobile, and
// writes a short summary into the read-only "Possible Duplicate(s)" field
// so it's visible even to someone reviewing the record later, not just at
// data-entry time.
window.alphax_check_smart_lead_duplicate = frappe.utils.debounce((frm) => {
    if (!frm.doc.email && !frm.doc.mobile_no) return;
    frappe.call({
        method: "alphax_crm.crm.smart_lead.check_duplicate",
        args: { email: frm.doc.email, mobile_no: frm.doc.mobile_no, exclude: frm.docname },
    }).then((r) => {
        const matches = r.message || [];
        if (!matches.length) {
            frm.set_value("possible_duplicate", "");
            return;
        }
        const summary = matches
            .map((m) => `${m.doctype} · ${m.title} (${m.name})`)
            .join("\n");
        frm.set_value("possible_duplicate", summary);
        frappe.show_alert({
            message: __("{0} possible duplicate(s) found — see 'Possible Duplicate(s)' below.", [matches.length]),
            indicator: "orange",
        });
    });
}, 600);
