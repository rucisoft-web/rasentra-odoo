import uuid
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import money

PAID_STATES = ("paid", "done", "invoiced")


class RasentraOutlet(models.Model):
    """Rasentra Lokal: tutup hari bisnis (port DayCloser).

    Ringkasan struk, retur, dan kas shift dikirim ke Central lewat outbox (business_day.closed)
    agar Central bisa mencocokkan dengan transaksi yang sudah diterimanya. Boleh dijalankan
    ulang; versi berikutnya menggantikan yang lama.
    """

    _inherit = "rasentra.outlet"

    def rasentra_day_summary(self, business_date):
        self.ensure_one()
        business_date = fields.Date.to_date(business_date)
        orders = self.env["pos.order"].sudo().search([
            ("rasentra_outlet_id", "=", self.id), ("rasentra_business_date", "=", business_date),
            ("rasentra_doc_no", "!=", False), ("state", "in", PAID_STATES),
        ], order="rasentra_doc_no")
        sales = orders.filtered(lambda o: not o._rasentra_is_return())
        # Retur dicatat pada tanggal bisnis saat retur dibuat, bukan tanggal struk asalnya.
        returns = self.env["rasentra.sales.return"].sudo().search([
            ("outlet_id", "=", self.id), ("business_date", "=", business_date), ("state", "=", "done"),
        ], order="doc_no")
        sessions = self.env["pos.session"].sudo().search([
            ("rasentra_outlet_id", "=", self.id), ("rasentra_business_date", "=", business_date),
        ])

        def total(records, field):
            return money(sum((money(r[field]) for r in records), money(0)))

        by_channel, payments, refunds = {}, {}, {}
        for order in sales:
            row = by_channel.setdefault(order.rasentra_channel, {"orders": 0, "net_amount": money(0)})
            row["orders"] += 1
            row["net_amount"] += money(order.rasentra_net_amount)
            for payment in order.payment_ids:
                code = payment.payment_method_id._rasentra_code()
                payments[code] = payments.get(code, money(0)) + money(payment.amount)
        for ret in returns:
            refunds[ret.refund_method] = refunds.get(ret.refund_method, money(0)) + money(ret.net_amount)
        closed = sessions.filtered(lambda s: s.rasentra_closing_expected)
        return {
            "outlet_code": self.code,
            "business_date": fields.Date.to_string(business_date),
            "closed_at": fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orders": len(sales),
            "gross_amount": str(total(sales, "rasentra_gross_amount")),
            "discount_amount": str(total(sales, "rasentra_discount_amount")),
            "net_amount": str(total(sales, "rasentra_net_amount")),
            "by_channel": {k: {"orders": v["orders"], "net_amount": str(money(v["net_amount"]))}
                           for k, v in by_channel.items()},
            "payments": {k: str(money(v)) for k, v in payments.items()},
            "doc_nos": sales.mapped("rasentra_doc_no"),
            "returns": len(returns),
            "returns_net_amount": str(total(returns, "net_amount")),
            "refunds": {k: str(money(v)) for k, v in refunds.items()},
            "return_doc_nos": returns.mapped("doc_no"),
            "shifts": [
                {"id": s.name, "user_id": s.user_id.login, "status": "closed" if s.rasentra_closing_expected else "open",
                 "cash_difference": str(money(s.rasentra_cash_difference)) if s.rasentra_closing_expected else None}
                for s in sessions
            ],
            "cash_difference": str(total(closed, "rasentra_cash_difference")),
            "open_shifts": len(sessions - closed),
        }

    def _business_day_uuid(self, business_date):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rasentra:business_day:{self.code}:{business_date}"))

    def rasentra_close_day(self, business_date):
        self.ensure_one()
        payload = self.rasentra_day_summary(business_date)
        entity = self._business_day_uuid(payload["business_date"])
        Outbox = self.env["rasentra.sync.outbox"].sudo()
        last = Outbox.search([("entity_type", "=", "business_day"), ("entity_uuid", "=", entity)],
                             order="entity_version desc", limit=1)
        event = Outbox.record("business_day", entity, "business_day.closed", payload, payload["business_date"],
                              entity_version=(last.entity_version or 0) + 1, outlet=self)
        self.env["rasentra.audit.event"].sudo().record(
            "business_day.closed", f"business_day:{self.code}:{payload['business_date']}", outlet=self,
            amount=money(payload["net_amount"]),
            after={"orders": payload["orders"], "cash_difference": payload["cash_difference"],
                   "version": event.entity_version},
        )
        return event

    @api.model
    def _cron_close_previous_day(self):
        """Dijalankan 04.00: tutup hari bisnis kemarin untuk outlet yang punya kasir di instalasi ini."""
        outlets = self.env["pos.config"].sudo().search([("rasentra_outlet_id", "!=", False)]).rasentra_outlet_id
        for outlet in outlets:
            outlet.rasentra_close_day(outlet.business_date() - timedelta(days=1))
