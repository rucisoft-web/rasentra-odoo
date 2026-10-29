from odoo import fields, models

KITCHEN_STATIONS = [
    ("grill", "Grill"),
    ("hot", "Hot kitchen"),
    ("cold", "Cold kitchen"),
    ("bar", "Bar"),
    ("pastry", "Pastry"),
    ("packing", "Packing"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    rasentra_type = fields.Selection(
        [
            ("retail", "Barang retail"),
            ("meat_pack", "Daging ber-Pack ID"),
            ("menu", "Menu restoran"),
            ("service", "Jasa (cooking fee)"),
            ("ingredient", "Bahan"),
        ],
        string="Jenis Rasentra",
    )
    kitchen_station = fields.Selection(KITCHEN_STATIONS, string="Station dapur")
