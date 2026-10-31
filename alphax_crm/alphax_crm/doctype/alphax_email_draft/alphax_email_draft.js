// AlphaX Email Draft: nothing is emailed until a person approves it.
frappe.ui.form.on("AlphaX Email Draft", {
	refresh(frm) {
		const colors = { Draft: "orange", Approved: "blue", Sent: "green", Cancelled: "gray", Failed: "red" };
		frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		frm.toggle_enable(["subject", "body", "recipient", "cc", "send_after"], !["Sent", "Cancelled"].includes(frm.doc.status));
		if (frm.is_new()) return;

		// a real Promise, because Frappe calls .finally() on a button handler's return value
		const act = (method, label) =>
			Promise.resolve(frm.call({ doc: frm.doc, method, freeze: true })).then(() => {
				frm.reload_doc();
				frappe.show_alert({ message: label, indicator: "green" });
			});

		if (["Draft", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Approve"), () => act("approve", __("Approved. It will be sent after {0}", [frm.doc.send_after || __("now")])));
		}
		if (["Draft", "Approved", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Send Now"), () =>
				frappe.confirm(__("Send this email to {0} now?", [frappe.utils.escape_html(frm.doc.recipient)]), () => act("send_now", __("Sent")))
			).addClass("btn-primary");
			frm.add_custom_button(__("Cancel Draft"), () => act("cancel_draft", __("Cancelled")));
		}
		if (frm.doc.communication) {
			frm.add_custom_button(__("View Sent Email"), () => frappe.set_route("Form", "Communication", frm.doc.communication));
		}
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.add_custom_button(__("Open {0}", [__(frm.doc.reference_doctype)]), () =>
				frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name));
		}
	},
});
