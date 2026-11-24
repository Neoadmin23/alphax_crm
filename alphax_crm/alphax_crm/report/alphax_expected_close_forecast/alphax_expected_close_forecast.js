frappe.query_reports["AlphaX Expected Close Forecast"] = {
    filters: [
    {
        "fieldname": "from_date",
        "label": "From date",
        "fieldtype": "Date",
        "reqd": 1,
        "default": frappe.datetime.month_start()
    },
    {
        "fieldname": "to_date",
        "label": "To date",
        "fieldtype": "Date",
        "reqd": 1,
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
