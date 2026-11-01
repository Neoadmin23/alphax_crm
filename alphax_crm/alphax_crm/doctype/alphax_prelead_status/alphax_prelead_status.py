import frappe
from frappe.model.document import Document


class AlphaXPreLeadStatus(Document):
    def validate(self):
        if self.is_default:
            others = frappe.get_all(
                "AlphaX PreLead Status",
                filters={"is_default": 1, "name": ["!=", self.name]},
                pluck="name",
            )
            for other in others:
                frappe.db.set_value("AlphaX PreLead Status", other, "is_default", 0)
