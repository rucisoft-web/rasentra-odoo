from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.rasentra_core.tools import RasentraError
from odoo.addons.rasentra_pos_meatshop.tests.test_pos_meatshop import PosMeatshopCase


class CookingCase(PosMeatshopCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env.ref("rasentra_cooking_fee.product_cooking_service")
        cls.service.write({"available_in_pos": True, "taxes_id": [(5, 0, 0)]})
        cls.potato = cls.env["product.product"].create({
            "name": "Kentang goreng", "default_code": "MN-POTATO", "type": "consu", "list_price": 25000,
            "available_in_pos": True, "taxes_id": [(5, 0, 0)], "rasentra_type": "menu", "kitchen_station": "hot",
        })
        cls.rule = cls.env["rasentra.cooking.fee.rule"].create({
            "code": "COOK-STD", "name": "Masak standar", "basis": "per_kg", "rate": 40000,
            "effective_from": "2026-01-01 00:00:00",
        })
        cls.rule.action_publish()
        cls.Job = cls.env["rasentra.cooking.job"]

    def cook(self, order_uuid, pack_code, **instructions):
        instructions.setdefault("method", "grill")
        return self.pos_session.rasentra_cooking_request(order_uuid, pack_code, instructions, self.cashier.id)

    def order_with_jobs(self, order_uuid, lines, jobs):
        data = self._order_data(order_uuid, lines + [(self.service, 1, float(j["fee"]), False) for j in jobs])
        for command, job in zip(data["lines"][len(lines):], jobs):
            command[2]["rasentra_cooking_job_uuid"] = job["job_uuid"]
        return data


@tagged("post_install", "-at_install", "rasentra")
class TestCookingFee(CookingCase):
    def test_fee_bases_and_minimum(self):
        rule = self.env["rasentra.cooking.fee.rule"]
        cases = [
            ({"basis": "per_kg", "rate": 40000}, "1.5", 1, "60000.00"),
            ({"basis": "per_pack", "rate": 50000}, "1.5", 1, "50000.00"),
            ({"basis": "per_portion", "rate": 15000}, "1.5", 3, "45000.00"),
            ({"basis": "tiered", "rate": 35000, "tiers": [{"up_to": "1.000", "rate": "45000"},
                                                         {"up_to": "2.000", "rate": "40000"}]}, "1.5", 1, "60000.00"),
            ({"basis": "tiered", "rate": 35000, "tiers": [{"up_to": "1.000", "rate": "45000"}]}, "2.5", 1, "87500.00"),
            ({"basis": "per_kg", "rate": 40000, "minimum_fee": 30000}, "0.4", 1, "30000.00"),
            ({"basis": "per_kg", "rate": 33333}, "0.333", 1, "11100.00"),
        ]
        for i, (vals, weight, portions, expected) in enumerate(cases):
            r = rule.create(dict(vals, code=f"T{i}", name="t"))
            self.assertEqual(str(r.fee(weight, portions)), expected, vals)

    def test_u29_cart_example_410000(self):
        """U29: 1,500 kg x Rp200.000 = Rp300.000; fee 1,500 kg x Rp40.000 = Rp60.000;
        kentang 2 x Rp25.000 = Rp50.000; subtotal Rp410.000."""
        self._pack("PK-C0001", 1.5)
        pack_line = self.scan("PK-C0001", "ORDER-C1")
        job = self.cook("ORDER-C1", "PK-C0001", doneness="medium_rare")
        self.assertEqual((job["fee"], job["label"]), ("60000.00", "Jasa masak (cooking fee) 1.500 kg"))
        order = self.sync(self.order_with_jobs("ORDER-C1", [pack_line, (self.potato, 2, 25000.0, False)], [job]))
        self.assertEqual(order.amount_total, 410000)
        record = self.Job.search([("uuid", "=", job["job_uuid"])])
        self.assertEqual((record.pos_order_id, record.rule_version, record.doneness), (order, 1, "medium_rare"))
        payload = self.env["rasentra.sync.outbox"].search([("entity_uuid", "=", "ORDER-C1")]).payload
        service = [l for l in payload["lines"] if l.get("cooking_job_id")]
        self.assertEqual(service[0]["line_type"], "cooking_service")

    def test_u25_meat_leaves_stock_once(self):
        """U25: daging dijual sekali sebagai baris retail; jasa tidak memotong pack lagi."""
        self._pack("PK-C0002", 1.0)
        pack_line = self.scan("PK-C0002", "ORDER-C2")
        job = self.cook("ORDER-C2", "PK-C0002")
        with self.assertRaises(RasentraError) as err:
            self.cook("ORDER-C2", "PK-C0002")
        self.assertEqual(err.exception.code, "pack_already_has_job")
        with self.assertRaises(RasentraError) as err:
            self.cook("ORDER-OTHER", "PK-C0002")
        self.assertEqual(err.exception.code, "not_pack_line")
        self.sync(self.order_with_jobs("ORDER-C2", [pack_line], [job]))
        pack = self.Lot.search([("name", "=", "PK-C0002")])
        self.assertEqual(pack.pack_status, "sold")
        self.assertEqual(self.env["rasentra.pack.event"].search_count([("lot_id", "=", pack.id), ("event", "=", "sold")]), 1)
        self.assertFalse(self.env["rasentra.stock.adjustment"].search([]))

    def test_u26_restaurant_bills_service_only_from_receipt(self):
        """U26: daging dibayar di retail; restoran menagih jasa saja berdasarkan struk + Pack ID."""
        self._pack("PK-C0003", 1.5)
        retail = self.sync(self._order_data("ORDER-RET", [self.scan("PK-C0003", "ORDER-RET")]))
        result = self.pos_session.rasentra_cooking_from_receipt(
            "ORDER-RESTO", retail.rasentra_doc_no, "PK-C0003", {"method": "grill"}, self.cashier.id)
        self.assertEqual(result["fee"], "60000.00")
        self.assertTrue(result["from_receipt"])
        resto = self.sync(self.order_with_jobs("ORDER-RESTO", [(self.potato, 2, 25000.0, False)], [result]))
        self.assertEqual(resto.amount_total, 110000, "jasa Rp60.000 + kentang Rp50.000, tanpa daging")
        self.assertFalse(resto.lines.filtered(lambda l: l.product_id == self.sirloin))

    def test_u27_meat_promo_does_not_discount_service_line(self):
        """U27: baris jasa adalah baris anak pack; diskon daging tidak ikut mendiskon jasa."""
        group = "rasentra_core.group_rasentra_merch,base.group_user"
        maker, checker = new_test_user(self.env, "m1", groups=group), new_test_user(self.env, "c1", groups=group)
        promotion = self.env["rasentra.promotion"].create({"code": "DISC10", "name": "Diskon 10%"})
        version = self.env["rasentra.promotion.version"].with_user(maker).create({
            "promotion_id": promotion.id, "type": "percent", "starts_at": "2026-01-01 00:00:00",
            "rules": {"percent": 10, "product_ids": ["SIRLOIN-AUS", "SVC-COOK"]},
        })
        version.simulate(self.outlet, "retail", [(self.sirloin, "1.5")])
        version.with_user(checker).publish({"outlets": ["SLO-MS"]})
        self._pack("PK-C0004", 1.5)
        pack_line = self.scan("PK-C0004", "ORDER-C4")
        job = self.cook("ORDER-C4", "PK-C0004")
        data = self.order_with_jobs("ORDER-C4", [pack_line, (self.promo_product, 1, -30000.0, version.uuid)], [job])
        order = self.sync(data)
        self.assertEqual(order.amount_total, 330000)
        self.assertFalse(order.rasentra_review, "server juga tidak mendiskon jasa")
        service = order.lines.filtered("rasentra_cooking_job_uuid")
        self.assertEqual((service.rasentra_discount_amount, service.rasentra_net_amount), (0, 60000))

    @mute_logger("odoo.addons.point_of_sale.models.pos_order")
    def test_fee_must_match_rule(self):
        self._pack("PK-C0005", 1.0)
        pack_line = self.scan("PK-C0005", "ORDER-C5")
        job = self.cook("ORDER-C5", "PK-C0005")
        with self.assertRaises(RasentraError) as err:
            self.sync(self.order_with_jobs("ORDER-C5", [pack_line], [dict(job, fee="10000")]))
        self.assertEqual(err.exception.code, "cooking_fee_mismatch")

    def test_u28_cancel_before_and_after_cook(self):
        """U28: batal sebelum masak = jasa batal, pack tetap; sesudah masak = PIN, pack jadi waste."""
        self._pack("PK-C0006", 1.2)
        self.scan("PK-C0006", "ORDER-C6")
        job = self.cook("ORDER-C6", "PK-C0006")
        result = self.pos_session.rasentra_cooking_cancel(job["job_uuid"], "Tamu batal", self.cashier.id)
        self.assertEqual((result["status"], result["remove_pack"]), ("cancelled_before_cook", False))
        self.assertEqual(self.Lot.search([("name", "=", "PK-C0006")]).pack_status, "reserved")

        job = self.cook("ORDER-C6", "PK-C0006")
        record = self.Job.search([("uuid", "=", job["job_uuid"])])
        record.hand_over(self.head)
        record.mark_cooking()
        result = self.pos_session.rasentra_cooking_cancel(job["job_uuid"], "Tamu pergi", self.cashier.id)
        self.assertEqual(result["kind"], "approval_required")
        result = self.pos_session.rasentra_cooking_cancel(job["job_uuid"], "Tamu pergi", self.cashier.id,
                                                          {"approver_id": self.head.id, "pin": "4321"})
        self.assertEqual((result["status"], result["remove_pack"]), ("cancelled_after_cook", True))
        pack = self.Lot.search([("name", "=", "PK-C0006")])
        self.assertEqual(pack.pack_status, "damaged")
        waste = self.env["rasentra.stock.adjustment"].search([("source_ref", "=", job["job_uuid"])])
        self.assertEqual((waste.kind, waste.approver_id), ("waste", self.head))
        with self.assertRaises(RasentraError):
            self.scan("PK-C0006", "ORDER-C7")

    def test_u30_entitlement_cannot_be_reused(self):
        """U30: hak layanan struk + Pack ID dipakai sekali; pemakaian ulang ditolak dan diaudit."""
        self._pack("PK-C0008", 1.0)
        retail = self.sync(self._order_data("ORDER-RET8", [self.scan("PK-C0008", "ORDER-RET8")]))
        first = self.pos_session.rasentra_cooking_from_receipt("ORDER-R1", retail.rasentra_doc_no, "PK-C0008",
                                                               {"method": "grill"}, self.cashier.id)
        self.assertEqual(first["kind"], "job")
        again = self.pos_session.rasentra_cooking_from_receipt("ORDER-R2", retail.rasentra_doc_no, "PK-C0008",
                                                               {"method": "grill"}, self.cashier.id)
        self.assertEqual((again["kind"], again["code"]), ("blocked", "entitlement_used"))
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "cooking.entitlement_reuse_blocked")]))
        # Batal sebelum masak membuka hak layanan lagi.
        self.pos_session.rasentra_cooking_cancel(first["job_uuid"], "Salah meja", self.cashier.id)
        third = self.pos_session.rasentra_cooking_from_receipt("ORDER-R3", retail.rasentra_doc_no, "PK-C0008",
                                                               {"method": "grill"}, self.cashier.id)
        self.assertEqual(third["kind"], "job")
        with self.assertRaises(RasentraError) as err:
            self.pos_session.rasentra_cooking_from_receipt("ORDER-R4", "SLO-MS-000000-99999", "PK-C0008", {}, self.cashier.id)
        self.assertEqual(err.exception.code, "receipt_not_found")

    def test_rule_supersede_keeps_old_version_immutable(self):
        new = self.rule.new_version()
        new.rate = 45000
        new.action_publish()
        self.assertEqual(self.rule.state, "superseded")
        self.assertTrue(self.rule.effective_to)
        with self.assertRaises(RasentraError):
            self.rule.rate = 1
        self.assertEqual(self.env["rasentra.cooking.fee.rule"].rule_for(self.outlet, "grill"), new)
