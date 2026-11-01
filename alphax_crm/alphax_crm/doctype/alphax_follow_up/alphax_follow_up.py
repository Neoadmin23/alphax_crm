import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AlphaXFollowup(Document):
    def validate(self):
        if not self.follow_up_datetime:
            self.follow_up_datetime = now_datetime()
        if not self.agent:
            self.agent = frappe.session.user
        self.title = f"{self.channel or 'Follow-up'} · {self.reference_name}"

    def after_insert(self):
        from alphax_crm.crm.followup import process_followup
        process_followup(self)
