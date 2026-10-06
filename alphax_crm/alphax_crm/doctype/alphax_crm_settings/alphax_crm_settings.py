import frappe
from frappe.model.document import Document


class AlphaXCRMSettings(Document):
    def validate(self):
        if self.auto_opportunity_threshold and not (0 <= self.auto_opportunity_threshold <= 100):
            frappe.throw("Auto-Opportunity Score Threshold must be between 0 and 100.")
        if self.ai_enabled and not self.ai_base_url:
            frappe.throw("AI Base URL is required when AI Assist is enabled.")

    def on_update(self):
        # Whatever Lead Stage values this mapping names, make sure Lead's
        # native `status` field actually accepts them — otherwise the very
        # next time automation tries to use a newly typed mapping value, the
        # save gets blocked by Frappe's own Select validation with no
        # obvious link back to this table. See ensure_select_option() in
        # crm/utils.py for the full story.
        try:
            from alphax_crm.crm.lead import sync_lead_stage_options

            sync_lead_stage_options(self)
        except Exception:
            frappe.log_error(title="AlphaX CRM: sync lead stage options", message=frappe.get_traceback())
