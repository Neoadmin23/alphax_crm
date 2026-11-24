frappe.query_reports["AlphaX Daily Follow-up Report"] = {
    filters: [
        { fieldname: "date", label: __("Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "agent", label: __("Agent"), fieldtype: "Link", options: "User" },
        { fieldname: "reference_doctype", label: __("Regarding"), fieldtype: "Select", options: "Lead\nAlphaX PreLead\nOpportunity", default: "Lead" },
        { fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nCompleted\nPending\nOverdue" },
    ],
    formatter: function (value, row, column, data, def) {
        value = def(value, row, column, data);
        if (data && column.fieldname === "status") {
            const color = { Overdue: "#b91c1c", Pending: "#c2410c", Completed: "#15803d" }[data.status];
            if (color) value = `<span style="color:${color};font-weight:600">${value}</span>`;
        }
        return value;
    },
};
