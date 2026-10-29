from odoo import fields, models


class RasentraRegion(models.Model):
    _name = "rasentra.region"
    _description = "Wilayah Rasentra"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    outlet_ids = fields.One2many("rasentra.outlet", "region_id")

    _sql_constraints = [("code_unique", "unique(code)", "Kode wilayah harus unik.")]
