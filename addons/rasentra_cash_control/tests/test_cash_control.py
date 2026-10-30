from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.addons.rasentra_core.tests.common import RasentraDataMixin
from odoo.addons.rasentra_core.tools import RasentraError


@tagged("post_install", "-at_install", "rasentra")
class TestCashControl(RasentraDataMixin, TestPoSCommon):
    EXTRAS = {"translatedType": "out", "formattedAmount": "Rp 20.000"}

    @classmethod
    def get_default_groups(cls):
        return super().get_default_groups() | cls.env.ref("rasentra_core.group_rasentra_admin") | cls.env.ref(
            "hr.group_hr_user"
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.config.write({"rasentra_outlet_id": cls.outlet.id, "rasentra_channel": "retail"})
        # Produk non-Pack ID (bumbu) cukup untuk menguji arus kas.
        cls.bumbu = cls.create_product("Bumbu steak", cls.categ_basic, 100000)

    def setUp(self):
        super().setUp()
        self.open_new_session(100000)
        self.session = self.pos_session

    def sell(self, quantity, method=None):
        payments = [(method, quantity * 100000)] if method else None
        data = self.create_ui_order_data([(self.bumbu, quantity)], payments=payments)
        self.env["pos.order"].sync_from_ui([data])

    def close_check(self, cash, approval=None, employee=None):
        counts = {"cash": cash, "edc_manual": self.session.rasentra_expected().get("edc_manual", "0")}
        return self.session.rasentra_close_check(counts, (employee or self.cashier).id, approval)

    def test_cash_movement_needs_reason_and_is_audited(self):
        with self.assertRaises(RasentraError) as err:
            self.session.try_cash_in_out("out", 20000, " ", self.EXTRAS)
        self.assertEqual(err.exception.code, "reason_required")
        self.session.try_cash_in_out("out", 20000, "Beli es batu", self.EXTRAS)
        event = self.env["rasentra.audit.event"].search([("action", "=", "cash.cash_out")])
        self.assertEqual(event.reason, "Beli es batu")

    def test_expected_per_method(self):
        """Saldo kas = modal awal + penjualan tunai + kas masuk - kas keluar; EDC terpisah."""
        self.sell(3)
        self.sell(1, self.bank_pm1)
        self.session.try_cash_in_out("out", 20000, "Beli es batu", self.EXTRAS)
        expected = self.session.rasentra_expected()
        self.assertEqual(expected["cash"], "380000.00")
        self.assertEqual(expected["edc_manual"], "100000.00")

    def test_small_difference_closes_without_approval(self):
        self.sell(3)
        result = self.close_check("395000")
        self.assertTrue(result["successful"])
        self.assertEqual(result["difference"], "-5000.00")
        self.assertFalse(self.session.rasentra_closing_approver_id)
        self.session.post_closing_cash_details(395000)
        self.session.update_closing_control_state_session("")
        self.assertTrue(self.session.close_session_from_ui()["successful"])
        self.assertEqual(self.session.state, "closed")
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "shift.closed")]))

    def test_large_difference_needs_head_pin(self):
        self.sell(3)
        self.assertEqual(self.close_check("350000")["kind"], "approval_required")
        self.assertEqual(
            self.close_check("350000", {"approver_id": self.head.id, "pin": "0000"})["kind"], "approval_required"
        )
        result = self.close_check("350000", {"approver_id": self.head.id, "pin": "4321"})
        self.assertTrue(result["successful"])
        self.assertEqual(self.session.rasentra_cash_difference, -50000)
        self.assertEqual(self.session.rasentra_closing_approver_id, self.head)

    def test_close_requires_counts(self):
        with self.assertRaises(RasentraError) as err:
            self.session.close_session_from_ui()
        self.assertEqual(err.exception.code, "shift_count_required")
        self.close_check("100000")
        with self.assertRaises(RasentraError) as err:
            self.session.post_closing_cash_details(90000)
        self.assertEqual(err.exception.code, "shift_count_changed")

    def test_report(self):
        self.sell(2)
        self.sell(1, self.bank_pm1)
        report = self.session.rasentra_report()
        self.assertEqual(report["orders"], 2)
        self.assertEqual(report["net"], "300000.00")
        self.assertEqual(report["payments"], {"cash": "200000.00", "edc_manual": "100000.00"})
        self.assertEqual(report["expected"]["cash"], "300000.00")

    def test_close_day_summary_versions(self):
        """Tutup hari mengirim ringkasan struk dan selisih kas; dijalankan ulang = versi berikutnya."""
        self.sell(3)
        self.sell(1, self.bank_pm1)
        self.close_check("395000")
        date = self.session.rasentra_business_date
        first = self.outlet.rasentra_close_day(date)
        payload = first.payload
        self.assertEqual((payload["orders"], payload["net_amount"]), (2, "400000.00"))
        self.assertEqual(payload["payments"], {"cash": "300000.00", "edc_manual": "100000.00"})
        self.assertEqual(payload["cash_difference"], "-5000.00")
        self.assertEqual(payload["open_shifts"], 0)
        self.assertEqual(len(payload["doc_nos"]), 2)
        second = self.outlet.rasentra_close_day(date)
        self.assertEqual((first.entity_uuid, second.entity_version), (second.entity_uuid, 2))
