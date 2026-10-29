from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    rasentra_outlet_id = fields.Many2one("rasentra.outlet", string="Outlet Rasentra", index=True)
    rasentra_type = fields.Selection(
        [
            ("stock", "Stok jual"),
            ("chiller", "Chiller"),
            ("quarantine", "Karantina"),
            ("transit", "Transit"),
            ("kitchen", "Dapur"),
        ],
        string="Jenis lokasi Rasentra",
    )
