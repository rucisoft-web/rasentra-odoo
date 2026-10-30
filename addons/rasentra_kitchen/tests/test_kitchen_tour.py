from odoo.tests import HttpCase, tagged

from odoo.addons.rasentra_core.tests.common import RasentraDataMixin


@tagged("post_install", "-at_install", "rasentra")
class TestKitchenTour(RasentraDataMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.outlet_code", cls.outlet.code)
        Product = cls.env["product.product"]
        steak = Product.create({"name": "Sirloin Steak", "default_code": "MN-STEAK", "type": "consu",
                                "rasentra_type": "menu", "kitchen_station": "grill"})
        tea = Product.create({"name": "Es teh", "default_code": "MN-TEA", "type": "consu",
                              "rasentra_type": "menu", "kitchen_station": "bar"})
        tomato = Product.create({"name": "Tomat", "default_code": "BH-TOMATO", "type": "consu", "is_storable": True})
        sauce = Product.create({"name": "Saus BBQ", "default_code": "SR-BBQ", "type": "consu", "is_storable": True})
        chef = cls.env["res.users"].create({"name": "Chef", "login": "chef-tour@solo.test",
                                            "groups_id": [(4, cls.env.ref("rasentra_core.group_rasentra_kitchen").id)]})
        recipe = cls.env["rasentra.recipe"].create({"product_id": sauce.id})
        cls.env["rasentra.recipe.version"].create({
            "recipe_id": recipe.id, "kind": "stocked_prep", "yield_quantity": 1,
            "line_ids": [(0, 0, {"component_product_id": tomato.id, "quantity": 1})]}).approve(chef)
        ticket = cls.env["rasentra.kitchen.ticket"]
        for station, product in (("grill", steak), ("bar", tea)):
            t = ticket.create({"outlet_id": cls.outlet.id, "order_uuid": "TOUR-1", "station": station,
                               "bump_code": f"9000000{len(station)}", "label": "Meja 5", "channel": "restaurant"})
            cls.env["rasentra.kitchen.item"].create({"ticket_id": t.id, "line_uuid": f"L-{station}",
                                                     "product_id": product.id, "quantity": 1,
                                                     "instructions": {"product": product.name}})

    def test_kitchen_board(self):
        action = self.env.ref("rasentra_kitchen.action_kitchen_board")
        self.start_tour(f"/odoo/action-{action.id}", "RasentraKitchenBoardTour", login="admin")
