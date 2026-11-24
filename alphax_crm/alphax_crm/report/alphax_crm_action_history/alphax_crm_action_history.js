frappe.query_reports["AlphaX CRM Action History"] = {
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
    },
    {
        "fieldname": "actor",
        "label": "Executed by",
        "fieldtype": "Link",
        "options": "User"
    }
]
};
