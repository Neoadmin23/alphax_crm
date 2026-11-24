frappe.query_reports["AlphaX Forecast Movement"] = {
    filters: [
    {
        "fieldname": "week_start",
        "label": "Week containing",
        "fieldtype": "Date",
        "default": frappe.datetime.get_today()
    },
    {
        "fieldname": "executive",
        "label": "Sales executive",
        "fieldtype": "Link",
        "options": "User"
    }
]
};
