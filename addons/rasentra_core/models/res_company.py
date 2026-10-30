from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    rasentra_legal_name = fields.Char(string="Nama legal")
    sap_company_db = fields.Char(
        string="Instance SAP B1", help="Company database SAP B1 milik CV ini, mis. sap_solo atau sap_lombok."
    )
