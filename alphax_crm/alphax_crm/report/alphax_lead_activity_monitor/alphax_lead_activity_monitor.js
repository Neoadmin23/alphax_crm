frappe.query_reports["AlphaX Lead Activity Monitor"] = {
    filters: [
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "MultiSelectList",
            get_data: function () {
                return (frappe.query_reports["AlphaX Lead Activity Monitor"].__status_options || []).map(
                    (o) => ({ value: o, description: "" })
                );
            },
        },
        { fieldname: "lead_owner", label: __("Lead Owner"), fieldtype: "Link", options: "User" },
        { fieldname: "idle_over_days", label: __("Idle Over (days)"), fieldtype: "Int" },
        { fieldname: "only_monitored", label: __("Only Monitored Statuses"), fieldtype: "Check", default: 1 },
        { fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
    ],
    onload: function (report) {
        // Populate the Status multiselect from Lead.status options, and default
        // to the configured default monitored status.
        frappe.db.get_doc("DocType", "Lead").then((d) => {
            const f = (d.fields || []).find((x) => x.fieldname === "status");
            const opts = (f && f.options ? f.options.split("\n") : []).filter(Boolean);
            frappe.query_reports["AlphaX Lead Activity Monitor"].__status_options = opts;
        });
        frappe.call("alphax_crm.crm.tasks.get_default_monitored_status").then((r) => {
            if (r.message) report.set_filter_value("status", [r.message]);
        });
        // Add configured extra fields as dynamic filters (Link where possible).
        frappe.call("alphax_crm.crm.tasks.get_monitor_fields", { target: "Lead" }).then((r) => {
            (r.message || []).forEach((mf) => {
                if (!mf.as_filter) return;
                if (report.get_filter && report.get_filter(mf.fieldname)) return;
                const df = {
                    fieldname: mf.fieldname,
                    label: mf.label,
                    fieldtype: mf.fieldtype === "Link" ? "Link" : "Data",
                };
                if (mf.fieldtype === "Link") df.options = mf.options;
                report.page.add_field(df);
            });
        });
    },
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (data && data.overdue === "Yes" && (column.fieldname === "idle_days" || column.fieldname === "overdue")) {
            value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
        }
        return value;
    },
};
