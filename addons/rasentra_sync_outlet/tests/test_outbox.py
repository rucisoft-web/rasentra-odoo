from datetime import timedelta

import requests

from odoo import fields
from odoo.tests import tagged

from odoo.addons.rasentra_core.tools import checksum

from .common import SyncOutletCase


@tagged("post_install", "-at_install", "rasentra")
class TestOutbox(SyncOutletCase):
    def _record(self, total="650000.00"):
        payload = {"order_no": "SLO-MS-0001", "total": total, "items": [{"pack": "P-0001", "qty": 1.0}]}
        return self.env["rasentra.sync.outbox"].record("order", "0192-order", "order.finalized", payload, "2026-10-29")

    def test_record_uses_php_compatible_checksum(self):
        event = self._record()
        self.assertEqual(event.checksum, checksum(event.payload))
        self.assertEqual(event.source_id, "SLO-MS-SRV")
        self.assertEqual(event.outlet_id, self.outlet)
        wire = event._to_wire()
        self.assertEqual(wire["outlet_id"], "SLO-MS")
        self.assertTrue(wire["occurred_at"].endswith("Z"))

    def test_dispatch_acks_accepted_and_duplicate(self):
        first, second = self._record(), self._record("1.00")

        def central(method, path, json, params):
            ids = [e["event_id"] for e in json["events"]]
            return {"results": [{"event_id": ids[0], "result": "accepted", "ack_ref": "ACK-1"},
                                {"event_id": ids[1], "result": "duplicate", "ack_ref": "ACK-0"}]}

        with self._central(central) as calls:
            self.assertEqual(self.env["rasentra.sync.outbox"].dispatch(), {"sent": 2})
        self.assertEqual(calls[0][:2], ("POST", "events"))
        self.assertEqual((first.state, first.ack_ref), ("acked", "ACK-1"))
        self.assertEqual((second.state, second.ack_ref), ("acked", "ACK-0"))
        with self._central(central) as calls:
            self.assertEqual(self.env["rasentra.sync.outbox"].dispatch(), {"sent": 0})
        self.assertFalse(calls, "tidak ada yang dikirim ulang setelah ack")

    def test_network_failure_backs_off_then_parks(self):
        event = self._record()

        def down(*args):
            raise requests.ConnectionError("Central tidak terjangkau")

        before = fields.Datetime.now()
        with self._central(down):
            result = self.env["rasentra.sync.outbox"].dispatch()
        self.assertIn("tidak terjangkau", result["error"])
        self.assertEqual((event.state, event.attempts), ("failed", 1))
        delay = (event.next_attempt_at - before).total_seconds()
        self.assertTrue(4 <= delay <= 11, delay)  # 5*2^1 = 10 detik, jitter 50-100%
        with self._central(down) as calls:
            self.env["rasentra.sync.outbox"].dispatch()
        self.assertFalse(calls, "belum waktunya dicoba lagi")

        event.sudo().write({"attempts": 19, "next_attempt_at": before - timedelta(seconds=1)})
        with self._central(down):
            self.env["rasentra.sync.outbox"].dispatch()
        self.assertEqual((event.state, event.attempts), ("parked", 20))
        event.action_retry()
        self.assertEqual((event.state, event.attempts), ("pending", 0))

    def test_rejected_event_is_retried_with_reason(self):
        event = self._record()
        with self._central(lambda *a: {"results": [{"event_id": event.event_uuid, "result": "rejected",
                                                    "error": "checksum tidak cocok"}]}):
            self.env["rasentra.sync.outbox"].dispatch()
        self.assertEqual(event.state, "failed")
        self.assertEqual(event.last_error, "checksum tidak cocok")

    def test_heartbeat_reports_outbox(self):
        self._record()
        with self._central(lambda m, p, j, q: {"server_time": j["sent_at"], "central_cursor": 9,
                                               "device": {"code": "SLO-MS-SRV"}}) as calls:
            result = self.env["rasentra.sync.agent"].run_heartbeat()
        self.assertTrue(result["ok"])
        self.assertEqual(result["clock_skew_seconds"], 0)
        payload = calls[0][2]
        self.assertEqual(payload["outbox"]["pending"], 1)
        self.assertEqual(payload["applied_cursor"], 0)

    def test_cron_enqueues_each_job_once(self):
        Job = self.env["queue.job"]
        before = Job.search_count([])
        self.env["rasentra.sync.agent"]._cron_sync()
        self.env["rasentra.sync.agent"]._cron_sync()
        self.assertEqual(Job.search_count([]) - before, 3)
