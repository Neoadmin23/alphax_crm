frappe.listview_settings["AlphaX Email Draft"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { Draft: "orange", Approved: "blue", Sent: "green", Cancelled: "gray", Failed: "red" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
