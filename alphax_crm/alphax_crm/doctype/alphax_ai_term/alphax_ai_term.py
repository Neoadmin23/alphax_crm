import frappe
from frappe.model.document import Document


class AlphaXAITerm(Document):
	def validate(self):
		for field in ("term", "english", "arabic"):
			self.set(field, (self.get(field) or "").strip())

	def on_update(self):
		frappe.cache.delete_value("alphax_ai_terms")

	def on_trash(self):
		frappe.cache.delete_value("alphax_ai_terms")
