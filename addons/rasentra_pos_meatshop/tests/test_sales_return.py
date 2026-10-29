from datetime import timedelta

from odoo import fields
from odoo.tests import new_test_user, tagged

from odoo.addons.rasentra_core.tools import RasentraError

from .test_pos_meatshop import PosMeatshopCase



@tagged("post_install", "-at_install", "rasentra")
class TestSalesReturn(PosMeatshopCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approval = {"approver_id": cls.head.id, "pin": "4321"}
        cls.bumbu = cls.create_product("Bumbu steak", cls.categ_basic, 100000)
        group = "rasentra_core.group_rasentra_merch,base.group_user"
        maker = new_test_user(cls.env, "promo_maker", groups=group)
        checker = new_test_user(cls.env, "promo_checker", groups=group)
        promotion = cls.env["rasentra.promotion"].create({"code": "DISC10", "name": "Diskon 10%"})
        cls.promo = cls.env["rasentra.promotion.version"].with_user(maker).create({
            "promotion_id": promotion.id, "type": "percent", "starts_at": "2026-01-01 00:00:00",
            "rules": {"percent": 10, "product_ids": ["SIRLOIN-AUS"]},
        })
        cls.promo.simulate(cls.outlet, "retail", [(cls.sirloin, "1.5")])
        cls.promo.with_user(checker).publish({"outlets": ["SLO-MS"]})

    def _sell_pack_with_promo(self):
        self._pack("PK-000400", 1.5)
        line = self.scan("PK-000400", "ORDER-S")
        return self.sync(self._order_data("ORDER-S", [line, (self.promo_product, 1, -30000.0, self.promo.uuid)]))

    def _sell_bumbu(self, quantity, uuid="ORDER-B"):
        return self.sync(self._order_data(uuid, [(self.bumbu, quantity, 100000.0, False)]))

    def prepare(self, refund_uuid, order, items, method="cash", approval="head", reason="Daging berbau"):
        return self.pos_session.rasentra_return_prepare(
            refund_uuid, order.id, items, reason, method, self.cashier.id,
            self.approval if approval == "head" else approval,
        )

    def _refund_data(self, refund_uuid, order, returns, correction=0.0, method=None):
        """`returns` = [(baris struk asal, qty)]; baris refund bernilai negatif seperti di POS."""
        ui_lines = [(0, 0, {
            "uuid": self.create_random_uid(), "product_id": line.product_id.id, "qty": -quantity,
            "price_unit": line.price_unit, "price_subtotal": -quantity * line.price_unit,
            "price_subtotal_incl": -quantity * line.price_unit, "discount": 0, "tax_ids": [(6, 0, [])],
            "refunded_orderline_id": line.id,
            "pack_lot_ids": [(0, 0, {"lot_name": line._rasentra_pack_code()})] if line._rasentra_pack_code() else [],
        }) for line, quantity in returns]
        if correction:
            ui_lines.append((0, 0, {
                "uuid": self.create_random_uid(), "product_id": self.promo_product.id, "qty": 1,
                "price_unit": correction, "price_subtotal": correction, "price_subtotal_incl": correction,
                "discount": 0, "tax_ids": [(6, 0, [])], "rasentra_promo_uuid": "return:x",
            }))
        total = sum(l[2]["price_subtotal_incl"] for l in ui_lines)
        data = self._order_data(refund_uuid, [])
        data.update({
            "lines": ui_lines, "amount_total": total, "amount_paid": total,
            "payment_ids": [(0, 0, {"amount": total, "name": fields.Datetime.now(),
                                    "payment_method_id": (method or self.cash_pm1).id})],
        })
        return data

    def test_pack_return_pro_rata_promo_to_quarantine(self):
        """Pack 1,5 kg Rp300.000 dengan promo 10%: retur mengembalikan Rp270.000, pack ke karantina."""
        order = self._sell_pack_with_promo()
        sale_line = order._rasentra_sale_lines()
        result = self.prepare("REFUND-1", order, [{"line_uuid": sale_line.uuid, "qty": "1.5"}])
        self.assertEqual((result["kind"], result["net_amount"], result["discount_amount"]),
                         ("prepared", "270000.00", "30000.00"))
        refund = self.sync(self._refund_data("REFUND-1", order, [(sale_line, 1.5)], correction=30000.0))
        self.assertEqual(refund.state, "paid")
        self.assertEqual(refund.amount_total, -270000)

        ret = self.env["rasentra.sales.return"].search([("refund_order_uuid", "=", "REFUND-1")])
        self.assertEqual(ret.state, "done")
        self.assertRegex(ret.doc_no, r"^SLO-MS-R\d{6}-0001$")
        self.assertEqual(ret.approver_id, self.head)
        self.assertEqual(ret.line_ids.disposition, "quarantine")
        self.assertEqual(self.Lot.search([("name", "=", "PK-000400")]).pack_status, "quarantine")
        event = self.env["rasentra.sync.outbox"].search([("event_type", "=", "order.returned")])
        self.assertEqual(event.payload["net_amount"], "270000.00")
        self.assertEqual(event.payload["original_doc_no"], order.rasentra_doc_no)
        self.assertEqual(event.payload["lines"][0]["pack_code"], "PK-000400")

    def test_partial_retail_returns_use_remaining_value(self):
        order = self._sell_bumbu(3)
        line = order.lines
        first = self.prepare("REFUND-A", order, [{"line_uuid": line.uuid, "qty": "1"}])
        self.assertEqual(first["net_amount"], "100000.00")
        self.sync(self._refund_data("REFUND-A", order, [(line, 1)]))
        with self.assertRaises(RasentraError) as err:
            self.prepare("REFUND-B", order, [{"line_uuid": line.uuid, "qty": "3"}])
        self.assertEqual(err.exception.code, "return_quantity")
        last = self.prepare("REFUND-B", order, [{"line_uuid": line.uuid, "qty": "2"}])
        self.assertEqual(last["net_amount"], "200000.00")
        ret = self.env["rasentra.sales.return"].search([("refund_order_uuid", "=", "REFUND-A")])
        self.assertEqual(ret.line_ids.disposition, "restock")

    def test_return_needs_head_pin_and_preparation(self):
        order = self._sell_bumbu(1)
        result = self.prepare("REFUND-C", order, [{"line_uuid": order.lines.uuid, "qty": "1"}], approval=None)
        self.assertEqual(result["kind"], "approval_required")
        with self.assertRaises(RasentraError) as err:
            self.sync(self._refund_data("REFUND-C", order, [(order.lines, 1)]))
        self.assertEqual(err.exception.code, "return_not_approved")

    def test_refund_must_match_prepared_return(self):
        order = self._sell_bumbu(2)
        self.prepare("REFUND-D", order, [{"line_uuid": order.lines.uuid, "qty": "1"}])
        with self.assertRaises(RasentraError) as err:
            self.sync(self._refund_data("REFUND-D", order, [(order.lines, 2)]))
        self.assertEqual(err.exception.code, "return_mismatch")

    def test_return_window_and_reason(self):
        order = self._sell_bumbu(1)
        items = [{"line_uuid": order.lines.uuid, "qty": "1"}]
        with self.assertRaises(RasentraError) as err:
            self.prepare("REFUND-E", order, items, reason=" ")
        self.assertEqual(err.exception.code, "reason_required")
        order.rasentra_business_date = order.rasentra_business_date - timedelta(days=8)
        with self.assertRaises(RasentraError) as err:
            self.prepare("REFUND-E", order, items)
        self.assertEqual(err.exception.code, "return_expired")

    def test_non_cash_refund_limited_to_paid_method(self):
        order = self._sell_bumbu(1)
        with self.assertRaises(RasentraError) as err:
            self.prepare("REFUND-F", order, [{"line_uuid": order.lines.uuid, "qty": "1"}], method="edc_manual")
        self.assertEqual(err.exception.code, "refund_method")
