from odoo import fields
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.addons.rasentra_core.tests.common import RasentraDataMixin
from odoo.addons.rasentra_core.tools import RasentraError


class PosMeatshopCase(RasentraDataMixin, TestPoSCommon):
    """Sesi POS terbuka di outlet Meatshop Solo dengan harga sirloin Rp200.000/kg."""

    @classmethod
    def get_default_groups(cls):
        # Pengguna uji akuntansi Odoo juga menyiapkan master Rasentra (wilayah, outlet, harga, karyawan).
        return super().get_default_groups() | cls.env.ref("rasentra_core.group_rasentra_admin") | cls.env.ref(
            "hr.group_hr_user"
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sirloin.write({"default_code": "SIRLOIN-AUS", "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
        cls._publish_price("SLO-2026-10", 200000, outlet=cls.outlet)
        cls.config = cls.basic_config
        cls.config.write({"rasentra_outlet_id": cls.outlet.id, "rasentra_channel": "retail"})
        cls.promo_product = cls.env.ref("rasentra_pos_meatshop.product_promo_discount")
        cls.Lot = cls.env["stock.lot"]

    def setUp(self):
        super().setUp()
        self.open_new_session()

    def _pack(self, code, weight, **vals):
        return self.Lot.create(dict({
            "name": code, "product_id": self.sirloin.id, "is_rasentra_pack": True, "net_weight": weight,
            "rasentra_outlet_id": self.outlet.id, "rasentra_location_type": "outlet", "pack_status": "received",
        }, **vals))

    def scan(self, code, order_uuid, approval=None):
        return self.pos_session.rasentra_scan(code, order_uuid, self.cashier.id, approval)

    def _order_data(self, order_uuid, lines):
        """`lines` = hasil scan (dict pack) atau (produk, qty, harga, promo_uuid)."""
        ui_lines = []
        for line in lines:
            if isinstance(line, dict):
                product_id, quantity, price = line["product_id"], float(line["quantity"]), float(line["unit_price"])
                lots, promo = [(0, 0, {"lot_name": line["pack_code"]})], False
            else:
                product, quantity, price, promo = line
                product_id, lots = product.id, []
            ui_lines.append((0, 0, {
                "uuid": self.create_random_uid(), "product_id": product_id, "qty": quantity, "price_unit": price,
                "price_subtotal": quantity * price, "price_subtotal_incl": quantity * price, "discount": 0,
                "tax_ids": [(6, 0, [])], "pack_lot_ids": lots, "rasentra_promo_uuid": promo,
            }))
        total = sum(line[2]["price_subtotal_incl"] for line in ui_lines)
        return {
            "uuid": order_uuid, "name": f"Order {order_uuid}", "session_id": self.pos_session.id,
            "sequence_number": 2, "user_id": self.env.uid, "employee_id": self.cashier.id,
            "pricelist_id": self.config.pricelist_id.id, "fiscal_position_id": False, "partner_id": False,
            "date_order": fields.Datetime.to_string(fields.Datetime.now()), "last_order_preparation_change": "{}",
            "amount_total": total, "amount_tax": 0, "amount_paid": total, "amount_return": 0, "to_invoice": False,
            "lines": ui_lines, "state": "paid",
            "payment_ids": [(0, 0, {"amount": total, "name": fields.Datetime.now(),
                                    "payment_method_id": self.cash_pm1.id})],
        }

    def sync(self, data):
        result = self.env["pos.order"].sync_from_ui([data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])


@tagged("post_install", "-at_install", "rasentra")
class TestPosMeatshop(PosMeatshopCase):
    def test_u01_two_packs_finalized_to_outbox(self):
        """U01: 1,500 kg + 1,750 kg x Rp200.000 = Rp650.000; Pack ID terjual, struk bernomor, event di outbox."""
        self._pack("PK-000184", 1.5)
        self._pack("PK-000191", 1.75)
        uuid = "ORDER-U01"
        lines = [self.scan("PK-000184", uuid), self.scan("PK-000191", uuid)]
        self.assertEqual([line["kind"] for line in lines], ["pack", "pack"])
        order = self.sync(self._order_data(uuid, lines))

        self.assertEqual(order.state, "paid")
        self.assertEqual(order.amount_total, 650000)
        self.assertEqual(sum(order.lines.mapped("qty")), 3.25)
        self.assertRegex(order.rasentra_doc_no, r"^SLO-MS-\d{6}-00001$")
        self.assertEqual(order.rasentra_net_amount, 650000)
        self.assertFalse(order.rasentra_review)
        packs = self.Lot.search([("name", "in", ["PK-000184", "PK-000191"])])
        self.assertEqual(set(packs.mapped("pack_status")), {"sold"})

        event = self.env["rasentra.sync.outbox"].search([("entity_uuid", "=", uuid)])
        self.assertEqual(event.event_type, "order.finalized")
        payload = event.payload
        self.assertEqual(payload["net_amount"], "650000.00")
        self.assertEqual([line["pack_code"] for line in payload["lines"]], ["PK-000184", "PK-000191"])
        self.assertEqual(payload["payments"][0]["amount"], "650000.00")

    def test_u02_pack_cannot_be_in_two_carts(self):
        """U02: Pack ID yang sudah di keranjang kasir lain ditolak; setelah terjual pun ditolak."""
        self._pack("PK-000200", 1.2)
        line = self.scan("PK-000200", "ORDER-A")
        with self.assertRaises(RasentraError) as err:
            self.scan("PK-000200", "ORDER-B")
        self.assertEqual(err.exception.code, "pack_reserved")
        self.sync(self._order_data("ORDER-A", [line]))
        with self.assertRaises(RasentraError) as err:
            self.scan("PK-000200", "ORDER-C")
        self.assertEqual(err.exception.code, "pack_already_sold")

    def test_release_frees_pack_for_other_cart(self):
        self._pack("PK-000201", 1.0)
        self.scan("PK-000201", "ORDER-A")
        self.pos_session.rasentra_release("PK-000201", "ORDER-A", self.cashier.id, "line_void")
        self.assertEqual(self.scan("PK-000201", "ORDER-B")["kind"], "pack")

    def test_non_pack_code_falls_back_to_odoo(self):
        self.assertFalse(self.scan("8991234567890", "ORDER-A"))

    def test_hold_pack_needs_head_approval(self):
        self._pack("PK-000202", 1.0, pack_status="hold")
        self.assertEqual(self.scan("PK-000202", "ORDER-A")["kind"], "approval_required")
        result = self.scan("PK-000202", "ORDER-A", {"approver_id": self.head.id, "pin": "4321"})
        self.assertEqual(result["kind"], "pack")

    @mute_logger("odoo.addons.point_of_sale.models.pos_order")
    def test_meat_pack_without_scan_is_rejected(self):
        with self.assertRaises(RasentraError) as err:
            self.sync(self._order_data("ORDER-X", [(self.sirloin, 1.0, 200000, False)]))
        self.assertEqual(err.exception.code, "weighed_needs_pack")

    def test_promo_line_matches_server_and_allocates(self):
        group = "rasentra_core.group_rasentra_merch,base.group_user"
        maker = new_test_user(self.env, "promo_maker", groups=group)
        checker = new_test_user(self.env, "promo_checker", groups=group)
        promotion = self.env["rasentra.promotion"].create({"code": "DISC10", "name": "Diskon 10%"})
        version = self.env["rasentra.promotion.version"].with_user(maker).create({
            "promotion_id": promotion.id, "type": "percent", "starts_at": "2026-01-01 00:00:00",
            "rules": {"percent": 10, "product_ids": ["SIRLOIN-AUS"]},
        })
        version.simulate(self.outlet, "retail", [(self.sirloin, "1.5")])
        version.with_user(checker).publish({"outlets": ["SLO-MS"]})

        self._pack("PK-000300", 1.5)
        line = self.scan("PK-000300", "ORDER-P")
        evaluated = self.pos_session.rasentra_evaluate(
            [{"uuid": "x", "product_id": self.sirloin.id, "qty": line["quantity"], "price_unit": line["unit_price"]}]
        )
        self.assertEqual(evaluated["promotions"], [{"uuid": version.uuid, "name": evaluated["promotions"][0]["name"],
                                                    "amount": "30000.00"}])
        order = self.sync(self._order_data("ORDER-P", [line, (self.promo_product, 1, -30000.0, version.uuid)]))
        self.assertEqual(order.amount_total, 270000)
        self.assertFalse(order.rasentra_review)
        self.assertEqual(order.rasentra_discount_amount, 30000)
        sale_line = order.lines.filtered(lambda l: not l.rasentra_promo_uuid)
        self.assertEqual(sale_line.rasentra_allocation_ids.promotion_version_id, version)
        self.assertEqual(sale_line.rasentra_net_amount, 270000)

    def test_wrong_promo_amount_flags_review(self):
        self._pack("PK-000301", 1.0)
        line = self.scan("PK-000301", "ORDER-R")
        order = self.sync(self._order_data("ORDER-R", [line, (self.promo_product, 1, -5000.0, "fake-uuid")]))
        self.assertTrue(order.rasentra_review)
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "order.review_needed")]))
