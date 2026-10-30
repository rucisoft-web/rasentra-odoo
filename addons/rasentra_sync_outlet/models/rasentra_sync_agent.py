import json
import logging

from odoo import api, fields, models

from odoo.addons.queue_job.job import identity_exact

_logger = logging.getLogger(__name__)

CURSOR = "rasentra.sync_cursor"
LAST_PULL = "rasentra.sync_last_pull"
LAST_HEARTBEAT = "rasentra.sync_last_heartbeat"


class RasentraSyncAgent(models.AbstractModel):
    """Pekerjaan sinkron Rasentra Lokal: kirim outbox, tarik publikasi, bootstrap, heartbeat.

    Cron tiap menit hanya mengantrekan job queue_job; identity_key mencegah job ganda menumpuk
    saat Central lambat.
    """

    _name = "rasentra.sync.agent"
    _description = "Agen sinkron Rasentra Lokal"

    # ---- status -----------------------------------------------------------------

    def _param(self):
        return self.env["ir.config_parameter"].sudo()

    @api.model
    def cursor(self):
        return int(self._param().get_param(CURSOR) or 0)

    def _set_cursor(self, cursor):
        self._param().set_param(CURSOR, str(int(cursor)))

    def _put(self, key, value):
        self._param().set_param(key, json.dumps(value))

    @api.model
    def get_state(self, key):
        raw = self._param().get_param(key)
        return json.loads(raw) if raw else {}

    # ---- cron -------------------------------------------------------------------

    @api.model
    def _cron_sync(self):
        if not self.env["rasentra.profile"].is_lokal() or not self._param().get_param("rasentra.central_url"):
            return
        self.with_delay(identity_key=identity_exact, description="Rasentra: kirim outbox").run_dispatch()
        self.with_delay(identity_key=identity_exact, description="Rasentra: tarik publikasi").run_pull()
        self.with_delay(identity_key=identity_exact, description="Rasentra: heartbeat").run_heartbeat()

    @api.model
    def run_dispatch(self):
        return self.env["rasentra.sync.outbox"].dispatch()

    # ---- tarik publikasi ---------------------------------------------------------

    @api.model
    def run_pull(self, max_pages=20):
        """Port ChangePuller::pull. Cursor berhenti tepat sebelum publikasi pertama yang gagal."""
        client = self.env["rasentra.central.client"]
        cursor = self.cursor()
        applied = 0
        types = {}
        error = None
        for _page in range(max_pages):
            response = client._request("GET", "changes", params={"cursor": cursor})
            acks, error, reached = self._apply_all(response.get("changes", []), types)
            applied += sum(1 for a in acks if a["status"] == "applied")
            cursor = max(cursor, int(response["next_cursor"])) if error is None else reached
            self._set_cursor(cursor)
            self._ack(acks, cursor)
            if error is not None or not response.get("has_more"):
                break
        return self._done(applied, cursor, types, error)

    @api.model
    def run_bootstrap(self):
        """Port ChangePuller::bootstrap: terapkan snapshot lengkap, lalu lanjut dari cursor snapshot."""
        response = self.env["rasentra.central.client"]._request("GET", "snapshot", timeout=120)
        types = {}
        acks, error, _reached = self._apply_all(response["changes"], types)
        if error is not None:
            return {"snapshot": self._done(len(acks) - 1, self.cursor(), types, error)}
        self._set_cursor(response["cursor"])
        if outlet_code := response.get("outlet_code"):
            self._param().set_param("rasentra.outlet_code", outlet_code)
        return {"snapshot": self._done(len(acks), int(response["cursor"]), types), "pull": self.run_pull()}

    def _apply_all(self, changes, types):
        applier = self.env["rasentra.sync.applier"]
        acks = []
        reached = self.cursor()
        for change in changes:
            key = {"entity_type": change["entity_type"], "entity_key": str(change["entity_key"])}
            try:
                applier.apply(change)
            except Exception as exc:  # noqa: BLE001 - kegagalan dicatat di ack, tidak menghentikan cron
                _logger.warning("Publikasi %s %s gagal diterapkan: %s", key["entity_type"], key["entity_key"], exc)
                message = str(exc)[:1000]
                acks.append({**key, "status": "failed", "error": message})
                return acks, f"{key['entity_type']} {key['entity_key']}: {message}", reached
            acks.append({**key, "status": "applied"})
            types[change["entity_type"]] = types.get(change["entity_type"], 0) + 1
            reached = max(reached, int(change.get("id") or 0))
        return acks, None, reached

    def _ack(self, acks, cursor):
        try:
            self.env["rasentra.central.client"]._request("POST", "ack", json={"acks": acks, "cursor": cursor})
        except Exception as exc:  # noqa: BLE001
            # Cursor ikut terkirim lewat heartbeat (applied_cursor); publikasi tidak perlu ditarik ulang.
            _logger.info("Ack ke Central gagal, menunggu heartbeat: %s", exc)

    def _done(self, applied, cursor, types, error=None):
        entry = {"at": _zulu(fields.Datetime.now()), "applied": applied, "cursor": cursor, "error": error,
                 "types": types}
        self._put(LAST_PULL, entry)
        result = {"applied": applied, "cursor": cursor}
        if error:
            result["error"] = error
        return result

    # ---- heartbeat ---------------------------------------------------------------

    @api.model
    def heartbeat_payload(self):
        return {
            "sent_at": _zulu(fields.Datetime.now()),
            "app_version": self.env.ref("base.module_rasentra_sync_outlet").sudo().latest_version,
            "applied_cursor": self.cursor(),
            "outbox": self.env["rasentra.sync.outbox"].stats(),
            # Shift baru ada di tahap POS; sampai saat itu nilainya kosong.
            "open_business_date": None,
            "open_shifts": 0,
            "last_error": self.get_state(LAST_PULL).get("error"),
        }

    @api.model
    def run_heartbeat(self):
        """Port HeartbeatSender::send."""
        try:
            payload = self.heartbeat_payload()
            response = self.env["rasentra.central.client"]._request("POST", "heartbeat", json=payload, timeout=10)
            sent = fields.Datetime.to_datetime(payload["sent_at"].replace("T", " ").rstrip("Z"))
            server = fields.Datetime.to_datetime(response["server_time"].replace("T", " ").rstrip("Z"))
            result = {"ok": True, "clock_skew_seconds": int(round((sent - server).total_seconds())),
                      "central_cursor": response.get("central_cursor"), "device": response.get("device")}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)[:500]}
        self._put(LAST_HEARTBEAT, {**result, "at": _zulu(fields.Datetime.now())})
        return result


def _zulu(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
