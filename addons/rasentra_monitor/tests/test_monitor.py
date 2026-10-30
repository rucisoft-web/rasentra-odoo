from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase


@tagged("post_install", "-at_install", "rasentra")
class TestMonitor(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": cls.outlet.id, "app": "lokal"})
        cls.Monitor = cls.env["rasentra.monitor"]
        cls.States = cls.env["rasentra.outlet.sync.state"]

    def test_health_levels(self):
        now = fields.Datetime.now()
        self.assertEqual(self.Monitor.health(self.States, now=now), "none")
        state = self.States._for(self.device)
        self.assertEqual(self.Monitor.health(state, now=now), "none", "belum pernah heartbeat")
        state.write({"last_heartbeat_at": now - timedelta(minutes=1)})
        self.assertEqual(self.Monitor.health(state, now=now), "ok")
        self.assertEqual(self.Monitor.health(state, lag=2, now=now), "warn")
        state.write({"last_heartbeat_at": now - timedelta(minutes=5)})
        self.assertEqual(self.Monitor.health(state, now=now), "warn")
        state.write({"last_heartbeat_at": now - timedelta(minutes=1), "clock_skew_seconds": 400})
        self.assertEqual(self.Monitor.health(state, now=now), "err")
        state.write({"last_heartbeat_at": now - timedelta(minutes=20)})
        self.assertEqual(self.Monitor.health(state, now=now), "lost")

    def test_status_page_data(self):
        self.States.heartbeat(self.device, {"app_version": "18.0.1", "outbox": {"pending": 3}})
        data = self.Monitor.status()
        row = next(o for o in data["outlets"] if o["id"] == self.outlet.id)
        self.assertEqual((row["health"], row["outbox_pending"], row["app_version"]), ("ok", 3, "18.0.1"))
        self.assertEqual(set(data["inbox"]), {"hour", "day", "failed", "waiting", "last"})
        self.assertIn("exceptions", data)
        self.assertTrue(self.Monitor.open_action("exceptions"))
        self.assertFalse(self.Monitor.open_action("unknown"))
