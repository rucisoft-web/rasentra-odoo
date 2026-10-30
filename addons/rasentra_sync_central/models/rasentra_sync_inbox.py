import hmac
import logging
import secrets

from psycopg2 import IntegrityError

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import checksum

_logger = logging.getLogger(__name__)

REQUIRED = (
    "event_id", "source_id", "outlet_id", "entity_type", "entity_id",
    "entity_version", "event_type", "payload", "checksum",
)


class RasentraSyncInbox(models.Model):
    """Event dari Rasentra Lokal (padanan inbox_events). Unik per (source_id, event_uuid):
    event yang dikirim ulang dibalas ack_ref yang sama, tidak diproses dua kali."""

    _name = "rasentra.sync.inbox"
    _description = "Inbox sinkron Rasentra"
    _order = "id desc"

    source_id = fields.Char(required=True, index=True, readonly=True)
    event_uuid = fields.Char(required=True, readonly=True)
    device_id = fields.Many2one("rasentra.device", readonly=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    entity_type = fields.Char(required=True, readonly=True)
    entity_uuid = fields.Char(required=True, readonly=True, index=True)
    entity_version = fields.Integer(readonly=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    schema_version = fields.Integer(default=1, readonly=True)
    occurred_at = fields.Char(readonly=True)
    business_date = fields.Date(readonly=True, index=True)
    correlation_id = fields.Char(readonly=True)
    payload = fields.Json(readonly=True)
    checksum = fields.Char(readonly=True)
    ack_ref = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [("accepted", "Diterima"), ("deferred_dependency", "Menunggu induk"), ("processed", "Diproses"),
         ("failed", "Gagal diproses")],
        default="accepted", required=True, index=True,
    )
    error = fields.Text()

    _sql_constraints = [("event_unique", "unique(source_id, event_uuid)", "Event sudah diterima.")]

    @api.model
    def receive_batch(self, device, events):
        """Port InboxReceiver::receive. `source_id` wajib sama dengan kode perangkat pemilik token.

        Outlet diambil dari perangkat yang terautentikasi, bukan dari `outlet_id` di event,
        karena id outlet Laravel dan Odoo berbeda.
        """
        return [self._receive_one(device, event) for event in events]

    def _receive_one(self, device, event):
        event_id = str(event.get("event_id") or "")
        missing = [f for f in REQUIRED if f not in event]
        if missing:
            return {"event_id": event_id, "result": "rejected", "error": f"field {missing[0]} wajib"}
        if event["source_id"] != device.code:
            return {"event_id": event_id, "result": "rejected", "error": "source_id tidak sesuai token perangkat"}
        if not hmac.compare_digest(str(event["checksum"]), checksum(event["payload"])):
            return {"event_id": event_id, "result": "rejected", "error": "checksum tidak cocok"}

        inbox = self.sudo()
        existing = inbox.search([("source_id", "=", device.code), ("event_uuid", "=", event_id)], limit=1)
        if existing:
            return {"event_id": event_id, "result": "duplicate", "ack_ref": existing.ack_ref}
        try:
            with self.env.cr.savepoint():
                record = inbox.create(
                    {
                        "source_id": device.code,
                        "event_uuid": event_id,
                        "device_id": device.id,
                        "outlet_id": device.outlet_id.id,
                        "entity_type": event["entity_type"],
                        "entity_uuid": str(event["entity_id"]),
                        "entity_version": int(event["entity_version"] or 0),
                        "event_type": event["event_type"],
                        "schema_version": int(event.get("schema_version") or 1),
                        "occurred_at": event.get("occurred_at"),
                        "business_date": event.get("business_date") or False,
                        "correlation_id": event.get("correlation_id"),
                        "payload": event["payload"],
                        "checksum": event["checksum"],
                        "ack_ref": "ACK-" + secrets.token_hex(10).upper(),
                    }
                )
                record._process()
        except IntegrityError:
            # Dua worker mengirim event sama bersamaan: yang kalah membaca ack milik pemenang.
            winner = inbox.search([("source_id", "=", device.code), ("event_uuid", "=", event_id)], limit=1)
            return {"event_id": event_id, "result": "duplicate", "ack_ref": winner.ack_ref}
        return {"event_id": event_id, "result": "accepted", "ack_ref": record.ack_ref}

    def _process(self):
        """Proyeksi event ke model Central. Tahap berikutnya menambah handler lewat
        `_rasentra_handle_<event_type dengan titik diganti garis bawah>` (mis. `_rasentra_handle_order_finalized`)."""
        for event in self:
            handler = getattr(event, "_rasentra_handle_" + event.event_type.replace(".", "_"), None)
            if handler:
                handler()
                event.state = "processed"
