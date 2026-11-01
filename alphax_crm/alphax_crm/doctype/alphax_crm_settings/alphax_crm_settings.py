import frappe
from frappe.model.document import Document


class AlphaXCRMSettings(Document):
    def validate(self):
        if self.auto_opportunity_threshold and not (0 <= self.auto_opportunity_threshold <= 100):
            frappe.throw("Auto-Opportunity Score Threshold must be between 0 and 100.")
        if self.ai_enabled and not self.ai_base_url:
            frappe.throw("AI Base URL is required when AI Assist is enabled.")
        self._check_ai_residency()
        self._ai_model_state()

    def _ai_model_state(self):
        """Self-test results belong to one server + model: any change resets them to Not tested.
        Free-tier hosted models are flagged (always External)."""
        from alphax_crm.ai import catalogue, engine
        from alphax_crm.ai.models import STATUS_FIELDS

        if not self.meta.has_field("ai_selftest_status"):
            return
        prov = engine.provider(self)
        for model_f, status_f, details_f, on_f, fp_f in STATUS_FIELDS.values():
            fp = catalogue.fingerprint(prov, self.ai_base_url, self.ai_chat_path, self.get(model_f))
            if self.get(fp_f) and self.get(fp_f) != fp or not self.get(model_f):
                self.set(status_f, "Not tested")
                self.set(details_f, "")
                self.set(on_f, None)
                self.set(fp_f, "")
        free = any(catalogue.is_free_tier(self.ai_base_url, self.get(f)) for f in ("ai_model", "ai_fast_model"))
        self.ai_free_tier = 1 if free else 0
        if free and self.get("ai_enabled") and self.get("ai_residency_mode"):
            frappe.msgprint(
                frappe._("A free-tier hosted model is selected. Free tiers are always External, so KSA Data Residency "
                    "Mode blocks every AI call while it is selected."),
                title=frappe._("Free-tier model is External"), indicator="orange")

    def _check_ai_residency(self):
        """Warn (not block) when KSA Data Residency Mode would refuse the configured AI server."""
        if not (self.get("ai_enabled") and self.get("ai_residency_mode")):
            return
        from urllib.parse import urlparse

        from alphax_crm.ai import engine, pure

        host = urlparse(engine.chat_url(self)).hostname or ""
        allowed = (self.get("ai_allowed_hosts") or "").splitlines()
        if not (pure.is_private_host(host) or pure.host_allowed(host, allowed)):
            frappe.msgprint(
                frappe._("KSA Data Residency Mode is on, but the AI server {0} is not on a private network and "
                    "not in Allowed AI Hosts, so AI calls will be blocked. Add it to Allowed AI Hosts only if "
                    "it is hosted in the Kingdom.").format(host or "?"),
                title=frappe._("AI calls will be blocked"), indicator="orange")

    def on_update(self):
        # AI writing-tools config is part of each user's cached boot info: refresh it for everyone
        frappe.cache.delete_key("bootinfo")
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
