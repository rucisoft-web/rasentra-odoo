from odoo.tests import tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import RasentraError


@tagged("post_install", "-at_install", "rasentra")
class TestStockCount(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.outlet_code", cls.outlet.code)
        cls.inv = cls.env["rasentra.inventory"]
        cls.ledger = cls.env["rasentra.stock.ledger"]
        cls.storekeeper = cls.env["hr.employee"].create(
            {"name": "Gudang Solo", "rasentra_role": "warehouse", "rasentra_outlet_id": cls.outlet.id, "pin": "2222"}
        )
        cls.counter2 = cls.env["hr.employee"].create(
            {"name": "Opname Solo", "rasentra_role": "counter", "rasentra_outlet_id": cls.outlet.id, "pin": "3333"}
        )
        cls.butter = cls.env["product.product"].create(
            {"name": "Butter 250g", "default_code": "BTR-250", "type": "consu", "is_storable": True,
             "rasentra_type": "ingredient"}
        )
        cls.stock = cls.ledger.location(cls.outlet, "stock")
        cls.stock.barcode = "LOC-SLO-STOK"

    def _shipped(self, code, weight):
        return self.env["stock.lot"].create(
            {"name": code, "product_id": self.sirloin.id, "is_rasentra_pack": True, "net_weight": weight,
             "rasentra_outlet_id": self.outlet.id, "rasentra_location_type": "transit", "pack_status": "shipped"}
        )

    def _put(self, product, quantity):
        self.ledger.move(product, quantity, self.ledger.virtual(self.company, "inventory"), self.stock, "saldo awal")

    def assertCode(self, code, func, *args, **kwargs):
        with self.assertRaises(RasentraError) as err:
            func(*args, **kwargs)
        self.assertEqual(err.exception.code, code)

    def test_receive_accept_reject_and_rescan(self):
        good = self._shipped("PK-R001", 1.25)
        bad = self._shipped("PK-R002", 0.8)
        self.assertEqual(self.inv.expected(self.outlet), good | bad)
        self.inv.receive(self.outlet, "PK-R001", self.storekeeper)
        self.assertEqual(good.pack_status, "received")
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, self.stock)), 1.25)
        self.assertCode("pack_already_received", self.inv.receive, self.outlet, "PK-R001", self.storekeeper)
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, self.stock)), 1.25, msg="scan ulang tidak menambah stok")
        self.assertCode("reason_required", self.inv.receive, self.outlet, "PK-R002", self.storekeeper, "reject")
        self.inv.receive(self.outlet, "PK-R002", self.storekeeper, "reject", "Vakum bocor")
        self.assertEqual(bad.pack_status, "damaged")
        quarantine = self.ledger.location(self.outlet, "quarantine")
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, quarantine)), 0.8)
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, self.stock)), 1.25, msg="tolak tidak menambah stok jual")
        self.assertEqual(self.inv.quarantine(self.outlet)["packs"][0]["reason"], "Vakum bocor")

    def test_waste_and_release_need_head(self):
        self._shipped("PK-W001", 1.0)
        self.inv.receive(self.outlet, "PK-W001", self.storekeeper, "reject", "Warna berubah")
        # Petugas gudang tanpa PIN ditolak; dengan PIN kepala outlet diterima.
        self.assertCode("approval_required", self.inv.release, self.outlet, self.storekeeper, "PK-W001", None, "Cek ulang OK")
        doc = self.inv.release(self.outlet, self.storekeeper, "PK-W001", None, "Cek ulang OK",
                               {"approver_id": self.head.id, "pin": "4321"})
        self.assertTrue(doc.doc_no.startswith("SLO-MS-RL"))
        self.assertEqual(doc.approver_id, self.head)
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, self.stock)), 1.0)
        # Kepala outlet membuang langsung tanpa PIN.
        doc = self.inv.waste(self.outlet, self.head, "PK-W001", None, "Kedaluwarsa")
        self.assertEqual(self.env["stock.lot"].search([("name", "=", "PK-W001")]).pack_status, "wasted")
        self.assertAlmostEqual(float(self.ledger.balance(self.sirloin, self.stock)), 0.0)
        event = self.env["rasentra.sync.outbox"].search([("entity_uuid", "=", doc.uuid)])
        self.assertEqual(event.event_type, "stock.adjusted")
        self.assertEqual(event.payload["lines"][0]["pack_id"], "PK-W001")
        self.assertEqual(event.payload["kind"], "waste")

    def test_waste_sku_limited_by_balance(self):
        self._put(self.butter, 5)
        self.assertCode("quantity_exceeds", self.inv.waste, self.outlet, self.head, "BTR-250", 6, "Rusak")
        self.inv.waste(self.outlet, self.head, "BTR-250", 2, "Rusak")
        self.assertAlmostEqual(float(self.ledger.balance(self.butter, self.stock)), 3.0)
        self.sirloin.default_code = "SRL-AUS"
        self.assertCode("pack_required", self.inv.waste, self.outlet, self.head, "SRL-AUS", 1, "x")

    def test_blind_count_recount_by_other_counter(self):
        self._put(self.butter, 10)
        session = self.env["rasentra.count.session"].open(self.storekeeper, self.outlet)
        self.assertCode("forbidden_role", self.env["rasentra.count.session"].open, self.cashier, self.outlet)
        session.record_scan(self.storekeeper, "BTR-250", 8, "LOC-SLO-STOK")
        self.assertNotIn("system", str(session.progress(self.storekeeper)), "blind count tidak membuka saldo sistem")
        self.assertCode("forbidden_role", session.review, self.storekeeper)
        result = session.review(self.head)
        self.assertEqual(session.state, "recount")
        self.assertEqual(result["lines"][0]["variance"], "-2.000000")
        self.assertCode("recount_same_counter", session.record_scan, self.storekeeper, "BTR-250", 9, "LOC-SLO-STOK")
        session.record_scan(self.counter2, "BTR-250", 9, "LOC-SLO-STOK")
        self.assertCode("count_not_reviewed", session.approve, self.head)
        session.review(self.head)
        self.assertEqual(session.state, "review")
        session.approve(self.head)
        self.assertEqual(session.state, "approved")
        self.assertAlmostEqual(float(self.ledger.balance(self.butter, self.stock)), 9.0)
        self.assertEqual(session.adjustment_id.kind, "count")
        self.assertEqual(session.adjustment_id.line_ids.from_state, "available")

    def test_pack_counted_once_per_round(self):
        self._shipped("PK-C001", 1.1)
        self.inv.receive(self.outlet, "PK-C001", self.storekeeper)
        session = self.env["rasentra.count.session"].open(self.storekeeper, self.outlet)
        session.record_scan(self.storekeeper, "PK-C001", None, "LOC-SLO-STOK")
        self.assertCode("pack_already_counted", session.record_scan, self.storekeeper, "PK-C001", None, "LOC-SLO-STOK")
        self.assertCode("location_unknown", session.record_scan, self.storekeeper, "BTR-250", 1, "RAK-X")
        session.review(self.head)
        self.assertEqual(session.state, "review", "tanpa selisih langsung review")

    def test_wizard_shows_error_without_losing_screen(self):
        wizard = self.env["rasentra.inventory.wizard"].create(
            {"mode": "receive", "outlet_id": self.outlet.id, "employee_id": self.storekeeper.id, "code": "PK-NOPE"}
        )
        wizard.action_process()
        self.assertEqual(wizard.message_level, "error")
        self._shipped("PK-Z001", 0.5)
        wizard.code = "PK-Z001"
        wizard.action_process()
        self.assertEqual(wizard.message_level, "ok")
