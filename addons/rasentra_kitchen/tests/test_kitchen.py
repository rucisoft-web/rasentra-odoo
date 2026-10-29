
from odoo.tests import tagged

from odoo.addons.rasentra_core.tools import RasentraError
from odoo.addons.rasentra_cooking_fee.tests.test_cooking_fee import CookingCase


@tagged("post_install", "-at_install", "rasentra")
class TestKitchen(CookingCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env["product.product"]

        def product(code, name, station=None, kind="menu", price=0):
            return Product.create({"name": name, "default_code": code, "type": "consu", "is_storable": kind != "menu",
                                   "rasentra_type": kind, "kitchen_station": station, "list_price": price,
                                   "available_in_pos": True, "taxes_id": [(5, 0, 0)]})

        cls.steak = product("MN-STEAK", "Sirloin Steak", "grill", price=185000)
        cls.tea = product("MN-TEA", "Es teh", "bar", price=15000)
        cls.beef = product("BH-BEEF", "Daging porsi", kind="ingredient")
        cls.butter = product("BH-BUTTER", "Butter", kind="ingredient")
        cls.sauce = product("SR-BBQ", "Saus BBQ", kind="ingredient")
        cls.tomato = product("BH-TOMATO", "Tomat", kind="ingredient")
        cls.chef = cls.env["res.users"].create({"name": "Chef 2", "login": "chef-kds@solo.test",
                                                "groups_id": [(4, cls.env.ref("rasentra_core.group_rasentra_kitchen").id)]})

        def approve(product_, lines, kind="menu", yield_qty=1.0):
            recipe = cls.env["rasentra.recipe"].create({"product_id": product_.id})
            version = cls.env["rasentra.recipe.version"].create({
                "recipe_id": recipe.id, "kind": kind, "yield_quantity": yield_qty,
                "line_ids": [(0, 0, {"component_product_id": p.id, "quantity": q, "modifier_key": m})
                             for p, q, m in lines]})
            return version.approve(cls.chef)

        cls.steak_recipe = approve(cls.steak, [(cls.beef, 0.2, False), (cls.butter, 0.01, False),
                                               (cls.butter, 0.015, "extra_butter")])
        cls.sauce_recipe = approve(cls.sauce, [(cls.tomato, 1.0, False), (cls.butter, 0.05, False)],
                                   kind="stocked_prep", yield_qty=1.0)
        cls.K = cls.env["rasentra.kitchen"]
        cls.Item = cls.env["rasentra.kitchen.item"]

    def draft(self, uuid, lines, **extra):
        data = self._order_data(uuid, [(p, q, p.list_price, False) for p, q in lines])
        data.update(state="draft", payment_ids=[], amount_paid=0, **extra)
        return self.sync(data)

    def set_qty(self, order, product, quantity):
        line = order.lines.filtered(lambda l: l.product_id == product)
        line.qty = quantity

    def items(self, order, product=None):
        items = self.Item.search([("ticket_id.order_uuid", "=", order.uuid)])
        return items.filtered(lambda i: i.product_id == product) if product else items

    def test_u07_only_delta_is_sent(self):
        """U07: Kirim ke Dapur hanya mengirim item baru atau tambahan kuantitas, per station."""
        order = self.draft("RESTO-1", [(self.steak, 2), (self.tea, 1)])
        result = self.pos_session.rasentra_kitchen_send("RESTO-1")
        self.assertEqual((result["tickets"], result["stations"]), (2, ["bar", "grill"]))
        self.assertEqual(self.pos_session.rasentra_kitchen_send("RESTO-1")["tickets"], 0, "kirim ulang tanpa perubahan")
        self.set_qty(order, self.steak, 3)
        self.pos_session.rasentra_kitchen_send("RESTO-1")
        self.assertEqual(self.items(order, self.steak).mapped("quantity"), [2.0, 1.0])
        # Kurangi kuantitas: item terakhir yang belum dimasak dibatalkan.
        self.set_qty(order, self.steak, 2)
        self.pos_session.rasentra_kitchen_send("RESTO-1")
        self.assertEqual(self.items(order, self.steak).mapped("status"), ["queued", "cancelled"])
        # Hapus baris yang sedang dimasak: minta batal ke station, tidak langsung batal.
        tea_item = self.items(order, self.tea)
        self.K.bump_item(tea_item.id)
        order.lines.filtered(lambda l: l.product_id == self.tea).unlink()
        self.assertEqual(tea_item.status, "cancel_requested")
        self.K.confirm_cancel(tea_item.id)
        self.assertEqual(tea_item.status, "cancelled")

    def test_u09_start_consumes_recipe_once_and_waste_after_cook(self):
        order = self.draft("RESTO-2", [(self.steak, 10)])
        line = order.lines
        value = self.env["product.attribute"].create({"name": "Tambahan", "create_variant": "no_variant",
                                                      "value_ids": [(0, 0, {"name": "Extra butter",
                                                                            "rasentra_modifier_key": "extra_butter"})]})
        ptal = self.env["product.template.attribute.line"].create(
            {"product_tmpl_id": self.steak.product_tmpl_id.id, "attribute_id": value.id,
             "value_ids": [(6, 0, value.value_ids.ids)]})
        line.attribute_value_ids = [(6, 0, ptal.product_template_value_ids.ids)]
        self.pos_session.rasentra_kitchen_send("RESTO-2")
        item = self.items(order)
        self.assertEqual(item.modifier_keys, ["extra_butter"])
        self.K.bump_item(item.id)
        self.K.bump_item(item.id)  # in_preparation -> ready, tanpa konsumsi ulang
        events = self.env["rasentra.consumption.event"].search([("source_ref", "=", str(item.id))])
        totals = {e.product_id.default_code: round(sum(events.filtered(lambda x: x.product_id == e.product_id).mapped("quantity")), 6) for e in events}
        self.assertEqual(totals, {"BH-BEEF": 2.0, "BH-BUTTER": 0.25})
        self.assertEqual(item.recipe_version_id, self.steak_recipe)
        self.assertEqual(item.status, "ready")
        # Batal setelah dimasak: bahan menjadi waste dan dokumen waste dibuat.
        line.unlink()
        self.assertEqual(item.status, "cancel_requested")
        self.K.confirm_cancel(item.id)
        self.assertEqual(set(events.mapped("reason")), {"waste"})
        waste = self.env["rasentra.stock.adjustment"].search([("source_ref", "=", str(item.id))])
        self.assertEqual(waste.kind, "waste")

    def test_u08_split_bill_moves_kitchen_items(self):
        """U08: split bill memindahkan item dapur ke order baru; tidak dianggap void dan tidak dikirim ulang."""
        order = self.draft("RESTO-3", [(self.steak, 2), (self.tea, 2)])
        self.pos_session.rasentra_kitchen_send("RESTO-3")
        tea_line = order.lines.filtered(lambda l: l.product_id == self.tea)
        steak_line = order.lines.filtered(lambda l: l.product_id == self.steak)
        tea_uuid = tea_line.uuid
        self.pos_session.rasentra_kitchen_split_begin("RESTO-3")
        new = self.draft("RESTO-3B", [(self.steak, 1), (self.tea, 2)])
        tea_line.unlink()
        steak_line.qty = 1
        moves = [{"from_line_uuid": steak_line.uuid, "qty": 1,
                  "to_line_uuid": new.lines.filtered(lambda l: l.product_id == self.steak).uuid},
                 {"from_line_uuid": tea_uuid, "qty": 2,
                  "to_line_uuid": new.lines.filtered(lambda l: l.product_id == self.tea).uuid}]
        self.pos_session.rasentra_kitchen_split_done("RESTO-3", "RESTO-3B", moves)
        self.assertNotIn("cancelled", self.Item.search([]).mapped("status"))
        self.assertEqual(self.pos_session.rasentra_kitchen_send("RESTO-3")["tickets"], 0)
        self.assertEqual(self.pos_session.rasentra_kitchen_send("RESTO-3B")["tickets"], 0)
        self.assertEqual(sorted(self.Item.search([]).mapped("quantity")), [1.0, 1.0, 2.0])

    def test_board_expeditor_bump_code_and_analytics(self):
        order = self.draft("RESTO-4", [(self.steak, 1), (self.tea, 1)])
        self.pos_session.rasentra_kitchen_send("RESTO-4")
        board = self.K.board(self.outlet.id, "grill")
        self.assertEqual(len(board["tickets"]), 1)
        self.assertEqual(self.items(order, self.steak).status, "acknowledged", "tampil di station = diterima")
        ticket = self.env["rasentra.kitchen.ticket"].search([("station", "=", "grill")])
        self.K.bump_by_code(ticket.bump_code, self.outlet.id)
        self.K.bump_ticket(ticket.id)
        with self.assertRaises(RasentraError) as err:
            self.K.bump_item(self.items(order, self.steak).id)
        self.assertEqual(err.exception.code, "needs_expeditor")
        self.K.recall(self.items(order, self.steak).id)
        self.K.bump_item(self.items(order, self.steak).id)
        expeditor = self.K.board(self.outlet.id)
        self.assertEqual(len(expeditor["tickets"]), 1, "expeditor mengelompokkan per pesanan")
        self.assertFalse(expeditor["tickets"][0]["complete"], "es teh belum siap")
        self.K.bump_item(self.items(order, self.steak).id, expeditor=True)
        self.assertEqual(self.items(order, self.steak).status, "served")
        stats = self.K.analytics(self.outlet.id)
        self.assertEqual(stats["by_station"][0]["station"], "grill")
        self.assertEqual(stats["overall"]["count"], 1)
        old = self.K.version(self.outlet.id)
        self.K.bump_item(self.items(order, self.tea).id)
        self.assertNotEqual(old, self.K.version(self.outlet.id))

    def test_pickup_queue_number(self):
        self.config.rasentra_channel = "takeaway"
        order = self.draft("RESTO-5", [(self.tea, 1)], customer_name="Budi", customer_phone="0812")
        self.pos_session.rasentra_kitchen_send("RESTO-5")
        self.assertEqual(order.rasentra_queue_no, 1)
        self.assertEqual(self.K.queue(self.outlet.id)["preparing"], [{"no": 1}])
        item = self.items(order)
        self.K.bump_item(item.id)
        self.K.bump_item(item.id)
        self.assertEqual(self.K.queue(self.outlet.id)["ready"][0]["no"], 1)

    def test_cooking_job_follows_kitchen(self):
        self._pack("PK-K0001", 1.5)
        pack = self.scan("PK-K0001", "RESTO-6")
        job = self.cook("RESTO-6", "PK-K0001", doneness="medium")
        data = self.order_with_jobs("RESTO-6", [pack], [job])
        data.update(state="draft", payment_ids=[], amount_paid=0)
        self.sync(data)
        self.pos_session.rasentra_kitchen_send("RESTO-6")
        item = self.Item.search([("cooking_job_uuid", "=", job["job_uuid"])])
        self.assertEqual(item.instructions["pack_id"], "PK-K0001")
        self.assertEqual(item.instructions["doneness"], "medium")
        record = self.env["rasentra.cooking.job"].search([("uuid", "=", job["job_uuid"])])
        self.K.bump_item(item.id)
        self.assertEqual(record.status, "cooking")
        self.K.bump_item(item.id)
        self.K.bump_item(item.id, expeditor=True)
        self.assertEqual(record.status, "served")

    def test_u10_sauce_production_with_loss_reason(self):
        """U10: produksi saus dari resep berstok; susut di atas 2% wajib alasan dari daftar."""
        Batch = self.env["rasentra.production.batch"]
        with self.assertRaises(RasentraError) as err:
            Batch.produce_from_recipe(self.outlet, self.head, self.sauce_recipe, 2, "1.9")
        self.assertEqual(err.exception.code, "loss_reason_required")
        with self.assertRaises(RasentraError) as err:
            Batch.produce_from_recipe(self.outlet, self.head, self.sauce_recipe, 2, "1.9", loss_reason="Lupa")
        self.assertEqual(err.exception.code, "loss_reason_invalid")
        batch = Batch.produce_from_recipe(self.outlet, self.head, self.sauce_recipe, 2, "1.9",
                                          {self.tomato.id: "2.1"}, loss_reason="Susut masak")
        self.assertAlmostEqual(batch.loss_quantity, 0.1)
        self.assertEqual([i["quantity"] for i in batch.inputs], ["2.100000", "0.100000"])
        doc = batch.adjustment_id
        self.assertEqual(doc.kind, "production")
        self.assertEqual([(l.product_id.default_code, l.from_state or None, l.to_state or None) for l in doc.line_ids],
                         [("BH-TOMATO", "available", None), ("BH-BUTTER", "available", None), ("SR-BBQ", None, "available")])
        ledger = self.env["rasentra.stock.ledger"]
        self.assertAlmostEqual(float(ledger.balance(self.sauce, ledger.location(self.outlet, "stock"))), 1.9)
        small = Batch.produce_from_recipe(self.outlet, self.head, self.sauce_recipe, 2, "1.97")
        self.assertFalse(small.loss_reason, "susut 1,5% tanpa alasan")

    def test_u12_cutting_yield_balance(self):
        """U12: neraca potong & porsi: input = output + susut; output > input ditolak."""
        Batch = self.env["rasentra.production.batch"]
        primal = self.env["product.product"].create({"name": "Striploin utuh", "default_code": "BH-PRIMAL",
                                                     "type": "consu", "is_storable": True, "rasentra_type": "ingredient"})
        with self.assertRaises(RasentraError) as err:
            Batch.produce(self.outlet, self.head, [(primal, "5")], [(self.beef, "5.1")])
        self.assertEqual(err.exception.code, "production_balance")
        batch = Batch.produce(self.outlet, self.head, [(primal, "5")],
                              [(self.beef, "4.6"), (self.tomato, "0.2", "trimming")], "Susut potong")
        self.assertAlmostEqual(batch.loss_quantity, 0.2)
        self.assertAlmostEqual(batch.loss_percent, 4.0)
        self.assertEqual(batch.outputs[1]["kind"], "trimming")
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "production.recorded")]))
