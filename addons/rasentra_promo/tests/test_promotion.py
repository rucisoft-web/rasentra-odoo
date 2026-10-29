from odoo.tests import new_test_user, tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import RasentraError


@tagged("post_install", "-at_install", "rasentra")
class TestPromotion(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sirloin.default_code = "SIRLOIN-AUS"
        cls._publish_price("HRG-ALL", 200000)
        group = "rasentra_core.group_rasentra_merch,base.group_user"
        cls.maker = new_test_user(cls.env, "promo_maker", groups=group)
        cls.checker = new_test_user(cls.env, "promo_checker", groups=group)
        cls.lombok = cls.env["rasentra.region"].create({"code": "LOP", "name": "Lombok"})
        cls.lombok_outlet = cls.env["rasentra.outlet"].create(
            {"code": "LOP-MS", "name": "Meatshop Lombok", "region_id": cls.lombok.id, "tz": "Asia/Makassar"}
        )

    def _draft(self, code="DISC10", rules=None, **vals):
        Version = self.env["rasentra.promotion.version"].with_user(self.maker)
        promotion = self.env["rasentra.promotion"].create({"code": code, "name": code})
        return Version.create({"promotion_id": promotion.id, "type": "percent",
                               "rules": rules or {"percent": 10, "product_ids": ["SIRLOIN-AUS"]},
                               "starts_at": "2026-01-01 00:00:00", **vals})

    def _publish(self, version, target):
        version.simulate(self.outlet, "retail", [(self.sirloin, "3.25")])
        version.with_user(self.checker).publish(target)

    def test_u05_promo_only_applies_in_target_region(self):
        version = self._draft()
        result = version.simulate(self.lombok_outlet, "retail", [(self.sirloin, "3.25")])
        self.assertEqual(result["this_discount"], "65000.00")  # 3,25 kg x Rp200.000 x 10%
        version.with_user(self.checker).publish({"regions": ["LOP"]})
        Version = self.env["rasentra.promotion.version"]
        self.assertEqual(Version.active_for(self.lombok_outlet, "retail"), version)
        self.assertFalse(Version.active_for(self.outlet, "retail"), "Solo bukan target")

    def test_central_publishes_to_targets_only(self):
        if "rasentra.sync.publication" not in self.env:
            self.skipTest("rasentra_sync_central tidak terpasang")
        self.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "central")
        version = self._draft()
        self._publish(version, {"regions": ["LOP"]})
        publication = self.env["rasentra.sync.publication"].search(
            [("entity_type", "=", "promotion_version"), ("entity_key", "=", version.uuid)]
        )
        self.assertEqual(publication.outlet_ids, self.lombok_outlet)
        self.assertEqual(publication.payload["rules"]["product_ids"], ["SIRLOIN-AUS"])
        keys = [k for k, _p in self.env["rasentra.promotion.version"]._rasentra_sync_snapshot(self.lombok_outlet)]
        self.assertEqual(keys, [version.uuid])
        self.assertFalse(self.env["rasentra.promotion.version"]._rasentra_sync_snapshot(self.outlet))

    def test_maker_checker_and_simulation_required(self):
        version = self._draft()
        with self.assertRaisesRegex(RasentraError, "simulasi"):
            version.with_user(self.checker).publish({"all": True})
        version.simulate(self.outlet, "retail", [(self.sirloin, "1")])
        with self.assertRaises(RasentraError) as error:
            version.with_user(self.maker).publish({"all": True})
        self.assertEqual(error.exception.code, "approval_self")
        version.write({"priority": 50})
        self.assertEqual(version.state, "draft", "mengubah aturan membatalkan simulasi")

    def test_published_is_immutable_and_new_version_supersedes(self):
        v1 = self._draft()
        self._publish(v1, {"all": True})
        with self.assertRaises(RasentraError):
            v1.write({"rules": {"percent": 50}})
        v2 = v1.with_user(self.maker).new_version()
        v2.write({"rules": {"percent": 15, "product_ids": ["SIRLOIN-AUS"]}})
        self._publish(v2, {"outlets": ["SLO-MS"]})
        self.assertEqual(v1.state, "superseded")
        # Versi baru berlaku mulai besok pagi bila versi lama sudah berjalan (sama dengan Laravel).
        self.assertEqual(v2.starts_at.hour, 0)
        self.assertEqual(self.env["rasentra.promotion.version"].active_for(self.outlet, "retail", v2.starts_at), v2)

    def test_channel_and_window(self):
        version = self._draft(channels=["restaurant"], ends_at="2026-02-01 00:00:00")
        self._publish(version, {"all": True})
        Version = self.env["rasentra.promotion.version"]
        self.assertFalse(Version.active_for(self.outlet, "retail", "2026-01-15 00:00:00"))
        self.assertEqual(Version.active_for(self.outlet, "restaurant", "2026-01-15 00:00:00"), version)
        self.assertFalse(Version.active_for(self.outlet, "restaurant", "2026-03-01 00:00:00"))

    def test_lokal_applies_publication_for_its_outlet(self):
        self.env["ir.config_parameter"].sudo().set_param("rasentra.outlet_code", "SLO-MS")
        Version = self.env["rasentra.promotion.version"]
        payload = {
            "uuid": "0192f0aa-0000-7000-8000-0000000p0001", "promotion_code": "WEEKEND", "promotion_name": "Weekend",
            "version": 1, "status": "published", "type": "percent", "scope": "item",
            "rules": {"percent": 5}, "channels": None, "priority": 100, "stacking": "exclusive",
            "funded_by": "internal", "starts_at": "2026-01-01 00:00:00", "ends_at": None,
        }
        Version._rasentra_sync_apply(payload)
        Version._rasentra_sync_apply(payload)  # idempoten
        version = Version.search([("uuid", "=", payload["uuid"])])
        self.assertEqual(len(version.target_ids), 1)
        self.assertEqual(Version.active_for(self.outlet, "retail"), version)
        Version._rasentra_sync_apply(dict(payload, status="expired", ends_at="2026-01-02 00:00:00"))
        self.assertFalse(Version.active_for(self.outlet, "retail"))
