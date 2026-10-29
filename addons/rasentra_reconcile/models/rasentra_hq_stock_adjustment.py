from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import qty


ADJUSTMENT_KINDS = [("waste", "Waste"), ("count", "Opname"), ("release", "Lepas karantina"), ("production", "Produksi")]


class RasentraHqStockAdjustment(models.Model):
    """Proyeksi event stock.adjusted di Central (port StockProjector): laporan waste, selisih opname dan
    produksi dapur per outlet. Idempoten per uuid dokumen."""

    _name = "rasentra.hq.stock.adjustment"
    _description = "Penyesuaian stok outlet (Central)"
    _order = "business_date desc, doc_no desc"
    _rec_name = "doc_no"

    uuid = fields.Char(required=True, readonly=True, index=True)
    inbox_id = fields.Many2one("rasentra.sync.inbox", readonly=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    company_id = fields.Many2one(related="outlet_id.company_id", store=True)
    doc_no = fields.Char(readonly=True, index=True)
    kind = fields.Selection(ADJUSTMENT_KINDS, required=True, readonly=True, index=True)
    reason = fields.Char(readonly=True)
    source_type = fields.Char(readonly=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    line_ids = fields.One2many("rasentra.hq.stock.adjustment.line", "adjustment_id", readonly=True)

    _sql_constraints = [("uuid_unique", "unique(uuid)", "Dokumen penyesuaian sudah diproyeksikan.")]

    @api.model
    def project(self, event):
        payload = dict(event.payload or {})
        payload.setdefault("id", event.entity_uuid)
        if self.search_count([("uuid", "=", payload["id"])]):
            return self.browse()
        outlet = self.env["rasentra.outlet"].sudo().search([("code", "=", payload["outlet_id"])], limit=1)
        Product = self.env["product.product"].with_context(active_test=False)
        lines = []
        for line in payload.get("lines") or []:
            amount = qty(line["quantity"])
            # Kuantitas bertanda: keluar dari stok negatif, masuk positif (lepas karantina = 0 bersih).
            sign = -1 if line.get("to_state") is None else (1 if line.get("from_state") is None else 0)
            lines.append((0, 0, {
                "line_no": line["line_no"],
                "product_code": line.get("product_code") or line.get("product_id"),
                "product_id": Product.search([("default_code", "=", line.get("product_code") or line.get("product_id"))], limit=1).id,
                "pack_code": line.get("pack_id"),
                "quantity": float(amount),
                "signed_quantity": float(amount) * sign,
                "uom": line.get("uom"),
                "from_state": line.get("from_state"),
                "to_state": line.get("to_state"),
            }))
        return self.create({
            "uuid": payload["id"],
            "inbox_id": event.id,
            "outlet_id": outlet.id,
            "doc_no": payload.get("doc_no"),
            "kind": payload["kind"],
            "reason": payload.get("reason"),
            "source_type": (payload.get("source") or {}).get("type"),
            "business_date": payload["business_date"],
            "line_ids": lines,
        })


class RasentraHqStockAdjustmentLine(models.Model):
    _name = "rasentra.hq.stock.adjustment.line"
    _description = "Baris penyesuaian stok outlet (Central)"
    _order = "adjustment_id, line_no"

    adjustment_id = fields.Many2one("rasentra.hq.stock.adjustment", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one(related="adjustment_id.outlet_id", store=True)
    business_date = fields.Date(related="adjustment_id.business_date", store=True)
    kind = fields.Selection(related="adjustment_id.kind", store=True)
    line_no = fields.Integer()
    product_code = fields.Char()
    product_id = fields.Many2one("product.product")
    pack_code = fields.Char()
    quantity = fields.Float(digits=(18, 6))
    signed_quantity = fields.Float(digits=(18, 6), string="Kuantitas bertanda")
    uom = fields.Char()
    from_state = fields.Char()
    to_state = fields.Char()
