from odoo import api, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    @api.model
    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [("rasentra_qris", "Rasentra QRIS / EDC")]
