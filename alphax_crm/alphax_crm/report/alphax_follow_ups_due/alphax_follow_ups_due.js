frappe.query_reports["AlphaX Follow-ups Due"] = {
    filters: [
        { fieldname: "agent", label: __("Agent"), fieldtype: "Link", options: "User" },
        { fieldname: "reference_doctype", label: __("Regarding"), fieldtype: "Select", options: "\nLead\nAlphaX PreLead\nOpportunity" },
        { fieldname: "within_days", label: __("Upcoming Within (days)"), fieldtype: "Int" },
    ],
    formatter: function (value, row, column, data, def) {
        value = def(value, row, column, data);
        if (data && data.state === "Overdue") value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
        return value;
    },
};
