from odoo import fields, models

from .rasentra_sap_document import STATUSES

SAP_STATES = [s for s in STATUSES if s[0] not in ("validated", "posting")] + [("locked", "Terkunci")]


class RasentraHqOrder(models.Model):
    _inherit = "rasentra.hq.order"

    sap_state = fields.Selection(SAP_STATES, string="Status SAP", default="pending", index=True, readonly=True)
    sap_document_ids = fields.One2many("rasentra.sap.document", "hq_order_id", string="Dokumen SAP")

    def _set_sap_state(self, state):
        self.write({"sap_state": state})
        return state

    def _sap_state_from_documents(self):
        statuses = set(self.sap_document_ids.mapped("status"))
        if not statuses:
            return "pending"
        if statuses == {"posted"}:
            expected = 2  # invoice + pembayaran, atau credit memo + refund
            return "posted" if len(self.sap_document_ids) >= expected else "partially_posted"
        if "posted" in statuses:
            return "partially_posted"
        for state in ("needs_review", "waiting_dependency", "failed"):
            if state in statuses:
                return state
        return "pending"

    def action_sap_post_now(self):
        Document = self.env["rasentra.sap.document"]
        for order in self:
            Document.post_order(order)
        return True
