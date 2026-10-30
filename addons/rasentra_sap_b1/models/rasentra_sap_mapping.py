from odoo import api, fields, models

ENTITY_TYPES = [
    ("product", "Produk (kode produk)"),
    ("outlet", "Gudang outlet (kode outlet)"),
    ("customer", "Pelanggan (walk_in)"),
    ("payment_method", "Metode bayar (cash, qris, ...)"),
    ("account", "Akun penyesuaian stok (waste, count, production)"),
]


class RasentraSapMapping(models.Model):
    """Mapping kode Rasentra ke kode SAP per instance (sap_solo, sap_lombok, ...)."""

    _name = "rasentra.sap.mapping"
    _description = "Mapping SAP"
    _order = "company_db, entity_type, entity_key"

    company_db = fields.Char(required=True, index=True)
    entity_type = fields.Selection(ENTITY_TYPES, required=True, index=True)
    entity_key = fields.Char(required=True, index=True)
    sap_code = fields.Char(required=True)
    tax_code = fields.Char()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("mapping_unique", "unique(company_db, entity_type, entity_key)", "Mapping sudah ada untuk instance ini."),
    ]

    @api.model
    def lookup(self, company_db, entity_type, key):
        return self.search([("company_db", "=", company_db), ("entity_type", "=", entity_type),
                            ("entity_key", "=", str(key))], limit=1)
