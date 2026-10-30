from datetime import timezone

from dateutil import parser as dateparser

from odoo import api, fields, models


class RasentraOutletSyncState(models.Model):
    """Kondisi sinkron tiap server Rasentra Lokal (padanan outlet_sync_states), diisi dari ack dan heartbeat."""

    _name = "rasentra.outlet.sync.state"
    _description = "Status sinkron outlet"
    _order = "outlet_id"
    _rec_name = "device_id"

    device_id = fields.Many2one("rasentra.device", required=True, ondelete="cascade", readonly=True)
    outlet_id = fields.Many2one(related="device_id.outlet_id", store=True)
    applied_cursor = fields.Integer(readonly=True)
    last_pull_at = fields.Datetime(readonly=True)
    last_heartbeat_at = fields.Datetime(readonly=True)
    app_version = fields.Char(readonly=True)
    clock_skew_seconds = fields.Integer(readonly=True)
    outbox_pending = fields.Integer(readonly=True)
    outbox_failed = fields.Integer(readonly=True)
    outbox_parked = fields.Integer(readonly=True)
    outbox_oldest_at = fields.Datetime(readonly=True)
    last_sent_at = fields.Datetime(readonly=True)
    open_business_date = fields.Date(readonly=True)
    open_shifts = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)
    central_cursor = fields.Integer(compute="_compute_lag")
    lag = fields.Integer(string="Tertinggal (publikasi)", compute="_compute_lag")

    _sql_constraints = [("device_unique", "unique(device_id)", "Satu status per perangkat.")]

    def _compute_lag(self):
        last = self.env["rasentra.sync.publication"].sudo().search([], order="id desc", limit=1).id or 0
        for state in self:
            state.central_cursor = last
            state.lag = max(0, last - state.applied_cursor)

    @api.model
    def _for(self, device):
        state = self.sudo().search([("device_id", "=", device.id)], limit=1)
        return state or self.sudo().create({"device_id": device.id})

    @api.model
    def ack(self, device, data):
        """Port SyncController::ack."""
        acks = data.get("acks") or []
        profile = self.env["rasentra.profile"]
        for item in acks:
            model = profile.sync_model(item.get("entity_type"))
            if model is not None and hasattr(model, "_rasentra_sync_ack"):
                model.sudo()._rasentra_sync_ack(device, item)
        failed = next((a for a in acks if a.get("status") == "failed"), None)
        state = self._for(device)
        vals = {
            "last_pull_at": fields.Datetime.now(),
            "last_error": f"{failed['entity_type']} {failed['entity_key']}: {failed.get('error') or 'gagal diterapkan'}"
            if failed else False,
        }
        if data.get("cursor") is not None:
            vals["applied_cursor"] = max(state.applied_cursor, int(data["cursor"]))
        state.write(vals)
        return {"ok": True}

    @api.model
    def heartbeat(self, device, data):
        """Port SyncController::heartbeat. Status hanya disimpan untuk server Rasentra Lokal."""
        now = fields.Datetime.now()
        if device.app == "lokal":
            state = self._for(device)
            outbox = data.get("outbox") or {}
            vals = {
                "last_heartbeat_at": now,
                "app_version": data.get("app_version") or state.app_version,
                "clock_skew_seconds": int(round((self._utc(data["sent_at"]) - now).total_seconds()))
                if data.get("sent_at") else 0,
                "outbox_pending": outbox.get("pending") or 0,
                "outbox_failed": outbox.get("failed") or 0,
                "outbox_parked": outbox.get("parked") or 0,
                "outbox_oldest_at": self._utc(outbox["oldest_at"]) if outbox.get("oldest_at") else False,
                "last_sent_at": self._utc(outbox["last_sent_at"]) if outbox.get("last_sent_at") else state.last_sent_at,
                "open_business_date": data.get("open_business_date") or False,
                "open_shifts": data.get("open_shifts") or 0,
            }
            if data.get("applied_cursor") is not None:
                vals["applied_cursor"] = max(state.applied_cursor, int(data["applied_cursor"]))
            if "last_error" in data:
                vals["last_error"] = data["last_error"] or False
            state.write(vals)
        last = self.env["rasentra.sync.publication"].sudo().search([], order="id desc", limit=1)
        return {
            "server_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "central_cursor": last.id or 0,
            "device": {"code": device.code, "app": device.app, "outlet_code": device.outlet_id.code},
        }

    @staticmethod
    def _utc(value):
        """Waktu ISO-8601 dari perangkat menjadi datetime UTC naif seperti yang disimpan Odoo."""
        parsed = dateparser.isoparse(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
