from odoo import models

from odoo.addons.rasentra_core.tools import RasentraError


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _add_missing_products(self, products, config_id, data):
        """Produk baris diskon promo selalu dimuat, juga saat POS membatasi kategori produk."""
        super()._add_missing_products(products, config_id, data)
        promo = self.env.ref("rasentra_pos_meatshop.product_promo_discount", raise_if_not_found=False)
        if promo and promo.id not in {p["id"] for p in products}:
            products.extend(self._load_product_with_domain([("id", "=", promo.id)], config_id))

    def _process_pos_ui_product_product(self, products, config_id):
        """Harga di POS diambil dari versi harga Rasentra yang berlaku untuk outlet dan kanal kasir."""
        super()._process_pos_ui_product_product(products, config_id)
        config = config_id if isinstance(config_id, models.BaseModel) else self.env["pos.config"].browse(config_id)
        outlet = config.rasentra_outlet_id
        if not outlet:
            return
        Price = self.env["rasentra.price.version"].sudo()
        by_id = {p.id: p for p in self.browse([p["id"] for p in products])}
        for data in products:
            product = by_id[data["id"]]
            if not product.rasentra_type:
                continue
            try:
                price, _version = Price.resolve(product, outlet, config.rasentra_channel)
            except RasentraError:
                continue
            data["lst_price"] = float(price)
