import json
from datetime import timedelta

from odoo import _, api, fields, models

# Heartbeat lebih tua dari ini dianggap terlambat / terputus (menit); selisih jam perangkat (detik).
LATE_MINUTES = 3
LOST_MINUTES = 15
SKEW_SECONDS = 120

HEALTH_LABELS = {
    "ok": "Normal",
    "warn": "Perlu dicek",
    "err": "Bermasalah",
    "lost": "Terputus: server Lokal mati atau jaringan outlet putus",
    "none": "Belum pernah terhubung",
}


class RasentraMonitor(models.AbstractModel):
    """Halaman Status Central (port CentralController + MonitoringController)."""

    _name = "rasentra.monitor"
    _description = "Status Central Rasentra"

    @api.model
    def health(self, state, lag=0, now=None):
        """none (belum pernah heartbeat), lost (heartbeat >= 15 menit), err, warn, ok."""
        if not state or not state.last_heartbeat_at:
            return "none"
        now = now or fields.Datetime.now()
        age = (now - state.last_heartbeat_at).total_seconds() / 60
        if age >= LOST_MINUTES:
            return "lost"
        if state.outbox_parked > 0 or abs(state.clock_skew_seconds or 0) > SKEW_SECONDS:
            return "err"
        if age >= LATE_MINUTES or lag > 0 or state.outbox_failed > 0 or state.last_error:
            return "warn"
        return "ok"

    @api.model
    def _outlets(self, now):
        States = self.env["rasentra.outlet.sync.state"].sudo()
        rows = []
        for outlet in self.env["rasentra.outlet"].sudo().search([("active", "=", True)], order="company_id, code"):
            state = States.search([("outlet_id", "=", outlet.id)], order="last_heartbeat_at desc", limit=1)
            lag = state.lag if state else 0
            health = self.health(state, lag, now)
            rows.append({
                "id": outlet.id, "code": outlet.code, "name": outlet.name, "company": outlet.company_id.name,
                "tz": outlet.tz, "health": health, "health_label": HEALTH_LABELS[health],
                "device": state.device_id.code if state else None,
                "last_heartbeat": fields.Datetime.to_string(state.last_heartbeat_at) if state.last_heartbeat_at else None,
                "heartbeat_minutes": int((now - state.last_heartbeat_at).total_seconds() // 60)
                if state.last_heartbeat_at else None,
                "lag": lag, "app_version": state.app_version or None,
                "outbox_pending": state.outbox_pending, "outbox_failed": state.outbox_failed,
                "outbox_parked": state.outbox_parked, "clock_skew": state.clock_skew_seconds,
                "open_business_date": fields.Date.to_string(state.open_business_date) if state.open_business_date else None,
                "open_shifts": state.open_shifts, "last_error": state.last_error or None,
            })
        return rows

    @api.model
    def status(self):
        now = fields.Datetime.now()
        Inbox = self.env["rasentra.sync.inbox"].sudo()
        Sap = self.env["rasentra.sap.document"].sudo()
        params = self.env["ir.config_parameter"].sudo()
        companies = []
        for company in self.env["res.company"].sudo().search([("sap_company_db", "!=", False)], order="id"):
            db = company.sap_company_db
            counts = {g["status"]: g["status_count"] for g in Sap.read_group([("company_db", "=", db)], ["status"], ["status"])}
            raw = params.get_param(f"rasentra.sap.health.{db}")
            companies.append({"name": company.name, "company_db": db, "sap": counts,
                              "health": json.loads(raw) if raw else None})
        week = fields.Date.context_today(self) - timedelta(days=7)
        reconciliation = {g["status"]: g["status_count"] for g in self.env["rasentra.day.reconciliation"].sudo().read_group(
            [("business_date", ">=", week)], ["status"], ["status"])}
        last = Inbox.search([], order="id desc", limit=1)
        return {
            "now": fields.Datetime.to_string(now),
            "profile": self.env["rasentra.profile"].get(),
            "cursor": self.env["rasentra.sync.publication"].sudo().search([], order="id desc", limit=1).id or 0,
            "outlets": self._outlets(now),
            "inbox": {
                "hour": Inbox.search_count([("create_date", ">=", now - timedelta(hours=1))]),
                "day": Inbox.search_count([("create_date", ">=", now - timedelta(days=1))]),
                "failed": Inbox.search_count([("state", "=", "failed")]),
                "waiting": Inbox.search_count([("state", "=", "deferred_dependency")]),
                "last": fields.Datetime.to_string(last.create_date) if last else None,
            },
            "companies": companies,
            "exceptions": self.env["rasentra.integration.exception"].sudo().search_count([("status", "=", "open")]),
            "needs_review": Sap.search_count([("status", "in", ("needs_review", "failed", "partially_posted"))]),
            "reconciliation": reconciliation,
        }

    @api.model
    def post_sap_now(self):
        summary = self.env["rasentra.sap.document"].post_pending()
        self.env["rasentra.audit.event"].record("sap.post_run", "sap:pending", after=summary)
        return summary

    @api.model
    def check_sap(self):
        result = self.env["rasentra.sap.document"].check_health()
        self.env["rasentra.audit.event"].record("sap.connection_checked", "sap:instances", after=result)
        return result

    @api.model
    def open_action(self, name):
        """Tombol di halaman status membuka daftar standar Odoo."""
        xmlids = {
            "exceptions": "rasentra_sap_b1.action_integration_exception",
            "sap": "rasentra_sap_b1.action_sap_document",
            "sync_state": "rasentra_sync_central.action_sync_state",
            "inbox": "rasentra_sync_central.action_sync_inbox",
            "reconciliation": "rasentra_reconcile.action_day_reconciliation",
            "audit": "rasentra_core.action_audit_event",
        }
        if name not in xmlids:
            return False
        return self.env["ir.actions.act_window"]._for_xml_id(xmlids[name])
