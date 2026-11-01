import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime, validate_email_address


class AlphaXEmailDraft(Document):
	def validate(self):
		self.recipient = (self.recipient or "").strip()
		validate_email_address(self.recipient, throw=True)
		if self.cc:
			validate_email_address(self.cc, throw=True)
		if not self.is_new() and self.status in ("Sent", "Cancelled"):
			before = self.get_doc_before_save()
			if before and before.status == self.status and (before.body != self.body or before.subject != self.subject):
				frappe.throw(_("A {0} email cannot be edited.").format(_(self.status)))

	@frappe.whitelist()
	def approve(self):
		self._require_write()
		if self.status not in ("Draft", "Failed"):
			frappe.throw(_("Only drafts can be approved."))
		self.status = "Approved"
		self.approved_by = frappe.session.user
		self.error = None
		self.save()
		return self.status

	@frappe.whitelist()
	def send_now(self):
		self._require_write()
		if self.status in ("Draft", "Failed"):
			self.approve()
		if self.status != "Approved":
			frappe.throw(_("Only approved drafts can be sent."))
		if self.send_after and get_datetime(self.send_after) > now_datetime():
			self.db_set("send_after", now_datetime())
		from alphax_crm.ai.sales import send_draft

		send_draft(self.name)
		self.reload()
		return self.status

	@frappe.whitelist()
	def cancel_draft(self):
		self._require_write()
		if self.status == "Sent":
			frappe.throw(_("This email has already been sent."))
		self.status = "Cancelled"
		self.save()
		return self.status

	def _require_write(self):
		if not self.has_permission("write"):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
