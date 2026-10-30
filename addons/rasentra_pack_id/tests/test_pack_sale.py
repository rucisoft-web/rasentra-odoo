from datetime import timedelta
from decimal import Decimal

import psycopg2

from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import RasentraError, money


@tagged("post_install", "-at_install", "rasentra")
class TestPackSale(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._publish_price("SLO-2026-10", 200000, outlet=cls.outlet)
        cls.lot = cls.env["stock.lot"]

    def _pack(self, code, weight, **vals):
        return self.lot.create(
            dict(
                {
                    "name": code,
                    "product_id": self.sirloin.id,
                    "is_rasentra_pack": True,
                    "net_weight": weight,
                    "rasentra_outlet_id": self.outlet.id,
                    "rasentra_location_type": "outlet",
                    "pack_status": "received",
                },
                **vals,
            )
        )

    def reserve(self, code, order="ORDER-1", **kwargs):
        kwargs.setdefault("outlet", self.outlet)
        kwargs.setdefault("employee", self.cashier)
        return self.lot.pack_reserve(code, order, kwargs.pop("outlet"), kwargs.pop("employee"), "retail", **kwargs)

    def assertCode(self, code, func, *args, **kwargs):
        with self.assertRaises(RasentraError) as err:
            func(*args, **kwargs)
        self.assertEqual(err.exception.code, code)

    def test_u01_two_packs_total_650000(self):
        """U01: 1,500 kg + 1,750 kg x Rp200.000/kg = Rp650.000, kedua Pack ID terjual."""
        self._pack("PK-000184", 1.5)
        self._pack("PK-000191", 1.75)
        lines = [self.reserve("PK-000184"), self.reserve("PK-000191")]
        self.assertEqual([line["gross_amount"] for line in lines], ["300000.00", "350000.00"])
        self.assertEqual(sum(Decimal(line["quantity"]) for line in lines), Decimal("3.250000"))
        self.assertEqual(money(sum(Decimal(line["gross_amount"]) for line in lines)), Decimal("650000.00"))
        for code, line_uuid in (("PK-000184", "L1"), ("PK-000191", "L2")):
            self.lot.pack_mark_sold(code, "ORDER-1", line_uuid, self.cashier)
        packs = self.lot.search([("name", "in", ["PK-000184", "PK-000191"])])
        self.assertEqual(set(packs.mapped("pack_status")), {"sold"})
        self.assertEqual(packs[0].pack_event_ids.mapped("event"), ["sold", "reserved"])

    def test_u02_u03_second_scan_is_rejected(self):
        self._pack("PK-1", 1.0)
        self.reserve("PK-1")
        self.assertCode("pack_already_in_cart", self.reserve, "PK-1")
        self.assertCode("pack_reserved", self.reserve, "PK-1", order="ORDER-2")
        self.lot.pack_mark_sold("PK-1", "ORDER-1", "L1")
        self.assertCode("pack_already_sold", self.reserve, "PK-1", order="ORDER-3")

    def test_u04_wrong_outlet_unknown_and_not_received(self):
        self._pack("PK-OTHER", 1.0, rasentra_outlet_id=self.other_outlet.id)
        self._pack("PK-TRANSIT", 1.0, rasentra_location_type="transit", pack_status="shipped")
        self._pack("PK-DAMAGED", 1.0, pack_status="damaged")
        self.assertCode("pack_other_outlet", self.reserve, "PK-OTHER")
        self.assertCode("pack_other_outlet", self.reserve, "PK-TRANSIT")
        self.assertCode("pack_not_sellable", self.reserve, "PK-DAMAGED")
        self.assertCode("pack_unknown", self.reserve, "PK-TIDAK-ADA")

    def test_hold_and_expired_need_supervisor_pin(self):
        self._pack("PK-HOLD", 1.0, pack_status="hold")
        yesterday = fields.Date.context_today(self.lot) - timedelta(days=1)
        self._pack("PK-EXP", 1.0, pack_expiry_date=yesterday)
        self.assertCode("approval_required", self.reserve, "PK-HOLD")
        line = self.reserve("PK-HOLD", approval={"approver_id": self.head.id, "pin": "4321"})
        self.assertEqual(line["approved_by"], self.head.id)
        self.reserve("PK-EXP", approval={"approver_id": self.head.id, "pin": "4321"})
        overrides = self.env["rasentra.audit.event"].search([("action", "=", "pack.sell_override")])
        self.assertEqual(sorted(overrides.mapped("reason")), ["expired", "hold"])

    def test_release_returns_pack_to_stock(self):
        self._pack("PK-1", 1.0)
        self.reserve("PK-1")
        self.assertFalse(self.lot.pack_release("PK-1", "ORDER-LAIN"))
        self.assertTrue(self.lot.pack_release("PK-1", "ORDER-1", reason="batal"))
        self.assertEqual(self.lot.search([("name", "=", "PK-1")]).pack_status, "received")
        self.reserve("PK-1", order="ORDER-2")

    def test_database_rejects_second_sale_and_duplicate_code(self):
        first = self._pack("PK-1", 1.0)
        first.sold_line_uuid = "L1"
        second = self._pack("PK-2", 1.0)
        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError), self.env.cr.savepoint():
            second.sold_line_uuid = "L1"
            second.flush_recordset()
        other_product = self.sirloin.copy({"name": "Ribeye"})
        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError), self.env.cr.savepoint():
            self._pack("PK-1", 1.0, product_id=other_product.id).flush_recordset()
