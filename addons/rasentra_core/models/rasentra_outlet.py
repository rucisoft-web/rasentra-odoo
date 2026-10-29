from odoo import api, fields, models

from odoo.addons.base.models.res_partner import _tz_get


class RasentraOutlet(models.Model):
    _name = "rasentra.outlet"
    _description = "Outlet Rasentra"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "code"

    code = fields.Char(required=True, tracking=True)
    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    region_id = fields.Many2one("rasentra.region", required=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Gudang Odoo")
    sap_warehouse_code = fields.Char(string="Kode gudang SAP")
    tz = fields.Selection(_tz_get, string="Zona waktu", required=True, default="Asia/Jakarta")
    retail_name = fields.Char(string="Nama retail")
    restaurant_name = fields.Char(string="Nama restoran")
    has_retail = fields.Boolean(default=True)
    has_restaurant = fields.Boolean()
    has_cooking_fee = fields.Boolean()
    active = fields.Boolean(default=True, tracking=True)
    location_ids = fields.One2many("stock.location", "rasentra_outlet_id", string="Lokasi")
    device_ids = fields.One2many("rasentra.device", "outlet_id", string="Perangkat")

    _sql_constraints = [("code_unique", "unique(code)", "Kode outlet harus unik.")]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for outlet in self:
            outlet.display_name = f"[{outlet.code}] {outlet.name}" if outlet.code else outlet.name
