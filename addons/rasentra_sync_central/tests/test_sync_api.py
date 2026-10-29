from contextlib import contextmanager

from fastapi.testclient import TestClient

from odoo.tests import tagged

from odoo.addons.fastapi.context import odoo_env_ctx
from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import checksum, uuid7


@tagged("post_install", "-at_install", "rasentra")
class TestSyncApi(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "central")
        cls.lokal = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": cls.outlet.id, "app": "lokal"}
        )
        cls.pos = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-POS1", "name": "POS 1", "outlet_id": cls.outlet.id, "app": "pos"}
        )
        cls.lokal_token = cls.lokal.rotate_token()
        cls.pos_token = cls.pos.rotate_token()
        cls.endpoint = cls.env.ref("rasentra_sync_central.endpoint_sync")

    @contextmanager
    def _client(self):
        app = self.endpoint._get_app()
        token = odoo_env_ctx.set(self.env(user=self.endpoint.user_id))
        try:
            yield TestClient(app, raise_server_exceptions=False)
        finally:
            odoo_env_ctx.reset(token)

    def _event(self, source="SLO-MS-SRV", **payload):
        payload = payload or {"order_no": "SLO-MS-0001", "total": "650000.00", "note": "a/b"}
        return {
            "event_id": uuid7(),
            "source_id": source,
            "outlet_id": 99,
            "entity_type": "order",
            "entity_id": uuid7(),
            "entity_version": 1,
            "event_type": "order.finalized",
            "schema_version": 1,
            "occurred_at": "2026-10-29T03:00:00Z",
            "business_date": "2026-10-29",
            "payload": payload,
            "checksum": checksum(payload),
        }

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_events_accept_duplicate_and_reject(self):
        event = self._event()
        bad_checksum = dict(self._event(), checksum="0" * 64)
        foreign = self._event(source="SLO-RB-SRV")
        with self._client() as client:
            res = client.post("/events", json={"events": [event, bad_checksum, foreign]}, headers=self._auth(self.lokal_token))
            self.assertEqual(res.status_code, 200, res.text)
            results = res.json()["results"]
            self.assertEqual([r["result"] for r in results], ["accepted", "rejected", "rejected"])
            again = client.post("/events", json={"events": [event]}, headers=self._auth(self.lokal_token)).json()
        self.assertEqual(again["results"][0]["result"], "duplicate")
        self.assertEqual(again["results"][0]["ack_ref"], results[0]["ack_ref"])
        inbox = self.env["rasentra.sync.inbox"].search([("event_uuid", "=", event["event_id"])])
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox.outlet_id, self.outlet, "outlet diambil dari perangkat, bukan dari event")

    def test_unauthenticated(self):
        with self._client() as client:
            self.assertEqual(client.post("/events", json={"events": []}).status_code, 401)
            self.assertEqual(client.get("/changes", headers=self._auth("salah")).status_code, 401)
            self.pos.action_revoke()
            self.assertEqual(client.get("/changes", headers=self._auth(self.pos_token)).status_code, 401)

    def test_batch_limit(self):
        with self._client() as client:
            res = client.post("/events", json={"events": [{}] * 501}, headers=self._auth(self.lokal_token))
        self.assertEqual(res.status_code, 422)

    def test_central_publishes_and_filters_changes(self):
        start = self.env["rasentra.sync.publication"].search([], order="id desc", limit=1).id or 0
        self.sirloin.default_code = "SIRLOIN-AUS"
        waiter = self.env["hr.employee"].create(
            {"name": "Pelayan RB", "rasentra_role": "waiter", "rasentra_outlet_id": self.other_outlet.id, "pin": "2222"}
        )
        self.head.approval_limit = 750000
        self._publish_price("HRG-SLO-1", 650000, outlet=self.outlet)
        with self._client() as client:
            lokal = client.get(f"/changes?cursor={start}", headers=self._auth(self.lokal_token)).json()
            pos = client.get(f"/changes?cursor={start}", headers=self._auth(self.pos_token)).json()
        keys = {(c["entity_type"], c["entity_key"]) for c in lokal["changes"]}
        self.assertIn(("product", "SIRLOIN-AUS"), keys)
        self.assertIn(("employee", self.head.rasentra_uuid), keys)
        self.assertNotIn(("employee", waiter.rasentra_uuid), keys, "petugas outlet lain tidak turun")
        price = next(c for c in lokal["changes"] if c["entity_type"] == "price_version")
        self.assertEqual(price["payload"]["items"], [{"product_code": "SIRLOIN-AUS", "unit_price": "650000.00"}])
        head = next(c for c in lokal["changes"] if c["entity_key"] == self.head.rasentra_uuid)
        self.assertEqual(head["payload"]["approval_limit"], "750000.00")
        self.assertFalse([c for c in pos["changes"] if c["entity_type"] == "employee"], "PIN hanya untuk server Lokal")
        self.assertEqual(lokal["next_cursor"], pos["next_cursor"])
        self.assertFalse(lokal["has_more"])
        self.assertEqual(lokal["outlet_code"], "SLO-MS")

    def test_lokal_profile_does_not_publish(self):
        self.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "lokal")
        before = self.env["rasentra.sync.publication"].search_count([])
        self.head.approval_limit = 900000
        self.assertEqual(self.env["rasentra.sync.publication"].search_count([]), before)

    def test_snapshot_only_for_lokal_server(self):
        self.sirloin.default_code = "SIRLOIN-AUS"
        self._publish_price("HRG-ALL-1", 600000)
        with self._client() as client:
            self.assertEqual(client.get("/snapshot", headers=self._auth(self.pos_token)).status_code, 403)
            snap = client.get("/snapshot", headers=self._auth(self.lokal_token)).json()
        types = [c["entity_type"] for c in snap["changes"]]
        self.assertEqual(types[0], "outlet")
        self.assertLess(types.index("product"), types.index("price_version"))
        self.assertEqual(len([t for t in types if t == "employee"]), 2)
        self.assertEqual(snap["changes"][0]["payload"]["company"]["sap_company_db"], "sap_solo")

    def test_heartbeat_and_ack(self):
        with self._client() as client:
            hb = client.post(
                "/heartbeat",
                json={"sent_at": "2026-10-29T03:00:00Z", "app_version": "18.0.1", "applied_cursor": 5,
                      "outbox": {"pending": 3, "failed": 1, "parked": 0}, "open_business_date": "2026-10-29",
                      "open_shifts": 2},
                headers=self._auth(self.lokal_token),
            ).json()
            self.assertEqual(hb["device"], {"code": "SLO-MS-SRV", "app": "lokal", "outlet_code": "SLO-MS"})
            client.post("/ack", json={"cursor": 3, "acks": [{"entity_type": "product", "entity_key": "X",
                                                              "status": "failed", "error": "uom tidak dikenal"}]},
                        headers=self._auth(self.lokal_token))
            client.post("/heartbeat", json={}, headers=self._auth(self.pos_token))
        state = self.env["rasentra.outlet.sync.state"].search([("device_id", "=", self.lokal.id)])
        self.assertEqual(state.applied_cursor, 5, "cursor tidak pernah mundur")
        self.assertEqual(state.outbox_pending, 3)
        self.assertEqual(state.open_shifts, 2)
        self.assertEqual(state.last_error, "product X: uom tidak dikenal")
        self.assertFalse(self.env["rasentra.outlet.sync.state"].search([("device_id", "=", self.pos.id)]))
