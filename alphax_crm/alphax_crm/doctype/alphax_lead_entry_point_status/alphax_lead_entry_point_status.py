import frappe
from frappe.model.document import Document


class AlphaXLeadEntryPointStatus(Document):
    def validate(self):
        if self.is_default:
            others = frappe.get_all(
                "AlphaX Lead Entry Point Status",
                filters={"is_default": 1, "name": ["!=", self.name]},
                pluck="name",
            )
            for other in others:
                frappe.db.set_value("AlphaX Lead Entry Point Status", other, "is_default", 0)
