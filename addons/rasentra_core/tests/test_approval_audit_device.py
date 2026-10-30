import psycopg2

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..tools import RasentraError, money, qty
from .common import RasentraCase


@tagged("post_install", "-at_install", "rasentra")
class TestApproval(RasentraCase):
    def verify(self, approval, requester=None, amount=0, outlet=None):
        return self.env["rasentra.approval"].verify(approval, requester or self.cashier, outlet or self.outlet, amount)

    def test_valid_pin_returns_approver(self):
        self.assertEqual(self.verify({"approver_id": self.head.id, "pin": "4321"}, amount=100000), self.head)

    def test_rejections_follow_laravel_codes(self):
        cases = [
            (None, {}, "approval_required"),
            ({"approver_id": self.head.id, "pin": "0000"}, {}, "approval_invalid"),
            ({"approver_id": self.cashier.id, "pin": "1111"}, {"requester": self.head}, "approval_invalid"),
            ({"approver_id": self.head.id, "pin": "4321"}, {"outlet": self.other_outlet}, "approval_invalid"),
            ({"approver_id": self.head.id, "pin": "4321"}, {"requester": self.head}, "approval_self"),
            ({"approver_id": self.head.id, "pin": "4321"}, {"amount": "500000.01"}, "approval_limit"),
        ]
        for approval, kwargs, code in cases:
            with self.subTest(code=code), self.assertRaises(RasentraError) as err:
                self.verify(approval, **kwargs)
            self.assertEqual(err.exception.code, code)
            self.assertEqual(err.exception.status, 403)


@tagged("post_install", "-at_install", "rasentra")
class TestAuditAndDevice(RasentraCase):
    def test_audit_is_append_only(self):
        event = self.env["rasentra.audit.event"].record("test.action", self.outlet, reason="uji", amount=10)
        self.assertEqual(event.outlet_id, self.outlet)
        with self.assertRaises(UserError):
            event.write({"reason": "ubah"})
        with self.assertRaises(UserError):
            event.unlink()
        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.Error), self.env.cr.savepoint():
            self.env.cr.execute("DELETE FROM rasentra_audit_event WHERE id = %s", [event.id])

    def test_device_token_is_hashed_and_revocable(self):
        device = self.env["rasentra.device"].create(
            {"code": "SLO-LOKAL-1", "name": "Server Solo", "outlet_id": self.outlet.id}
        )
        token = device.rotate_token()
        self.assertNotEqual(device.sudo().token_hash, token)
        self.assertEqual(self.env["rasentra.device"].authenticate(token), device)
        self.assertFalse(self.env["rasentra.device"].authenticate("salah"))
        device.action_revoke()
        self.assertFalse(self.env["rasentra.device"].with_context(active_test=False).authenticate(token))

    def test_decimal_rounding_on_money_not_weight(self):
        self.assertEqual(str(money(qty("1.5") * 200000)), "300000.00")
        self.assertEqual(str(money("0.005")), "0.01")
        self.assertEqual(str(qty(1.75)), "1.750000")


@tagged("post_install", "-at_install", "rasentra")
class TestPhpJson(RasentraCase):
    def test_checksum_matches_php_json_encode(self):
        from ..tools import checksum, php_json

        payload = {"doc_no": "SLO/2026/0001", "name": "Kopi ☕", "qty": "1.500000", "rate": 1.0, "lines": []}
        self.assertEqual(
            php_json(payload),
            '{"doc_no":"SLO\\/2026\\/0001","name":"Kopi ☕","qty":"1.500000","rate":1.0,"lines":[]}',
        )
        self.assertEqual(len(checksum(payload)), 64)
