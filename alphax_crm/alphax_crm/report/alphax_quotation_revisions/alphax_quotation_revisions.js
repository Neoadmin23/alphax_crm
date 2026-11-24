frappe.query_reports["AlphaX Quotation Revisions"] = {
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
        "label": "Quotation creator",
        "fieldtype": "Link",
        "options": "User"
    }
]
};
