frappe.ui.form.on("AlphaX Automation Log", {
    refresh(frm) {
        if (frm.is_new()) return;
        const rows = frm.doc.delivery_attempts || [];
        if (rows.some(r => r.channel === "Email" && r.result === "Queued")) {
            frm.add_custom_button(__("Email delivery status"), async () => {
                const receipts = await frappe.xcall("alphax_crm.crm.delivery.transport_status", {log_name: frm.doc.name});
                const list = $("<ul>");
                receipts.forEach(r => {
                    const item = $("<li>").text(r.recipient + " · " + r.status + " ");
                    $("<a>").attr("href", frappe.utils.get_form_link("Email Queue", r.queue)).text(r.queue).appendTo(item);
                    list.append(item);
                });
                frappe.msgprint({title:__("Email delivery status"),message:receipts.length ? list.prop("outerHTML") : __("No accessible Email Queue entries yet.")});
            });
        }
        const latest = new Map(rows.map(row => [JSON.stringify([row.recipient, row.channel]), row]));
        if (frappe.user_roles.includes("System Manager")) {
            const failed = Array.from(latest.values()).filter(row => row.result === "Failed");
            if (failed.length) {
                const labels = failed.map(r => r.recipient + " · " + r.channel);
                frm.add_custom_button(__("Retry failed channel"), () => frappe.prompt([
                    {fieldname: "receipt", fieldtype: "Select", label: __("Recipient and channel"), options: labels.join("\n"), reqd: 1}
                ], async v => {
                    const row = failed[labels.indexOf(v.receipt)];
                    await frappe.xcall("alphax_crm.crm.delivery.retry_channel", {
                        log_name: frm.doc.name, recipient: row.recipient, channel: row.channel
                    });
                    await frm.reload_doc();
                }, __("Retry delivery"), __("Retry")));
            }
        }
        if (!frm.doc.lead || frm.doc.resolution === "Resolved" || !(frm.doc.is_sales_exception || frm.doc.__onload?.sales_exception)) return;
        if (!frappe.user_roles.some(role => ["System Manager", "Sales Manager"].includes(role))) return;
        frm.add_custom_button(__("Manage exception"), () => frappe.prompt([
            {fieldname:"decision",fieldtype:"Select",label:__("Action"),options:"Assign\nResolve",reqd:1},
            {fieldname:"assignee",fieldtype:"Link",label:__("Assign to"),options:"User",depends_on:"eval:doc.decision=='Assign'"},
            {fieldname:"note",fieldtype:"Small Text",label:__("Action note"),reqd:1}
        ], async v => {
            await frappe.xcall("alphax_crm.crm.sales_desk.manage_exception", {log_name:frm.doc.name,...v});
            await frm.reload_doc();
        }, __("Manage exception"), __("Save")));
    }
});
