import frappe
from frappe.model.document import Document


class AlphaXSmartLead(Document):
    def validate(self):
        if not self.contact_name and (self.first_name or self.last_name):
            self.contact_name = " ".join(filter(None, [self.first_name, self.last_name]))
        if not self.lead_owner:
            self.lead_owner = frappe.session.user
        self._score_completeness()

    def _score_completeness(self):
        # Non-blocking, informational only — reuses the same config-driven
        # engine Lead uses (AlphaX CRM Settings > Data Quality > Field
        # Rules). Rules are matched by fieldname per doctype, so this shows
        # 100% until rules referencing Smart Lead's own fieldnames (email,
        # organization, mobile_no, ...) are added there; Lead-only rules
        # (e.g. email_id) simply don't apply here and are skipped.
        try:
            from alphax_crm.crm.data_quality import evaluate

            result = evaluate(self)
            self.alphax_dq_score = result["score"]
            self.alphax_dq_report = result["report"]
        except Exception:
            frappe.log_error(title="AlphaX CRM: smart lead dq score", message=frappe.get_traceback())

    def after_insert(self):
        from alphax_crm.crm.smart_lead import maybe_sync_to_lead
        maybe_sync_to_lead(self, on_insert=True)

    def on_update(self):
        from alphax_crm.crm.smart_lead import maybe_sync_to_lead
        maybe_sync_to_lead(self, on_insert=False)
