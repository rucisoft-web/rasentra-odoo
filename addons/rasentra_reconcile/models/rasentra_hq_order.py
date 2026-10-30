import logging
from datetime import datetime

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import money, qty

_logger = logging.getLogger(__name__)

KINDS = [("sale", "Penjualan"), ("return", "Retur")]
REQUIRED = ("business_date", "gross_amount", "discount_amount", "net_amount")


def parse_time(value):
    """Waktu ISO 8601 dari payload outlet (UTC, akhiran Z) menjadi datetime naif UTC untuk Odoo."""
    if not value:
        return False
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


class RasentraHqOrder(models.Model):
    """Salinan konsolidasi penjualan outlet di Central (padanan hq_orders).

    Bukan pos.order karena Central tidak membuka sesi POS. Retur menjadi dokumen kind=return bernilai
    negatif pada tanggal bisnis retur, sehingga penjumlahan biasa langsung menghasilkan penjualan bersih.
    """

    _name = "rasentra.hq.order"
    _description = "Penjualan outlet (Central)"
    _order = "business_date desc, doc_no desc"
    _rec_name = "doc_no"

    uuid = fields.Char(required=True, readonly=True, index=True)
    inbox_id = fields.Many2one("rasentra.sync.inbox", readonly=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    company_id = fields.Many2one(related="outlet_id.company_id", store=True)
    doc_no = fields.Char(readonly=True, index=True)
    kind = fields.Selection(KINDS, default="sale", required=True, readonly=True, index=True)
    original_order_uuid = fields.Char(readonly=True)
    original_order_id = fields.Many2one("rasentra.hq.order", compute="_compute_original_order_id")
    channel = fields.Char(readonly=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    gross_amount = fields.Float(digits=(18, 2), readonly=True)
    discount_amount = fields.Float(digits=(18, 2), readonly=True)
    net_amount = fields.Float(digits=(18, 2), readonly=True)
    finalized_at = fields.Datetime(readonly=True)
    line_ids = fields.One2many("rasentra.hq.order.line", "order_id", readonly=True)
    discount_ids = fields.One2many("rasentra.hq.order.discount", "order_id", readonly=True)
    payment_ids = fields.One2many("rasentra.hq.order.payment", "order_id", readonly=True)

    _sql_constraints = [("uuid_unique", "unique(uuid)", "Dokumen outlet sudah diproyeksikan.")]

    def _compute_original_order_id(self):
        for order in self:
            order.original_order_id = order.original_order_uuid and self.search(
                [("uuid", "=", order.original_order_uuid)], limit=1
            )

    @api.model
    def _product(self, code):
        if not code:
            return self.env["product.product"]
        return self.env["product.product"].with_context(active_test=False).search(
            [("default_code", "=", code)], limit=1
        )

    @api.model
    def project(self, event):
        """Port SalesProjector::project. Idempoten per uuid dokumen, aman dijalankan ulang."""
        payload = dict(event.payload or {})
        payload.setdefault("id", event.entity_uuid)
        missing = [key for key in REQUIRED if payload.get(key) in (None, "")]
        if missing:
            # Event tetap diterima inbox; dokumen tanpa nilai tidak bisa masuk laporan penjualan.
            _logger.warning("Event %s tidak diproyeksikan, field kosong: %s", event.event_uuid, ", ".join(missing))
            return self.browse()
        if self.search_count([("uuid", "=", payload["id"])]):
            return self.browse()
        if event.event_type == "order.returned":
            return self._project_return(event, payload)
        lines, discounts = [], []
        for line in payload.get("lines") or []:
            lines.append(self._line_vals(line, sign=1))
            for discount in line.get("discounts") or []:
                discounts.append((0, 0, {
                    "line_no": line["line_no"],
                    "promotion_version_uuid": discount.get("promotion_version_id"),
                    "amount": float(money(discount["amount"])),
                    "funded_by": discount.get("funded_by") or "internal",
                }))
        payments = [
            (0, 0, {"method": p["method"], "amount": float(money(p["amount"]))})
            for p in payload.get("payments") or [] if (p.get("status") or "succeeded") == "succeeded"
        ]
        order = self.create({
            "uuid": payload["id"],
            "inbox_id": event.id,
            "outlet_id": event.outlet_id.id,
            "doc_no": payload.get("doc_no"),
            "channel": payload.get("channel"),
            "business_date": payload["business_date"],
            "gross_amount": float(money(payload["gross_amount"])),
            "discount_amount": float(money(payload["discount_amount"])),
            "net_amount": float(money(payload["net_amount"])),
            "finalized_at": parse_time(payload.get("finalized_at")) or event.create_date,
            "line_ids": lines,
            "discount_ids": discounts,
            "payment_ids": payments,
        })
        order._rasentra_after_project()
        return order

    def _project_return(self, event, payload):
        refund = payload.get("refund") or {}
        order = self.create({
            "uuid": payload["id"],
            "inbox_id": event.id,
            "outlet_id": event.outlet_id.id,
            "doc_no": payload.get("doc_no"),
            "kind": "return",
            "original_order_uuid": payload.get("original_order_id"),
            "channel": payload.get("channel"),
            "business_date": payload["business_date"],
            "gross_amount": float(-money(payload["gross_amount"])),
            "discount_amount": float(-money(payload["discount_amount"])),
            "net_amount": float(-money(payload["net_amount"])),
            "finalized_at": parse_time(payload.get("finalized_at")) or event.create_date,
            "line_ids": [self._line_vals(line, sign=-1) for line in payload.get("lines") or []],
            "payment_ids": [(0, 0, {"method": refund.get("method") or "cash",
                                    "amount": float(-money(refund.get("amount") or payload["net_amount"]))})],
        })
        order._rasentra_after_project()
        return order

    def _line_vals(self, line, sign):
        code = line.get("product_code") or line.get("product_id")
        return (0, 0, {
            "line_no": line["line_no"],
            "line_type": line.get("line_type"),
            "product_code": code,
            "product_id": self._product(code).id,
            "pack_code": line.get("pack_code") or line.get("pack_id"),
            "quantity": float(sign * qty(line["quantity"])),
            "uom": line.get("uom"),
            "gross_amount": float(sign * money(line["gross_amount"])),
            "discount_amount": float(sign * money(line["discount_amount"])),
            "net_amount": float(sign * money(line["net_amount"])),
            "disposition": line.get("disposition"),
        })

    def _rasentra_after_project(self):
        """Titik sambung modul lain (mis. antrean posting SAP)."""
        return True

    @api.model
    def rebuild(self):
        """Bangun ulang proyeksi dari inbox (padanan SalesProjector::rebuild)."""
        self.search([]).unlink()
        events = self.env["rasentra.sync.inbox"].search(
            [("event_type", "in", ("order.finalized", "order.returned"))], order="id"
        )
        for event in events:
            self.project(event)
        return len(events)


class RasentraHqOrderLine(models.Model):
    _name = "rasentra.hq.order.line"
    _description = "Baris penjualan outlet (Central)"
    _order = "order_id, line_no"

    order_id = fields.Many2one("rasentra.hq.order", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one(related="order_id.outlet_id", store=True)
    business_date = fields.Date(related="order_id.business_date", store=True)
    kind = fields.Selection(related="order_id.kind", store=True)
    channel = fields.Char(related="order_id.channel", store=True)
    line_no = fields.Integer()
    line_type = fields.Char()
    product_code = fields.Char(index=True)
    product_id = fields.Many2one("product.product")
    pack_code = fields.Char()
    quantity = fields.Float(digits=(18, 6))
    uom = fields.Char()
    gross_amount = fields.Float(digits=(18, 2))
    discount_amount = fields.Float(digits=(18, 2))
    net_amount = fields.Float(digits=(18, 2))
    disposition = fields.Char()


class RasentraHqOrderDiscount(models.Model):
    _name = "rasentra.hq.order.discount"
    _description = "Diskon promo per baris (Central)"

    order_id = fields.Many2one("rasentra.hq.order", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one(related="order_id.outlet_id", store=True)
    business_date = fields.Date(related="order_id.business_date", store=True)
    line_no = fields.Integer()
    promotion_version_uuid = fields.Char(index=True)
    promotion_version_id = fields.Many2one(
        "rasentra.promotion.version", compute="_compute_promotion_version_id", store=True
    )
    amount = fields.Float(digits=(18, 2))
    funded_by = fields.Char()

    @api.depends("promotion_version_uuid")
    def _compute_promotion_version_id(self):
        Version = self.env["rasentra.promotion.version"].sudo()
        for discount in self:
            discount.promotion_version_id = discount.promotion_version_uuid and Version.search(
                [("uuid", "=", discount.promotion_version_uuid)], limit=1
            )


class RasentraHqOrderPayment(models.Model):
    _name = "rasentra.hq.order.payment"
    _description = "Pembayaran penjualan outlet (Central)"

    order_id = fields.Many2one("rasentra.hq.order", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one(related="order_id.outlet_id", store=True)
    business_date = fields.Date(related="order_id.business_date", store=True)
    method = fields.Char(required=True)
    amount = fields.Float(digits=(18, 2))
