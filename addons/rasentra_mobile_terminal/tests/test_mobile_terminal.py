from odoo.tests import tagged

from odoo.addons.rasentra_core.tools import RasentraError
from odoo.addons.rasentra_cooking_fee.tests.test_cooking_fee import CookingCase


@tagged("post_install", "-at_install", "rasentra")
class TestMobileTerminal(CookingCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.steak = cls.env["product.product"].create({
            "name": "Sirloin Steak", "default_code": "MN-STEAK", "type": "consu", "rasentra_type": "menu",
            "kitchen_station": "grill", "list_price": 185000, "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
        floor = cls.env["restaurant.floor"].create({"name": "Lantai 1", "pos_config_ids": [(4, cls.config.id)]})
        Table = cls.env["restaurant.table"]
        cls.t1, cls.t2, cls.t3 = (Table.create({"floor_id": floor.id, "table_number": n, "seats": 4}) for n in (1, 2, 3))
        cls.Visit = cls.env["rasentra.visit"]

    def table_order(self, uuid, table, lines=None, state="draft", guests=2):
        lines = lines if lines is not None else [(self.steak, 1)]
        data = self._order_data(uuid, [(p, q, p.list_price, False) for p, q in lines])
        data.update(table_id=table.id, customer_count=guests)
        if state == "draft":
            data.update(state="draft", payment_ids=[], amount_paid=0)
        return self.sync(data)

    def open_visit(self, table):
        return self.Visit.search([("table_id", "=", table.id), ("status", "=", "open")])

    def test_visit_token_and_close_on_payment(self):
        order = self.table_order("T-1", self.t1)
        visit = order.rasentra_visit_id
        self.assertEqual((visit.table_id, visit.status, visit.guest_count), (self.t1, "open", 2))
        self.assertEqual(len(visit.visit_token), 64)
        self.table_order("T-1", self.t1, state="paid")
        self.assertEqual(visit.status, "closed")
        # Meja dibuka lagi: kunjungan baru dengan token baru, tidak menempel ke tamu sebelumnya.
        again = self.table_order("T-2", self.t1).rasentra_visit_id
        self.assertNotEqual(again, visit)
        self.assertNotEqual(again.visit_token, visit.visit_token)

    def test_second_order_same_table_joins_visit(self):
        first = self.table_order("T-3", self.t1)
        second = self.table_order("T-4", self.t1)
        self.assertEqual(first.rasentra_visit_id, second.rasentra_visit_id)
        self.table_order("T-3", self.t1, state="paid")
        self.assertEqual(first.rasentra_visit_id.status, "open", "masih ada order meja yang belum dibayar")

    def test_move_and_merge_tables(self):
        order = self.table_order("T-5", self.t1)
        visit = order.rasentra_visit_id
        order.table_id = self.t2
        self.assertEqual((visit.table_id, visit.status), (self.t2, "open"))
        self.assertFalse(self.open_visit(self.t1))
        other = self.table_order("T-6", self.t3)
        other.table_id = self.t2
        self.assertEqual(other.rasentra_visit_id, visit, "pindah ke meja terisi = gabung kunjungan")
        self.assertFalse(self.open_visit(self.t3))
        actions = self.env["rasentra.audit.event"].search([]).mapped("action")
        self.assertIn("table.moved", actions)
        self.assertIn("table.merged", actions)

    def test_bill_request_and_table_map(self):
        order = self.table_order("T-7", self.t1, lines=[(self.steak, 2)])
        table_map = self.pos_session.rasentra_table_map()
        info = table_map[self.t1.id]
        self.assertEqual((info["status"], info["unsent"], info["ready"]), ("occupied", 1, 0))
        self.pos_session.rasentra_kitchen_send("T-7")
        self.assertEqual(self.pos_session.rasentra_table_map()[self.t1.id]["cooking"], 1)
        self.assertTrue(self.pos_session.rasentra_request_bill("T-7", self.cashier.id))
        self.assertEqual(self.pos_session.rasentra_table_map()[self.t1.id]["status"], "billing")
        self.table_order("T-7", self.t1, lines=[(self.steak, 2)], state="paid")
        self.assertNotIn(self.t1.id, self.pos_session.rasentra_table_map())
        with self.assertRaises(RasentraError):
            order.rasentra_visit_id.request_bill()

    def test_empty_order_removed_closes_visit(self):
        order = self.table_order("T-8", self.t1)
        visit = order.rasentra_visit_id
        order.unlink()
        self.assertEqual(visit.status, "closed")
