frappe.query_reports["AlphaX Manager Exceptions"] = {
    filters: [
    {
        "fieldname": "state",
        "label": "State",
        "fieldtype": "Select",
        "options": "Open\nResolved",
        "default": "Open"
    },
    {
        "fieldname": "executive",
        "label": "Sales executive",
        "fieldtype": "Link",
        "options": "User"
    }
]
};
