from odoo import models


class RasentraSyncInbox(models.Model):
    _inherit = "rasentra.sync.inbox"

    def _rasentra_handle_order_finalized(self):
        order = self.env["rasentra.hq.order"].sudo().project(self)
        if order:
            self.env["rasentra.day.reconciliation"].sudo().on_document(order)

    _rasentra_handle_order_returned = _rasentra_handle_order_finalized

    def _rasentra_handle_business_day_closed(self):
        self.env["rasentra.day.reconciliation"].sudo().record(self)

    def _rasentra_handle_stock_adjusted(self):
        self.env["rasentra.hq.stock.adjustment"].sudo().project(self)
