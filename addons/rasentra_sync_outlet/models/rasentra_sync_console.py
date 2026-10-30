import json

from odoo import fields, models

from .rasentra_sync_agent import LAST_HEARTBEAT, LAST_PULL


class RasentraSyncConsole(models.TransientModel):
    """Layar Sinkron di Rasentra Lokal: kondisi koneksi Central dan tombol jalankan sekarang."""

    _name = "rasentra.sync.console"
    _description = "Konsol sinkron Rasentra Lokal"

    central_url = fields.Char(readonly=True, default=lambda s: s._param("rasentra.central_url"))
    device_code = fields.Char(readonly=True, default=lambda s: s._param("rasentra.device_code"))
    outlet_code = fields.Char(readonly=True, default=lambda s: s._param("rasentra.outlet_code"))
    cursor = fields.Integer(readonly=True, default=lambda s: s.env["rasentra.sync.agent"].cursor())
    outbox_pending = fields.Integer(readonly=True, default=lambda s: s._stats()["pending"])
    outbox_failed = fields.Integer(readonly=True, default=lambda s: s._stats()["failed"])
    outbox_parked = fields.Integer(readonly=True, default=lambda s: s._stats()["parked"])
    last_pull = fields.Text(readonly=True, default=lambda s: s._state(LAST_PULL))
    last_heartbeat = fields.Text(readonly=True, default=lambda s: s._state(LAST_HEARTBEAT))
    result = fields.Text(readonly=True)

    def _param(self, key):
        return self.env["ir.config_parameter"].sudo().get_param(key) or ""

    def _stats(self):
        return self.env["rasentra.sync.outbox"].stats()

    def _state(self, key):
        state = self.env["rasentra.sync.agent"].get_state(key)
        return json.dumps(state, indent=2, ensure_ascii=False) if state else ""

    def _run(self, method):
        result = getattr(self.env["rasentra.sync.agent"], method)()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "target": "inline",
            "res_id": self.create({"result": json.dumps(result, indent=2, ensure_ascii=False)}).id,
        }

    def action_dispatch(self):
        return self._run("run_dispatch")

    def action_pull(self):
        return self._run("run_pull")

    def action_bootstrap(self):
        return self._run("run_bootstrap")

    def action_heartbeat(self):
        return self._run("run_heartbeat")
