frappe.query_reports["AlphaX My Sales Worklist"] = {
    filters: [
    {
        "fieldname": "days",
        "label": "Days ahead",
        "fieldtype": "Int",
        "default": 7
    }
]
};

Object.assign(frappe.query_reports["AlphaX My Sales Worklist"], {
    formatter(value, row, column, data, format) {
        if (!data || column.fieldname !== "task") return format(value, row, column, data);
        const el = $("<button>", {type: "button", class: "btn btn-xs btn-default ax-work-action", text: __(data.task)});
        el.attr({"data-task": data.task, "data-lead": data.lead, "data-kind": data.reference_doctype, "data-name": data.reference_name});
        return el.prop("outerHTML");
    },
    onload(report) {
        $(report.page.wrapper).off("click.ax-work").on("click.ax-work", ".ax-work-action", function () {
            const {task, lead, kind, name} = this.dataset;
            if (["Make first contact", "Contact postponed Lead", "Follow up contract"].includes(task)) {
                return window.alphax_log_followup({doctype: "Lead", docname: lead, reload_doc: () => report.refresh()});
            }
            if (task === "Schedule meeting") {
                return frappe.new_doc("Event", {}, doc => {
                    doc.subject = __("Meeting with {0}", [lead]);
                    frappe.model.add_child(doc, "Event Participants", "event_participants").reference_doctype = "Lead";
                    doc.event_participants[doc.event_participants.length - 1].reference_docname = lead;
                });
            }
            if (task === "Prepare quotation") {
                return frappe.new_doc("Quotation", {quotation_to:"Lead", party_name:lead});
            }
            frappe.set_route("Form", kind, name);
        });
    }
});
