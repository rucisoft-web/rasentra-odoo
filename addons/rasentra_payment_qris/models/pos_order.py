from odoo import _, models

from odoo.addons.rasentra_core.tools import RasentraError, money


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _rasentra_check_before_paid(self):
        """QRIS/EDC terintegrasi hanya sah dengan konfirmasi provider (transaction_id = uuid intent)."""
        super()._rasentra_check_before_paid()
        Intent = self.env["rasentra.payment.intent"].sudo()
        for payment in self.payment_ids.filtered(lambda p: p.payment_method_id.use_payment_terminal == "rasentra_qris"):
            intent = Intent.search([("uuid", "=", payment.transaction_id or ""), ("order_uuid", "=", self.uuid)], limit=1)
            if not intent or intent.status != "succeeded" or money(intent.amount) != money(payment.amount):
                raise RasentraError.conflict(
                    "payment_not_confirmed", _("Pembayaran %s belum dikonfirmasi provider.", payment.payment_method_id.name)
                )
