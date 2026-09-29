import frappe
from frappe.model.document import Document


class AlphaXCRMSettings(Document):
    def validate(self):
        if self.auto_opportunity_threshold and not (0 <= self.auto_opportunity_threshold <= 100):
            frappe.throw("Auto-Opportunity Score Threshold must be between 0 and 100.")
        if self.ai_enabled and not self.ai_base_url:
            frappe.throw("AI Base URL is required when AI Assist is enabled.")
