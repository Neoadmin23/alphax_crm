from frappe.model.document import Document


class AlphaXAutomationLog(Document):
    def before_insert(self):
        from alphax_crm.crm.action_history import identity
        self.update(identity(automated=True))
        from alphax_crm.crm.sales_desk import is_exception
        self.is_sales_exception = int(is_exception(self))

    def onload(self):
        from alphax_crm.crm.sales_desk import is_exception
        self.set_onload("sales_exception", is_exception(self))

    def after_insert(self):
        from alphax_crm.crm.action_history import record
        record(self.rule, self.doctype, self.name, self.lead, True, self.result or self.subject)
