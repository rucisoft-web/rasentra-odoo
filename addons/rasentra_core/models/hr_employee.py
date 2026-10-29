from odoo import api, fields, models

from ..tools import uuid7

RASENTRA_ROLES = [
    ("admin", "Admin pusat"),
    ("outlet_head", "Kepala outlet"),
    ("cashier", "Kasir"),
    ("waiter", "Pelayan"),
    ("chef", "Chef / dapur"),
    ("warehouse", "Petugas gudang"),
    ("counter", "Petugas opname"),
]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    rasentra_role = fields.Selection(RASENTRA_ROLES, string="Peran Rasentra")
    rasentra_outlet_id = fields.Many2one("rasentra.outlet", string="Outlet Rasentra", index=True)
    rasentra_uuid = fields.Char(string="UUID Rasentra", copy=False, index=True, readonly=True)
    approval_limit = fields.Monetary(
        string="Limit approval", currency_field="currency_id", help="Nominal maksimum yang boleh disetujui."
    )

    _sql_constraints = [("rasentra_uuid_unique", "unique(rasentra_uuid)", "UUID Rasentra karyawan harus unik.")]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("rasentra_role") and not vals.get("rasentra_uuid"):
                vals["rasentra_uuid"] = uuid7()
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if vals.get("rasentra_role"):
            for employee in self.filtered(lambda e: not e.rasentra_uuid):
                employee.rasentra_uuid = uuid7()
        return res
