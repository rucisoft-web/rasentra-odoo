from decimal import Decimal

from odoo.tests import tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import RasentraError


@tagged("post_install", "-at_install", "rasentra")
class TestRecipe(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env["product.product"]

        def product(code, name, kind="ingredient"):
            return Product.create({"name": name, "default_code": code, "type": "consu", "is_storable": True,
                                   "rasentra_type": kind})

        cls.steak = product("MN-STEAK", "Sirloin Steak 200g", "menu")
        cls.beef = product("BH-BEEF", "Daging sirloin porsi")
        cls.butter = product("BH-BUTTER", "Butter")
        cls.onion = product("BH-ONION", "Bawang bombay")
        cls.sauce = product("SR-BLACKPEPPER", "Saus lada hitam")
        cls.pepper = product("BH-PEPPER", "Lada hitam")
        cls.chef2 = cls.env["res.users"].create({
            "name": "Chef Kepala", "login": "chef2@solo.test",
            "groups_id": [(4, cls.env.ref("rasentra_core.group_rasentra_kitchen").id)],
        })

    def _version(self, product, lines, kind="menu", yield_qty=1.0):
        recipe = self.env["rasentra.recipe"].search([("product_id", "=", product.id)]) or \
            self.env["rasentra.recipe"].create({"product_id": product.id})
        version = self.env["rasentra.recipe.version"].create({
            "recipe_id": recipe.id, "version": len(recipe.version_ids) + 1, "kind": kind, "yield_quantity": yield_qty,
            "line_ids": [(0, 0, {"component_product_id": p.id, "quantity": q, "modifier_key": m}) for p, q, m in lines],
        })
        return version

    def _approve(self, version):
        return version.approve(self.chef2)

    def test_maker_checker_and_immutable(self):
        version = self._version(self.steak, [(self.beef, 0.2, False)])
        with self.assertRaises(RasentraError) as err:
            version.approve(self.env.user)
        self.assertEqual(err.exception.code, "approval_self")
        self._approve(version)
        self.assertEqual(version.state, "approved")
        with self.assertRaises(RasentraError):
            version.yield_quantity = 2
        with self.assertRaises(RasentraError):
            version.line_ids.quantity = 0.3
        v2 = version.new_version()
        self.assertEqual((v2.version, v2.state, len(v2.line_ids)), (2, "draft", 1))
        v2.line_ids.quantity = 0.25
        self._approve(v2)
        self.assertEqual(version.state, "retired")
        self.assertEqual(self.env["rasentra.recipe"].active_version_for(self.steak), v2)
        self.assertTrue(self.env["rasentra.audit.event"].search([("action", "=", "recipe.approved")]))

    def test_u09_consumption_ten_portions_with_modifiers_and_virtual_sub(self):
        """U09: 10 porsi steak = 10x komposisi; subresep virtual diurai, berstok dipotong sebagai barang jadi."""
        virtual = self._version(self.sauce, [(self.pepper, 0.02, False), (self.butter, 0.01, False)],
                                kind="virtual_prep", yield_qty=0.1)
        self._approve(virtual)
        steak = self._version(self.steak, [(self.beef, 0.2, False), (self.sauce, 0.05, False),
                                           (self.butter, 0.015, "extra_butter"), (self.onion, 0.03, False)])
        self._approve(steak)
        needs = {n["product"].default_code: n["quantity"] for n in steak.explode(10, ["without:BH-ONION"])}
        self.assertEqual(needs, {"BH-BEEF": Decimal("2.000000"), "BH-PEPPER": Decimal("0.100000"),
                                 "BH-BUTTER": Decimal("0.050000")})
        needs = {n["product"].default_code: n["quantity"] for n in steak.explode(10, ["extra_butter"])}
        self.assertEqual(needs["BH-BUTTER"], Decimal("0.200000"), "butter saus 0,05 + extra 0,15")
        self.assertEqual(needs["BH-ONION"], Decimal("0.300000"))
        # Bila saus menjadi subresep berstok, saus dipotong sebagai barang jadi.
        stocked = virtual.new_version()
        stocked.kind = "stocked_prep"
        self._approve(stocked)
        needs = {n["product"].default_code: n["quantity"] for n in steak.explode(10)}
        self.assertEqual(needs["SR-BLACKPEPPER"], Decimal("0.500000"))
        self.assertNotIn("BH-PEPPER", needs)

    def test_cycle_rejected(self):
        a = self._version(self.sauce, [(self.pepper, 0.1, False)], kind="virtual_prep")
        self._approve(a)
        pepper_recipe = self._version(self.pepper, [(self.sauce, 0.5, False)], kind="virtual_prep")
        with self.assertRaises(RasentraError) as err:
            self._approve(pepper_recipe)
        self.assertEqual(err.exception.code, "recipe_cycle")
        self_ref = self._version(self.steak, [(self.steak, 1, False)])
        with self.assertRaises(RasentraError):
            self._approve(self_ref)

    def test_sync_apply_roundtrip(self):
        version = self._version(self.steak, [(self.beef, 0.2, False), (self.butter, 0.015, "extra_butter")])
        self._approve(version)
        payload = version._rasentra_sync_payload()
        payload = dict(payload, uuid="0192f000-0000-7000-8000-000000000001", version=9)
        applied = self.env["rasentra.recipe.version"]._rasentra_sync_apply(payload)
        self.assertEqual(applied.state, "approved")
        self.assertEqual(version.state, "retired", "versi lama dipensiunkan saat publikasi baru diterapkan")
        self.assertEqual(applied.line_ids.filtered("modifier_key").modifier_key, "extra_butter")
