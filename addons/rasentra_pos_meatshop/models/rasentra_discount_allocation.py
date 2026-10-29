from odoo import fields, models


class RasentraDiscountAllocation(models.Model):
    """Diskon promo per baris (padanan discount_allocations), sumber retur, laporan promo dan SAP."""

    _name = "rasentra.discount.allocation"
    _description = "Alokasi diskon promo"

    line_id = fields.Many2one("pos.order.line", required=True, ondelete="cascade", index=True)
    order_id = fields.Many2one(related="line_id.order_id", store=True)
    promotion_version_uuid = fields.Char(required=True, index=True)
    promotion_version_id = fields.Many2one("rasentra.promotion.version", compute="_compute_version")
    amount = fields.Float(digits=(18, 2), required=True)
    funded_by = fields.Char(required=True, default="internal")

    def _compute_version(self):
        Version = self.env["rasentra.promotion.version"].sudo()
        for allocation in self:
            allocation.promotion_version_id = Version.search(
                [("uuid", "=", allocation.promotion_version_uuid)], limit=1
            )
