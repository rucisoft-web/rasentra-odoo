import logging
import random
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import checksum, uuid7

_logger = logging.getLogger(__name__)

BATCH = 500
BACKOFF_BASE = 5
BACKOFF_MAX = 900
MAX_ATTEMPTS = 20
OPEN_STATES = ("pending", "sending", "failed", "parked")


class RasentraSyncOutbox(models.Model):
    """Event bisnis Rasentra Lokal yang menunggu dikirim ke Central (padanan outbox_events).

    `record()` wajib dipanggil dalam transaksi yang sama dengan dokumen dan pergerakan stoknya,
    sehingga tidak ada transaksi tanpa event. Pengiriman at-least-once; Central menjamin idempotensi.
    """

    _name = "rasentra.sync.outbox"
    _description = "Outbox sinkron Rasentra"
    _order = "id"

    event_uuid = fields.Char(required=True, readonly=True, index=True, default=lambda self: uuid7())
    source_id = fields.Char(required=True, readonly=True)
    outlet_id = fields.Many2one("rasentra.outlet", readonly=True)
    entity_type = fields.Char(required=True, readonly=True)
    entity_uuid = fields.Char(required=True, readonly=True, index=True)
    entity_version = fields.Integer(default=1, readonly=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    schema_version = fields.Integer(default=1, readonly=True)
    occurred_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    business_date = fields.Date(required=True, readonly=True)
    correlation_id = fields.Char(readonly=True)
    payload = fields.Json(required=True, readonly=True)
    checksum = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [("pending", "Menunggu"), ("sending", "Mengirim"), ("acked", "Diterima Central"), ("failed", "Gagal, dicoba lagi"),
         ("parked", "Berhenti dicoba"), ("held", "Ditahan")],
        default="pending", required=True, index=True, readonly=True,
    )
    attempts = fields.Integer(readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    ack_ref = fields.Char(readonly=True)
    last_error = fields.Text(readonly=True)
    acked_at = fields.Datetime(readonly=True)

    _sql_constraints = [("event_uuid_unique", "unique(event_uuid)", "Event outbox harus unik.")]

    @api.model
    def record(self, entity_type, entity_uuid, event_type, payload, business_date,
               entity_version=1, correlation_id=None, outlet=None):
        """Port Outbox::record."""
        params = self.env["ir.config_parameter"].sudo()
        return self.sudo().create(
            {
                "source_id": params.get_param("rasentra.device_code") or "",
                "outlet_id": (outlet or self.env["rasentra.profile"].current_outlet()).id,
                "entity_type": entity_type,
                "entity_uuid": str(entity_uuid),
                "entity_version": entity_version,
                "event_type": event_type,
                "business_date": business_date,
                "correlation_id": correlation_id or uuid7(),
                "payload": payload,
                "checksum": checksum(payload),
            }
        )

    def _to_wire(self):
        self.ensure_one()
        return {
            "event_id": self.event_uuid,
            "source_id": self.source_id,
            "outlet_id": self.outlet_id.code,
            "entity_type": self.entity_type,
            "entity_id": self.entity_uuid,
            "entity_version": self.entity_version,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "business_date": fields.Date.to_string(self.business_date),
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "checksum": self.checksum,
        }

    @api.model
    def dispatch(self):
        """Port OutboxDispatcher::dispatch. Gagal = backoff eksponensial + jitter, lalu parked."""
        now = fields.Datetime.now()
        events = self.sudo().search(
            [("state", "in", ("pending", "failed")), "|", ("next_attempt_at", "=", False), ("next_attempt_at", "<=", now)],
            order="id", limit=BATCH,
        )
        if not events:
            return {"sent": 0}
        events.write({"state": "sending"})
        try:
            response = self.env["rasentra.central.client"]._request(
                "POST", "events", json={"events": [e._to_wire() for e in events]}, timeout=15
            )
            results = {r.get("event_id"): r for r in response.get("results", [])}
        except Exception as exc:  # noqa: BLE001 - semua kegagalan jaringan/HTTP diperlakukan sama
            _logger.warning("Kirim outbox gagal: %s", exc)
            for event in events:
                event._fail(str(exc))
            return {"sent": 0, "error": str(exc)}
        acked = 0
        for event in events:
            result = results.get(event.event_uuid)
            if result and result.get("result") in ("accepted", "duplicate"):
                event.write({"state": "acked", "ack_ref": result.get("ack_ref"), "last_error": False, "acked_at": now})
                acked += 1
            else:
                event._fail((result or {}).get("error") or "tidak ada hasil untuk event ini")
        return {"sent": acked}

    def _fail(self, error):
        attempts = self.attempts + 1
        delay = min(BACKOFF_MAX, BACKOFF_BASE * 2 ** min(attempts, 10))
        delay = int(delay * (0.5 + random.random() / 2))  # jitter 50-100%
        self.write(
            {
                "state": "parked" if attempts >= MAX_ATTEMPTS else "failed",
                "attempts": attempts,
                "next_attempt_at": fields.Datetime.now() + timedelta(seconds=delay),
                "last_error": error[:2000],
            }
        )

    def action_retry(self):
        """Kembalikan event gagal/parked/ditahan ke antrean (padanan tombol Coba lagi)."""
        retry = self.filtered(lambda e: e.state in ("failed", "parked", "held"))
        retry.sudo().write({"state": "pending", "attempts": 0, "next_attempt_at": False})
        for event in retry:
            self.env["rasentra.audit.event"].record(
                "outbox.requeued", f"rasentra.sync.outbox:{event.event_uuid}", outlet=event.outlet_id,
                after={"event_type": event.event_type},
            )
        return True

    @api.model
    def stats(self):
        open_events = self.sudo().search([("state", "in", OPEN_STATES)], order="occurred_at", limit=1)
        last = self.sudo().search([("state", "=", "acked")], order="acked_at desc", limit=1)
        count = self.sudo().search_count
        return {
            "pending": count([("state", "in", ("pending", "sending"))]),
            "failed": count([("state", "=", "failed")]),
            "parked": count([("state", "=", "parked")]),
            "oldest_at": _zulu(open_events.occurred_at),
            "last_sent_at": _zulu(last.acked_at),
        }


def _zulu(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None
