from odoo.tests import new_test_user, tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon
from odoo.addons.rasentra_core.tests.common import RasentraDataMixin


@tagged("post_install", "-at_install", "rasentra")
class TestPosMeatshopTour(RasentraDataMixin, TestPointOfSaleHttpCommon):
    @classmethod
    def get_default_groups(cls):
        return super().get_default_groups() | cls.env.ref("rasentra_core.group_rasentra_admin") | cls.env.ref(
            "hr.group_hr_user"
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sirloin.write({"default_code": "SIRLOIN-AUS", "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
        cls._publish_price("SLO-2026-10", 200000, outlet=cls.outlet)
        # TestPointOfSaleHttpCommon mengarsipkan semua produk yang sudah ada.
        cls.env.ref("rasentra_pos_meatshop.product_promo_discount").active = True
        cls.main_pos_config.write({"rasentra_outlet_id": cls.outlet.id, "rasentra_channel": "retail"})
        for code, weight in (("PK-T00184", 1.5), ("PK-T00191", 1.75)):
            cls.env["stock.lot"].create({
                "name": code, "product_id": cls.sirloin.id, "is_rasentra_pack": True, "net_weight": weight,
                "rasentra_outlet_id": cls.outlet.id, "rasentra_location_type": "outlet", "pack_status": "received",
            })
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

    def test_pack_scan_promo_and_pay(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.start_pos_tour("RasentraPackScanTour")
        order = self.env["pos.order"].search([("config_id", "=", self.main_pos_config.id)], limit=1)
        self.assertEqual(order.state, "paid")
        self.assertEqual(order.amount_total, 585000)
        self.assertFalse(order.rasentra_review)
        self.assertTrue(order.rasentra_doc_no.startswith("SLO-MS-"))
        packs = self.env["stock.lot"].search([("name", "in", ["PK-T00184", "PK-T00191"])])
        self.assertEqual(set(packs.mapped("pack_status")), {"sold"})
        self.assertEqual(order.lines.rasentra_allocation_ids.promotion_version_id, self.promo)
