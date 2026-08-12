frappe.query_reports["AlphaX Owner Activity Summary"] = {
    filters: [
        {
            fieldname: "document_type",
            label: __("Document Type"),
            fieldtype: "Select",
            options: "Lead\nOpportunity\nProspect",
            default: "Lead",
            reqd: 1,
        },
        { fieldname: "only_overdue", label: __("Only With Overdue"), fieldtype: "Check" },
    ],
    onload: function (report) {
        const map = { Lead: "Lead", Opportunity: "Opportunity", Prospect: "AlphaX Prospect" };
        const target = map[(report.get_filter_value && report.get_filter_value("document_type")) || "Lead"];
        frappe.call("alphax_crm.crm.tasks.get_monitor_fields", { target: target }).then((r) => {
            (r.message || []).forEach((mf) => {
                if (!mf.as_filter) return;
                if (report.get_filter && report.get_filter(mf.fieldname)) return;
                const df = { fieldname: mf.fieldname, label: mf.label, fieldtype: mf.fieldtype === "Link" ? "Link" : "Data" };
                if (mf.fieldtype === "Link") df.options = mf.options;
                report.page.add_field(df);
            });
        });
    },
};
