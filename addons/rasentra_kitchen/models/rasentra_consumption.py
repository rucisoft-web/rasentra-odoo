from odoo import fields, models

REASONS = [("sale", "Penjualan"), ("complimentary", "Complimentary"), ("staff_meal", "Makan staf"),
           ("waste", "Waste"), ("remake", "Masak ulang")]


class RasentraConsumptionEvent(models.Model):
    """Pemakaian bahan per sumber (item dapur). Versi resep disimpan sehingga perubahan resep tidak
    menghitung ulang histori."""

    _name = "rasentra.consumption.event"
    _description = "Konsumsi bahan dapur"
    _order = "id desc"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, index=True)
    source_type = fields.Char(required=True)
    source_ref = fields.Char(required=True, index=True)
    recipe_version_id = fields.Many2one("rasentra.recipe.version", required=True)
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(digits=(18, 6), required=True)
    uom_id = fields.Many2one(related="product_id.uom_id")
    reason = fields.Selection(REASONS, required=True, default="sale")
    move_id = fields.Many2one("stock.move")
    occurred_at = fields.Datetime(default=fields.Datetime.now, required=True)
