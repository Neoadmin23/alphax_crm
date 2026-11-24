// AlphaX CRM: adds an "Ask AI" inner button to the standard Lead list and (optionally) a Postponed
// status colour. Lead is a core ERPNext doctype (not owned by this app), so this can't live as a
// doctype-folder <n>_list.js convention file the way AlphaX PreLead's does: it's wired in explicitly
// via hooks.py's doctype_list_js instead. Preserves whatever ERPNext's own Lead list settings
// (get_indicator, onload, ...) already do, rather than clobbering them: this file only ever adds to
// what's there.
(function () {
    const existing = frappe.listview_settings["Lead"] || {};
    const base_onload = existing.onload;
    const base_indicator = existing.get_indicator;
    const fields = Array.from(new Set([...(existing.add_fields || []), "status", "alphax_next_contact_date", "alphax_last_activity"]));

    frappe.listview_settings["Lead"] = Object.assign({}, existing, {
        add_fields: fields,
        onload(listview) {
            if (typeof base_onload === "function") {
                base_onload(listview);
            }
            listview.page.add_inner_button(
                __("Ask AI"),
                () => window.alphax_open_ai_assistant(window.alphax_ai_list_context("Lead")),
                __("AlphaX")
            );
        },
        get_indicator(doc) {
            // Postponed Leads: grey while waiting, orange when due today, red when overdue with no activity.
            // Everything else keeps ERPNext's own colours.
            if (["Both", "List view"].includes(window.alphax_postponed_mode())) {
                const s = window.alphax_postponed_state(doc);
                if (s) return [s.list_label, s.color, "status,=," + doc.status];
            }
            return typeof base_indicator === "function" ? base_indicator(doc) : undefined;
        },
    });
})();
