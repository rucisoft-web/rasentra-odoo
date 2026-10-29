from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import money

GROUP_TZ = "Asia/Jakarta"


class RasentraDashboard(models.AbstractModel):
    """Dashboard grup (port DashboardController): angka dari proyeksi rasentra.hq.order di Central."""

    _name = "rasentra.dashboard"
    _description = "Dashboard Rasentra"

    @api.model
    def _today(self):
        return datetime.now(pytz.timezone(GROUP_TZ)).date()

    @api.model
    def _aggregate(self, orders, key):
        out = defaultdict(lambda: {"net": 0.0, "orders": 0, "returns": 0.0})
        for order in orders:
            # Retur tersimpan dengan nilai negatif, jadi bersih = jumlah semua net_amount.
            row = out[key(order)]
            row["net"] += order.net_amount
            if order.kind == "sale":
                row["orders"] += 1
            else:
                row["returns"] += abs(order.net_amount)
        return out

    @api.model
    def summary(self, day=None):
        today = fields.Date.to_date(day) if day else self._today()
        week_start = today - timedelta(days=6)
        Order = self.env["rasentra.hq.order"].sudo()
        week_orders = Order.search([("business_date", ">=", week_start), ("business_date", "<=", today)])
        day_orders = week_orders.filtered(lambda o: o.business_date == today)

        totals = self._aggregate(day_orders, lambda o: "all")["all"]
        week_totals = self._aggregate(week_orders, lambda o: "all")["all"]
        by_day = self._aggregate(week_orders, lambda o: o.business_date)
        by_outlet = self._aggregate(day_orders, lambda o: o.outlet_id.id)
        by_channel = self._aggregate(day_orders, lambda o: o.channel or "lainnya")
        health = {row["id"]: row for row in self.env["rasentra.monitor"]._outlets(fields.Datetime.now())}

        outlets = []
        for outlet in self.env["rasentra.outlet"].sudo().search([("active", "=", True)], order="company_id, code"):
            sales = by_outlet.get(outlet.id, {"net": 0.0, "orders": 0, "returns": 0.0})
            info = health.get(outlet.id, {})
            outlets.append({
                "id": outlet.id, "code": outlet.code, "name": outlet.name, "company_id": outlet.company_id.id,
                "net": str(money(sales["net"])), "orders": sales["orders"],
                "health": info.get("health", "none"), "health_label": info.get("health_label"),
                "outbox": (info.get("outbox_pending") or 0) + (info.get("outbox_failed") or 0),
                "parked": info.get("outbox_parked") or 0,
            })

        Sap = self.env["rasentra.sap.document"].sudo()
        companies = []
        for company in self.env["res.company"].sudo().search([], order="id"):
            rows = [o for o in outlets if o["company_id"] == company.id]
            if not rows:
                continue
            sap = {g["status"]: g["status_count"] for g in Sap.read_group(
                [("company_db", "=", company.sap_company_db)], ["status"], ["status"])} if company.sap_company_db else {}
            companies.append({
                "id": company.id, "name": company.name, "sap_company_db": company.sap_company_db or None,
                "net": str(money(sum(float(o["net"]) for o in rows))), "orders": sum(o["orders"] for o in rows),
                "outlets": rows, "sap": sap,
            })

        days = []
        for offset in range(7):
            date = week_start + timedelta(days=offset)
            row = by_day.get(date, {"net": 0.0, "orders": 0})
            days.append({"date": fields.Date.to_string(date), "net": str(money(row["net"])), "orders": row["orders"]})

        Version = self.env["rasentra.promotion.version"].sudo()
        promo_drafts = [{"id": v.id, "name": v.name, "version": v.version, "state": v.state}
                        for v in Version.search([("state", "in", ("draft", "simulated"))], order="id desc", limit=5)]
        return {
            "today": fields.Date.to_string(today),
            "totals": {"net": str(money(totals["net"])), "orders": totals["orders"],
                       "returns": str(money(totals["returns"])),
                       "avg": str(money(totals["net"] / totals["orders"])) if totals["orders"] else "0.00"},
            "week": {"net": str(money(week_totals["net"])), "orders": week_totals["orders"]},
            "days": days,
            "channels": [{"channel": k, "net": str(money(v["net"])), "orders": v["orders"]}
                         for k, v in sorted(by_channel.items())],
            "companies": companies,
            "sap": {g["status"]: g["status_count"] for g in Sap.read_group([], ["status"], ["status"])},
            "exceptions": self.env["rasentra.integration.exception"].sudo().search_count([("status", "=", "open")]),
            "promo_drafts": promo_drafts,
            "price_drafts": self.env["rasentra.price.version"].sudo().search_count([("state", "=", "draft")]),
            "pending_receipts": self.env["rasentra.promotion.target"].sudo().search_count([("ack_status", "=", "pending")]),
        }
