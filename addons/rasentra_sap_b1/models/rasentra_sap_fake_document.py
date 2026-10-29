from odoo import api, fields, models


class RasentraSapFakeDocument(models.Model):
    """Isi SAP tiruan (mode simulasi) untuk uji dan demo tanpa server SAP."""

    _name = "rasentra.sap.fake.document"
    _description = "Dokumen SAP simulasi"
    _order = "id desc"

    company_db = fields.Char(required=True, index=True)
    sap_object = fields.Char(required=True, index=True)
    source_ref = fields.Char(required=True, index=True)
    doc_entry = fields.Integer(readonly=True)
    doc_num = fields.Integer(readonly=True)
    doc_total = fields.Char()
    payload = fields.Json()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.write({"doc_entry": 1000 + record.id, "doc_num": 51000 + record.id})
        return records
