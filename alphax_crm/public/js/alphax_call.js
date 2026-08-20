// Shared "Log a Call" dialog for AlphaX CRM (Prospect + Lead).
window.alphax_log_call = function (frm) {
    const d = new frappe.ui.Dialog({
        title: __("Log a Call"),
        fields: [
            { fieldtype: "Select", fieldname: "call_type", label: __("Direction"),
              options: "Outgoing\nIncoming", default: "Outgoing", reqd: 1 },
            { fieldtype: "Select", fieldname: "status", label: __("Outcome"),
              options: "Completed\nNo Answer\nBusy\nLeft Voicemail\nWrong Number\nCall Back Requested",
              default: "Completed", reqd: 1 },
            { fieldtype: "Column Break" },
            { fieldtype: "Duration", fieldname: "duration", label: __("Duration") },
            { fieldtype: "Date", fieldname: "follow_up_date", label: __("Next Follow-up Date") },
            { fieldtype: "Section Break" },
            { fieldtype: "Small Text", fieldname: "summary", label: __("Summary / Notes") },
        ],
        primary_action_label: __("Log Call"),
        primary_action(values) {
            frappe.call({
                method: "alphax_crm.crm.activity.log_call",
                args: {
                    reference_doctype: frm.doctype,
                    reference_name: frm.docname,
                    call_type: values.call_type,
                    status: values.status,
                    duration: values.duration || 0,
                    summary: values.summary || "",
                    follow_up_date: values.follow_up_date || null,
                },
                freeze: true,
                freeze_message: __("Logging call..."),
                callback: () => {
                    d.hide();
                    frappe.show_alert({ message: __("Call logged"), indicator: "green" });
                    frm.reload_doc();
                },
            });
        },
    });
    d.show();
};

// Route to the phone-call history (Communications, medium = Phone) for a doc.
window.alphax_call_history = function (frm) {
    frappe.route_options = {
        reference_doctype: frm.doctype,
        reference_name: frm.docname,
        communication_medium: "Phone",
    };
    frappe.set_route("List", "Communication");
};

// ---- Complete follow-up mechanism (Lead / Prospect / Opportunity) ----
window.alphax_log_followup = function (frm) {
    const d = new frappe.ui.Dialog({
        title: __("Log Follow-up"),
        fields: [
            { fieldtype: "Select", fieldname: "channel", label: __("Channel"),
              options: "Call\nEmail\nWhatsApp\nMeeting\nVisit\nSMS\nOther", default: "Call", reqd: 1 },
            { fieldtype: "Select", fieldname: "meeting_type", label: __("Meeting Type"),
              options: "\nOnline Meeting\nOn-site Meeting",
              depends_on: 'eval:doc.channel=="Meeting"', mandatory_depends_on: 'eval:doc.channel=="Meeting"' },
            { fieldtype: "Select", fieldname: "direction", label: __("Direction"),
              options: "Outgoing\nIncoming", default: "Outgoing" },
            { fieldtype: "Column Break" },
            { fieldtype: "Select", fieldname: "outcome", label: __("Outcome"),
              options: "Connected\nNo Answer\nBusy\nLeft Voicemail\nRescheduled\nInterested\nNot Interested\nCallback Requested\nCompleted",
              default: "Connected" },
            { fieldtype: "Duration", fieldname: "duration", label: __("Duration") },
            { fieldtype: "Section Break" },
            { fieldtype: "Small Text", fieldname: "summary", label: __("Summary / Notes"), reqd: 1 },
            { fieldtype: "Section Break", label: __("Next step") },
            { fieldtype: "Small Text", fieldname: "next_action", label: __("Next Action") },
            { fieldtype: "Date", fieldname: "next_follow_up_date", label: __("Next Follow-up Date") },
        ],
        primary_action_label: __("Save Follow-up"),
        primary_action(v) {
            frappe.call({
                method: "alphax_crm.crm.followup.log_followup",
                args: {
                    reference_doctype: frm.doctype, reference_name: frm.docname,
                    channel: v.channel, meeting_type: v.meeting_type || "", direction: v.direction, outcome: v.outcome,
                    duration: v.duration || 0, summary: v.summary || "",
                    next_action: v.next_action || "", next_follow_up_date: v.next_follow_up_date || null,
                },
                freeze: true, freeze_message: __("Saving follow-up..."),
                callback: () => {
                    d.hide();
                    frappe.show_alert({ message: __("Follow-up saved"), indicator: "green" });
                    frm.reload_doc();
                },
            });
        },
    });
    d.show();
};

window.alphax_followup_history = function (frm) {
    frappe.call({
        method: "alphax_crm.crm.followup.get_history",
        args: { reference_doctype: frm.doctype, reference_name: frm.docname },
    }).then((r) => {
        const rows = r.message || [];
        if (!rows.length) {
            frappe.msgprint({ title: __("Follow-up History"), message: __("No follow-ups logged yet.") });
            return;
        }
        const body = rows.map((f) => {
            const when = frappe.datetime.str_to_user(f.follow_up_datetime);
            const nxt = f.next_follow_up_date ? ` · <b>next</b> ${frappe.datetime.str_to_user(f.next_follow_up_date)}` : "";
            return `<div style="padding:8px 0;border-bottom:1px solid #eee">
                <div><b>${f.channel}${f.meeting_type ? " · " + f.meeting_type : ""}</b> (${f.direction || ""}) — ${f.outcome || ""} · <span style="color:#888">${when}</span></div>
                <div>${frappe.utils.escape_html(f.summary || "")}</div>
                <div style="color:#5b21b6">${f.next_action ? "→ " + frappe.utils.escape_html(f.next_action) : ""}${nxt}</div>
                <div style="color:#999;font-size:11px">${f.agent || ""} · ${f.name}</div></div>`;
        }).join("");
        frappe.msgprint({ title: __("Follow-up History ({0})", [rows.length]), message: body, wide: true });
    });
};
