from odoo import _, models

from odoo.addons.rasentra_core.tools import RasentraError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _rasentra_intent(self, intent_uuid):
        intent = self.env["rasentra.payment.intent"].sudo().search(
            [("uuid", "=", intent_uuid), ("session_id", "=", self.id)], limit=1
        )
        if not intent:
            raise RasentraError("payment_unknown", _("Pembayaran tidak ditemukan."), 404)
        return intent

    def rasentra_payment_start(self, order_uuid, payment_method_id, amount):
        self.ensure_one()
        method = self.env["pos.payment.method"].sudo().browse(int(payment_method_id))
        return self.env["rasentra.payment.intent"].start(self, order_uuid, method, amount)._rasentra_wire()

    def rasentra_payment_status(self, intent_uuid):
        self.ensure_one()
        intent = self._rasentra_intent(intent_uuid)
        intent.query_provider()
        return intent._rasentra_wire()

    def rasentra_payment_timeout(self, intent_uuid):
        self.ensure_one()
        return self._rasentra_intent(intent_uuid).mark_uncertain()._rasentra_wire()

    def rasentra_payment_cancel(self, intent_uuid):
        self.ensure_one()
        return self._rasentra_intent(intent_uuid).cancel()._rasentra_wire()
