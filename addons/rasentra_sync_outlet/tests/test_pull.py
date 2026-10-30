from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.rasentra_core.tools import uuid7

from .common import SyncOutletCase

OUTLET_UUID = "0192f0aa-0000-7000-8000-00000000a001"


def _changes():
    return [
        {"id": 11, "entity_type": "outlet", "entity_key": OUTLET_UUID, "payload": {
            "uuid": OUTLET_UUID, "code": "LOP-MS", "name": "Meatshop Lombok",
            "company": {"name": "CV Lombok", "legal_name": "CV Lombok Kulina Utama", "sap_company_db": "sap_lombok"},
            "region": {"code": "LOP", "name": "Lombok"}, "tz": "Asia/Makassar", "retail_name": None,
            "restaurant_name": None, "has_retail": True, "has_restaurant": False, "has_cooking_fee": False,
            "sap_warehouse_code": "LOP01", "active": True}},
        {"id": 12, "entity_type": "product", "entity_key": "RIBEYE-AUS", "payload": {
            "default_code": "RIBEYE-AUS", "name": "Ribeye AUS", "barcode": None, "uom": "kg",
            "rasentra_type": "meat_pack", "kitchen_station": None, "tracking": "lot", "is_storable": True,
            "active": True}},
        {"id": 13, "entity_type": "employee", "entity_key": "0192f0aa-0000-7000-8000-00000000e001", "payload": {
            "uuid": "0192f0aa-0000-7000-8000-00000000e001", "name": "Kasir Lombok", "role": "cashier",
            "outlet_uuid": OUTLET_UUID, "pin": "2468", "approval_limit": "0.00", "active": True}},
        {"id": 14, "entity_type": "price_version", "entity_key": "0192f0aa-0000-7000-8000-00000000f001", "payload": {
            "uuid": "0192f0aa-0000-7000-8000-00000000f001", "code": "HRG-LOP-1", "outlet_uuid": OUTLET_UUID,
            "channel": "retail", "effective_from": "2026-01-01 00:00:00", "effective_to": None, "note": None,
            "items": [{"product_code": "RIBEYE-AUS", "unit_price": "480000.00"}]}},
    ]


@tagged("post_install", "-at_install", "rasentra")
class TestPull(SyncOutletCase):
    def _counts(self):
        env = self.env(context={"active_test": False})
        return (
            env["rasentra.outlet"].search_count([]),
            env["product.product"].search_count([("default_code", "=", "RIBEYE-AUS")]),
            env["hr.employee"].search_count([("rasentra_uuid", "!=", False)]),
            env["rasentra.price.version"].search_count([]),
        )

    def _serve(self, changes, acks):
        def central(method, path, json, params):
            if path == "changes":
                page = [c for c in changes if c["id"] > int(params["cursor"])]
                return {"outlet_code": "SLO-MS", "changes": page,
                        "next_cursor": max([c["id"] for c in page] or [int(params["cursor"])]), "has_more": False}
            acks.append(json)
            return {"ok": True}
        return central

    def test_pull_creates_then_is_idempotent(self):
        before = self._counts()
        acks = []
        with self._central(self._serve(_changes(), acks)):
            result = self.env["rasentra.sync.agent"].run_pull()
        self.assertEqual(result, {"applied": 4, "cursor": 14})
        self.assertEqual(self._counts(), tuple(b + 1 for b in before))
        self.assertEqual(acks[-1]["cursor"], 14)
        self.assertTrue(all(a["status"] == "applied" for a in acks[-1]["acks"]))

        lombok = self.env["rasentra.outlet"].search([("uuid", "=", OUTLET_UUID)])
        ribeye = self.env["product.product"].search([("default_code", "=", "RIBEYE-AUS")])
        price, version = self.env["rasentra.price.version"].resolve(ribeye, lombok, "retail")
        self.assertEqual(str(price), "480000.00")
        self.assertEqual(version.state, "published")
        self.assertEqual(lombok.region_id.code, "LOP")

        # Delta yang sama diterapkan ulang (cursor direset): tidak ada duplikat.
        self.env["rasentra.sync.agent"]._set_cursor(0)
        with self._central(self._serve(_changes(), acks)):
            self.env["rasentra.sync.agent"].run_pull()
        self.assertEqual(self._counts(), tuple(b + 1 for b in before))

    def test_cursor_stops_before_first_failure(self):
        changes = _changes()
        changes[3]["payload"]["items"][0]["product_code"] = "TIDAK-ADA"
        changes.append({"id": 15, "entity_type": "product", "entity_key": "TBONE", "payload": {
            **changes[1]["payload"], "default_code": "TBONE", "name": "T-Bone"}})
        acks = []
        with self._central(self._serve(changes, acks)):
            result = self.env["rasentra.sync.agent"].run_pull()
        self.assertEqual(result["cursor"], 13)
        self.assertIn("TIDAK-ADA", result["error"])
        self.assertEqual(acks[-1]["acks"][-1]["status"], "failed")
        self.assertEqual(acks[-1]["cursor"], 13)
        self.assertFalse(self.env["product.product"].search([("default_code", "=", "TBONE")]))
        self.assertFalse(self.env["rasentra.price.version"].search([("code", "=", "HRG-LOP-1")]))
        self.assertIn("TIDAK-ADA", self.env["rasentra.sync.agent"].heartbeat_payload()["last_error"])


@tagged("post_install", "-at_install", "rasentra")
class TestLokalToCentral(SyncOutletCase):
    """Satu database berperan sebagai Central dan Lokal sekaligus: bootstrap, kirim event dan
    heartbeat lewat API FastAPI yang sebenarnya. Dilewati bila rasentra_sync_central tidak terpasang."""

    def setUp(self):
        super().setUp()
        if "rasentra.sync.inbox" not in self.env:
            self.skipTest("rasentra_sync_central tidak terpasang")

    @contextmanager
    def _via_central_api(self, token):
        from fastapi.testclient import TestClient

        from odoo.addons.fastapi.context import odoo_env_ctx

        endpoint = self.env.ref("rasentra_sync_central.endpoint_sync")
        client = TestClient(endpoint._get_app())
        ctx = odoo_env_ctx.set(self.env(user=endpoint.user_id))

        def request(model, method, path, json=None, params=None, timeout=20):
            res = client.request(method, "/" + path, json=json, params=params,
                                 headers={"Authorization": f"Bearer {token}"})
            res.raise_for_status()
            return res.json()

        try:
            with patch.object(type(self.env["rasentra.central.client"]), "_request", request):
                yield
        finally:
            odoo_env_ctx.reset(ctx)

    def test_bootstrap_send_and_heartbeat(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("rasentra.profile", "central")
        device = self.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": self.outlet.id, "app": "lokal"}
        )
        token = device.rotate_token()
        self.sirloin.default_code = "SIRLOIN-AUS"
        self._publish_price("HRG-SLO-1", 650000, outlet=self.outlet)
        last = self.env["rasentra.sync.publication"].search([], order="id desc", limit=1)
        params.set_param("rasentra.profile", "lokal")
        params.set_param("rasentra.outlet_code", "")

        before = (self.env["rasentra.outlet"].search_count([]), self.env["rasentra.price.version"].search_count([]))
        with self._via_central_api(token):
            result = self.env["rasentra.sync.agent"].run_bootstrap()
            self.assertNotIn("error", result["snapshot"], result)
            self.assertEqual(result["snapshot"]["cursor"], last.id)
            self.assertEqual(params.get_param("rasentra.outlet_code"), "SLO-MS")
            self.assertEqual(
                (self.env["rasentra.outlet"].search_count([]), self.env["rasentra.price.version"].search_count([])),
                before, "snapshot atas data yang sudah ada tidak membuat duplikat",
            )

            event = self.env["rasentra.sync.outbox"].record(
                "order", uuid7(), "order.finalized", {"total": "650000.00", "note": "kirim/ambil"}, "2026-10-29"
            )
            self.assertEqual(self.env["rasentra.sync.outbox"].dispatch(), {"sent": 1})
            self.assertTrue(self.env["rasentra.sync.agent"].run_heartbeat()["ok"])

        inbox = self.env["rasentra.sync.inbox"].search([("event_uuid", "=", event.event_uuid)])
        self.assertEqual(inbox.ack_ref, event.ack_ref)
        state = self.env["rasentra.outlet.sync.state"].search([("device_id", "=", device.id)])
        self.assertEqual(state.applied_cursor, last.id)
        self.assertEqual(state.outbox_pending, 0)
