// AlphaX CRM — adds an "Ask AI" inner button to the standard Lead list.
// Lead is a core ERPNext doctype (not owned by this app), so this can't
// live as a doctype-folder <name>_list.js convention file the way AlphaX
// PreLead's does — it's wired in explicitly via hooks.py's
// doctype_list_js instead. Preserves whatever ERPNext's own Lead list
// settings (get_indicator, onload, ...) already do, rather than clobbering
// them — this file only ever adds to what's there.
(function () {
    const existing = frappe.listview_settings["Lead"] || {};
    const base_onload = existing.onload;

    frappe.listview_settings["Lead"] = Object.assign({}, existing, {
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
    });
})();
