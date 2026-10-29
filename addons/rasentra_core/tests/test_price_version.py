from decimal import Decimal

from odoo.exceptions import UserError
from odoo.tests import tagged

from ..tools import RasentraError
from .common import RasentraCase


@tagged("post_install", "-at_install", "rasentra")
class TestPriceVersion(RasentraCase):
    def test_outlet_specific_beats_all_outlets(self):
        self._publish_price("ALL-1", 180000)
        specific = self._publish_price("SLO-1", 200000, outlet=self.outlet)
        price, version = self.env["rasentra.price.version"].resolve(self.sirloin, self.outlet, "retail")
        self.assertEqual(price, Decimal("200000.00"))
        self.assertEqual(version, specific)
        price_other, _v = self.env["rasentra.price.version"].resolve(self.sirloin, self.other_outlet, "retail")
        self.assertEqual(price_other, Decimal("180000.00"))

    def test_channel_specific_beats_all_channels(self):
        self._publish_price("SLO-ALL", 200000, outlet=self.outlet)
        self._publish_price("SLO-RESTO", 220000, outlet=self.outlet, channel="restaurant")
        resolve = self.env["rasentra.price.version"].resolve
        self.assertEqual(resolve(self.sirloin, self.outlet, "restaurant")[0], Decimal("220000.00"))
        self.assertEqual(resolve(self.sirloin, self.outlet, "retail")[0], Decimal("200000.00"))

    def test_draft_is_ignored_and_missing_price_raises(self):
        self.env["rasentra.price.version"].create(
            {"code": "DRAFT", "item_ids": [(0, 0, {"product_id": self.sirloin.id, "unit_price": 1})]}
        )
        with self.assertRaises(RasentraError) as err:
            self.env["rasentra.price.version"].resolve(self.sirloin, self.outlet)
        self.assertEqual(err.exception.code, "price_not_found")

    def test_published_version_is_immutable(self):
        version = self._publish_price("SLO-1", 200000, outlet=self.outlet)
        with self.assertRaises(UserError):
            version.note = "ubah"
        with self.assertRaises(UserError):
            version.item_ids.unit_price = 1
        with self.assertRaises(UserError):
            version.unlink()
        self.assertTrue(
            self.env["rasentra.audit.event"].search_count(
                [("action", "=", "price_version.published"), ("subject_ref", "=", version.uuid)]
            )
        )
