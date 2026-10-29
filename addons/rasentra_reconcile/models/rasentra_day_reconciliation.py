from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import money

from .rasentra_hq_order import parse_time

STATUSES = [("waiting", "Menunggu struk"), ("matched", "Cocok"), ("mismatch", "Tidak cocok")]


class RasentraDayReconciliation(models.Model):
    """Port DayReconciler: ringkasan tutup hari Lokal dicocokkan dengan rasentra.hq.order.

    "waiting" berarti masih ada struk yang belum sampai (outlet sempat offline); statusnya diperiksa
    ulang setiap struk outlet itu masuk dan tiap jam.
    """

    _name = "rasentra.day.reconciliation"
    _description = "Rekonsiliasi tutup hari"
    _order = "business_date desc, outlet_id"
    _rec_name = "business_date"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    closing_version = fields.Integer(readonly=True)
    closed_at = fields.Datetime(readonly=True)
    local_orders = fields.Integer(string="Struk Lokal", readonly=True)
    local_net = fields.Float(string="Bersih Lokal", digits=(18, 2), readonly=True)
    local_returns = fields.Integer(string="Retur Lokal", readonly=True)
    local_returns_net = fields.Float(string="Retur bersih Lokal", digits=(18, 2), readonly=True)
    cash_difference = fields.Float(string="Selisih kas", digits=(18, 2), readonly=True)
    shifts = fields.Integer(readonly=True)
    open_shifts = fields.Integer(readonly=True)
    local_summary = fields.Json(readonly=True)
    central_orders = fields.Integer(string="Struk Central", readonly=True)
    central_net = fields.Float(string="Bersih Central", digits=(18, 2), readonly=True)
    missing_doc_nos = fields.Json(string="Belum sampai", readonly=True)
    extra_doc_nos = fields.Json(string="Tidak ada di Lokal", readonly=True)
    missing_count = fields.Integer(compute="_compute_counts")
    extra_count = fields.Integer(compute="_compute_counts")
    status = fields.Selection(STATUSES, default="waiting", required=True, readonly=True, index=True)
    checked_at = fields.Datetime(readonly=True)

    _sql_constraints = [("outlet_date_unique", "unique(outlet_id, business_date)", "Rekonsiliasi sudah ada.")]

    @api.depends("missing_doc_nos", "extra_doc_nos")
    def _compute_counts(self):
        for row in self:
            row.missing_count = len(row.missing_doc_nos or [])
            row.extra_count = len(row.extra_doc_nos or [])

    @api.model
    def record(self, event):
        payload = event.payload
        existing = self.search(
            [("outlet_id", "=", event.outlet_id.id), ("business_date", "=", payload["business_date"])], limit=1
        )
        if existing and existing.closing_version > event.entity_version:
            return existing  # versi tutup hari yang lebih lama datang terlambat
        vals = {
            "closing_version": event.entity_version,
            "closed_at": parse_time(payload.get("closed_at")),
            "local_orders": payload["orders"],
            "local_net": float(money(payload["net_amount"])),
            "local_returns": payload.get("returns") or 0,
            "local_returns_net": float(money(payload.get("returns_net_amount") or 0)),
            "cash_difference": float(money(payload.get("cash_difference") or 0)),
            "shifts": len(payload.get("shifts") or []),
            "open_shifts": payload.get("open_shifts") or 0,
            "local_summary": payload,
        }
        row = existing or self.create(
            {"outlet_id": event.outlet_id.id, "business_date": payload["business_date"], **vals}
        )
        if existing:
            row.write(vals)
        return row.check()

    def check(self):
        Order = self.env["rasentra.hq.order"]
        for row in self:
            docs = Order.search([("outlet_id", "=", row.outlet_id.id), ("business_date", "=", row.business_date)])
            sales = docs.filtered(lambda o: o.kind == "sale")
            returns = docs - sales
            summary = row.local_summary or {}
            # Struk dan dokumen retur dicocokkan bersama: keduanya harus sampai di Central.
            local_docs = list(summary.get("doc_nos") or []) + list(summary.get("return_doc_nos") or [])
            central_docs = [d for d in docs.mapped("doc_no") if d]
            missing = [d for d in local_docs if d not in central_docs]
            extra = [d for d in central_docs if d not in local_docs]
            central_net = sum((money(o.net_amount) for o in sales), money(0))
            # Retur disimpan negatif di Central; ringkasan Lokal mengirim nilai positif.
            returns_net = -sum((money(o.net_amount) for o in returns), money(0))
            same = (
                len(sales) == row.local_orders and central_net == money(row.local_net)
                and len(returns) == row.local_returns and returns_net == money(row.local_returns_net)
            )
            row.write({
                "central_orders": len(sales),
                "central_net": float(central_net),
                "missing_doc_nos": missing,
                "extra_doc_nos": extra,
                "status": "waiting" if missing else ("matched" if not extra and same else "mismatch"),
                "checked_at": fields.Datetime.now(),
            })
        return self

    @api.model
    def on_document(self, order):
        """Struk/retur baru masuk: periksa ulang rekonsiliasi tanggalnya bila belum cocok."""
        open_rows = self.search([
            ("outlet_id", "=", order.outlet_id.id), ("business_date", "=", order.business_date),
            ("status", "!=", "matched"),
        ])
        open_rows.check()

    def action_recheck(self):
        self.check()
        return True

    @api.model
    def _cron_recheck(self):
        self.search([("status", "!=", "matched")]).check()
