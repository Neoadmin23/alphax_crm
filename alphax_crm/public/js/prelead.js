frappe.ui.form.on("AlphaX PreLead", {
    setup(frm) {
        frm.set_query("status", () => ({ filters: { is_active: 1 } }));
    },
    refresh(frm) {
        if (frm.doc.converted) {
            // Already converted — the real record now lives on the Lead.
            // Lock the whole form so it can't drift out of sync or confuse
            // anyone into thinking further edits here matter. Server-side
            // validate() enforces this too, for API/script access.
            frm.disable_form();
            frm.dashboard.set_headline_alert(
                __("Converted to Lead {0} — this PreLead is now read-only.", [frm.doc.lead || ""]),
                "blue"
            );
        }
        frm.add_custom_button(__("Ask AI"), () => window.alphax_open_ai_assistant(window.alphax_ai_form_context(frm)), __("AlphaX"));
        if (!frm.is_new()) {
            frm.add_custom_button(__("Follow-up History"), () => window.alphax_followup_history(frm), __("View"));
            frm.add_custom_button(__("Call History"), () => window.alphax_call_history(frm), __("View"));
            if (!frm.doc.converted) {
                frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm));
                frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), __("More"));
            }
        }
        if (frm.doc.lead) {
            frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
        }
        if (frm.doc.converted) {
            // Nothing below matters once locked — status can't change anyway.
        } else if (frm.doc.conversion_failed) {
            // Persistent — not a one-time toast. Stays until conversion
            // actually succeeds (see _clear_conversion_failure server-side),
            // so re-opening the record later still shows why it's stuck.
            frm.dashboard.set_headline_alert(
                __("Conversion to Lead failed and hasn't succeeded since: {0}",
                   [frappe.utils.escape_html(frm.doc.conversion_error || "")]),
                "red"
            );
        } else if (frm.doc.status) {
            frappe.db.get_value("AlphaX PreLead Status", frm.doc.status, "behavior").then((r) => {
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
