import pytz

from odoo import api, fields, models

from odoo.addons.base.models.res_partner import _tz_get


class RasentraOutlet(models.Model):
    _name = "rasentra.outlet"
    _description = "Outlet Rasentra"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "code"

    code = fields.Char(required=True, tracking=True, string="Kode")
    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="Perusahaan (CV)", required=True, default=lambda self: self.env.company
    )
    region_id = fields.Many2one("rasentra.region", required=True, string="Wilayah")
    warehouse_id = fields.Many2one("stock.warehouse", string="Gudang Odoo")
    sap_warehouse_code = fields.Char(string="Kode gudang SAP")
    tz = fields.Selection(_tz_get, string="Zona waktu", required=True, default="Asia/Jakarta")
    retail_name = fields.Char(string="Nama retail")
    restaurant_name = fields.Char(string="Nama restoran")
    has_retail = fields.Boolean(default=True, string="Kanal retail")
    has_restaurant = fields.Boolean(string="Kanal restoran")
    has_cooking_fee = fields.Boolean(string="Layanan masak (cooking fee)")
    active = fields.Boolean(default=True, tracking=True)
    location_ids = fields.One2many("stock.location", "rasentra_outlet_id", string="Lokasi")
    device_ids = fields.One2many("rasentra.device", "outlet_id", string="Perangkat")

    _sql_constraints = [("code_unique", "unique(code)", "Kode outlet harus unik.")]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for outlet in self:
            outlet.display_name = f"[{outlet.code}] {outlet.name}" if outlet.code else outlet.name

    def business_date(self, at=None):
        """Tanggal bisnis menurut zona waktu outlet (padanan Outlet::businessDate)."""
        self.ensure_one()
        at = at or fields.Datetime.now()
        return pytz.utc.localize(at).astimezone(pytz.timezone(self.tz or "Asia/Jakarta")).date()
