from odoo import fields, models

from odoo.addons.rasentra_core.models.rasentra_price_version import CHANNELS


class PosConfig(models.Model):
    _inherit = "pos.config"

    rasentra_outlet_id = fields.Many2one("rasentra.outlet", string="Outlet Rasentra")
    rasentra_channel = fields.Selection(CHANNELS, string="Kanal Rasentra", default="retail")

    def _get_special_products(self):
        # Baris diskon promo dibuat oleh POS saat bayar, tidak dipilih kasir dari daftar produk.
        promo = self.env.ref("rasentra_pos_meatshop.product_promo_discount", raise_if_not_found=False)
        return super()._get_special_products() | (promo or self.env["product.product"])
