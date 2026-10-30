from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, qty

ADJUSTMENT_KINDS = [
    ("waste", "Waste"),
    ("count", "Opname"),
    ("release", "Lepas karantina"),
    ("production", "Produksi"),
]
DOC_PREFIX = {"waste": "W", "count": "OP", "release": "RL", "production": "PR"}
STOCK_STATES = [("available", "Stok jual"), ("quarantine", "Karantina")]


class RasentraStockAdjustment(models.Model):
    """Dokumen penyesuaian stok Lokal (padanan stock_adjustments). Dikirim ke Central sebagai
    event `stock.adjusted` lalu menjadi Goods Issue / Goods Receipt di SAP."""

    _name = "rasentra.stock.adjustment"
    _description = "Penyesuaian stok Rasentra"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "id desc"
    _rec_name = "doc_no"

    doc_no = fields.Char(required=True, readonly=True, index=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    kind = fields.Selection(ADJUSTMENT_KINDS, required=True, readonly=True)
    reason = fields.Char(readonly=True)
    source_type = fields.Char(readonly=True)
    source_ref = fields.Char(readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Petugas", readonly=True)
    approver_id = fields.Many2one("hr.employee", string="Disetujui", readonly=True)
    business_date = fields.Date(required=True, readonly=True)
    line_ids = fields.One2many("rasentra.stock.adjustment.line", "adjustment_id", readonly=True)
    move_ids = fields.Many2many("stock.move", string="Pergerakan stok", readonly=True)

    _sql_constraints = [("doc_no_unique", "unique(doc_no)", "Nomor dokumen penyesuaian harus unik.")]

    @api.model
    def record(self, kind, outlet, lines, employee=None, approver=None, reason=None, source_type=None, source_ref=None):
        """Catat dokumen untuk pergerakan yang dibukukan pemanggil (port StockAdjustmentService::record).

        `lines`: list dict product, quantity, pack (stock.lot | None), from_state, to_state.
        """
        if not lines:
            return self.browse()
        self.env.cr.execute("SELECT id FROM rasentra_outlet WHERE id = %s FOR UPDATE", [outlet.id])
        business_date = outlet.business_date()
        adjustment = self.sudo().create(
            {
                "doc_no": self._next_doc_no(outlet, kind, business_date),
                "outlet_id": outlet.id,
                "kind": kind,
                "reason": reason,
                "source_type": source_type,
                "source_ref": source_ref,
                "employee_id": employee.id if employee else False,
                "approver_id": approver.id if approver else False,
                "business_date": business_date,
                "line_ids": [
                    (0, 0, {
                        "line_no": no,
                        "product_id": line["product"].id,
                        "lot_id": line["pack"].id if line.get("pack") else False,
                        "quantity": float(abs(qty(line["quantity"]))),
                        "from_state": line.get("from_state") or False,
                        "to_state": line.get("to_state") or False,
                    })
                    for no, line in enumerate(lines, start=1)
                ],
            }
        )
        self.env["rasentra.sync.outbox"].record(
            "stock_adjustment", adjustment.uuid, "stock.adjusted", adjustment._payload(), business_date, outlet=outlet
        )
        return adjustment

    def _payload(self):
        self.ensure_one()
        return {
            "id": self.uuid,
            "doc_no": self.doc_no,
            "outlet_id": self.outlet_id.code,
            "kind": self.kind,
            "reason": self.reason,
            "source": {"type": self.source_type, "id": self.source_ref} if self.source_type else None,
            "business_date": fields.Date.to_string(self.business_date),
            "lines": [
                {
                    "line_no": line.line_no,
                    "product_id": line.product_id.default_code,
                    "product_code": line.product_id.default_code,
                    "pack_id": line.lot_id.name or None,
                    "quantity": str(qty(line.quantity)),
                    "uom": line.product_id.uom_id.name,
                    "from_state": line.from_state or None,
                    "to_state": line.to_state or None,
                }
                for line in self.line_ids
            ],
        }

    def _next_doc_no(self, outlet, kind, business_date):
        prefix = f"{outlet.code}-{DOC_PREFIX[kind]}{business_date:%y%m%d}-"
        last = self.sudo().search([("doc_no", "=like", prefix + "%")], order="doc_no desc", limit=1)
        seq = int(last.doc_no[len(prefix):]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def write(self, vals):
        if set(vals) - {"move_ids"}:
            raise RasentraError("adjustment_immutable", _("Dokumen penyesuaian tidak bisa diubah."))
        return super().write(vals)


class RasentraStockAdjustmentLine(models.Model):
    _name = "rasentra.stock.adjustment.line"
    _description = "Baris penyesuaian stok"
    _order = "adjustment_id, line_no"

    adjustment_id = fields.Many2one("rasentra.stock.adjustment", required=True, ondelete="cascade", index=True)
    line_no = fields.Integer(required=True)
    product_id = fields.Many2one("product.product", required=True)
    lot_id = fields.Many2one("stock.lot", string="Pack ID")
    quantity = fields.Float(digits=(18, 6), required=True)
    uom_id = fields.Many2one(related="product_id.uom_id")
    from_state = fields.Selection(STOCK_STATES, string="Dari")
    to_state = fields.Selection(STOCK_STATES, string="Ke")
