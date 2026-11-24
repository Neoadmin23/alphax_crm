// AlphaX CRM: one definition of "where is this Postponed Lead?", shared by the Lead list and the Lead form.
// Which of the two shows it is chosen in AlphaX CRM Settings > Postponed Lead Highlight.
window.alphax_postponed_mode = function () {
    const wf = (frappe.boot && frappe.boot.alphax_workflow) || {};
    return wf.postponed_highlight || "Both";
};

window.alphax_postponed_state = function (doc) {
    const wf = (frappe.boot && frappe.boot.alphax_workflow) || {};
    if (!wf.postponed || !doc || doc.status !== wf.postponed || !doc.alphax_next_contact_date) return null;
    const date = frappe.datetime.str_to_user(doc.alphax_next_contact_date);
    const days = frappe.datetime.get_diff(doc.alphax_next_contact_date, frappe.datetime.get_today());
    const n = (k) => (k === 1 ? __("1 day") : __("{0} days", [k]));
    if (days > 0) {
        return { key: "waiting", color: "gray", banner: "blue", list_label: __("Postponed · {0}", [date]),
            text: __("Postponed until {0}: {1} left.", [date, n(days)]) };
    }
    if (days === 0) {
        return { key: "due", color: "orange", banner: "orange", list_label: __("Postponed · due today"),
            text: __("Postponed Lead: the Next Contact Date is today ({0}). Contact the client or set a new date.", [date]) };
    }
    // overdue: activity on or after the due date counts as followed up
    const last = (doc.alphax_last_activity || "").slice(0, 10);
    const followed = last && frappe.datetime.get_diff(last, doc.alphax_next_contact_date) >= 0;
    if (followed) {
        return { key: "overdue_followed", color: "orange", banner: "orange", list_label: __("Postponed · overdue, followed up"),
            text: __("Postponed Lead: the Next Contact Date ({0}) passed {1} ago and there has been activity since. Set the next step.", [date, n(-days)]) };
    }
    return { key: "overdue", color: "red", banner: "red", list_label: __("Postponed · overdue, no activity"),
        text: __("Postponed Lead overdue by {0} (due {1}) with no activity since. Contact the client or set a new Next Contact Date.", [n(-days), date]) };
};
