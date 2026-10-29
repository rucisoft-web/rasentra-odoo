from odoo import fields, models

from .rasentra_hq_order import SAP_STATES


class RasentraHqStockAdjustment(models.Model):
    _inherit = "rasentra.hq.stock.adjustment"

    sap_state = fields.Selection(
        SAP_STATES + [("not_required", "Tidak perlu SAP")], string="Status SAP", default="pending", index=True,
        readonly=True,
    )
    sap_document_ids = fields.One2many("rasentra.sap.document", "hq_stock_adjustment_id", string="Dokumen SAP")

    def _set_sap_state(self, state):
        self.write({"sap_state": state})
        return state

    def _sap_state_from_documents(self):
        statuses = set(self.sap_document_ids.mapped("status"))
        if not statuses:
            return "pending"
        if statuses == {"posted"}:
            return "posted"
        if "posted" in statuses:
            return "partially_posted"
        for state in ("needs_review", "failed"):
            if state in statuses:
                return state
        return "pending"

    def action_sap_post_now(self):
        for adjustment in self:
            self.env["rasentra.sap.document"].post_stock_adjustment(adjustment)
        return True
