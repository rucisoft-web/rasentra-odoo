from odoo import fields
from odoo.tests import tagged

from odoo.addons.rasentra_core.tools import RasentraError
from odoo.addons.rasentra_pos_meatshop.tests.test_pos_meatshop import PosMeatshopCase


@tagged("post_install", "-at_install", "rasentra")
class TestPaymentQris(PosMeatshopCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.qris = cls.bank_pm1
        cls.qris.write({"rasentra_method": "qris", "use_payment_terminal": "rasentra_qris"})
        cls.Intent = cls.env["rasentra.payment.intent"]

    def _paid_by_qris(self, uuid, line, intent_uuid):
        data = self._order_data(uuid, [line])
        data["payment_ids"] = [(0, 0, {"amount": data["amount_total"], "name": fields.Datetime.now(),
                                       "payment_method_id": self.qris.id, "transaction_id": intent_uuid})]
        return data

    def test_order_needs_provider_confirmation(self):
        self._pack("PK-000500", 1.5)
        line = self.scan("PK-000500", "ORDER-Q")
        intent = self.pos_session.rasentra_payment_start("ORDER-Q", self.qris.id, 300000)
        self.assertEqual(intent["status"], "pending")
        with self.assertRaises(RasentraError) as err:
            self.sync(self._paid_by_qris("ORDER-Q", line, intent["uuid"]))
        self.assertEqual(err.exception.code, "payment_not_confirmed")
        record = self.Intent.search([("uuid", "=", intent["uuid"])])
        record.apply_provider_result("succeeded", "300000")
        order = self.sync(self._paid_by_qris("ORDER-Q", line, intent["uuid"]))
        self.assertEqual(order.state, "paid")
        self.assertEqual(order._rasentra_payload()["payments"][0]["method"], "qris")

    def test_uncertain_is_not_failed_and_results_are_idempotent(self):
        intent = self.Intent.search([("uuid", "=", self.pos_session.rasentra_payment_start("O", self.qris.id, 50000)["uuid"])])
        self.pos_session.rasentra_payment_timeout(intent.uuid)
        self.assertEqual(intent.status, "uncertain")
        with self.assertRaises(RasentraError):
            intent.cancel()  # belum pasti: cek provider dulu
        intent.apply_provider_result("succeeded", "50000.00")
        intent.apply_provider_result("failed", "50000.00")
        self.assertEqual(intent.status, "succeeded", "status final tidak mundur")

    def test_amount_mismatch_rejected_and_audited(self):
        intent = self.Intent.search([("uuid", "=", self.pos_session.rasentra_payment_start("O", self.qris.id, 50000)["uuid"])])
        self.assertFalse(intent.apply_provider_result("succeeded", "5000"))
        self.assertEqual(intent.status, "pending")
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "payment.amount_mismatch")]))
