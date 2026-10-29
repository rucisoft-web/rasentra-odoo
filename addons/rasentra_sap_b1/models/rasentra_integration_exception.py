from odoo import api, fields, models


class RasentraIntegrationException(models.Model):
    """Pengecualian integrasi (mis. mapping SAP kosong) yang perlu ditangani manusia.

    Satu catatan terbuka per (jenis, sumber), agar posting berkala tidak menumpuk duplikat.
    """

    _name = "rasentra.integration.exception"
    _description = "Pengecualian integrasi"
    _order = "id desc"

    kind = fields.Char(required=True, index=True)
    source_type = fields.Char(required=True)
    source_uuid = fields.Char(required=True, index=True)
    company_db = fields.Char()
    message = fields.Text()
    status = fields.Selection([("open", "Terbuka"), ("resolved", "Selesai")], default="open", required=True,
                              index=True)
    resolved_by = fields.Many2one("res.users", readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    @api.model
    def raise_open(self, kind, source_type, source_uuid, message, company_db=None):
        existing = self.search([("kind", "=", kind), ("source_type", "=", source_type),
                                ("source_uuid", "=", source_uuid), ("status", "=", "open")], limit=1)
        if existing:
            existing.message = message
            return existing
        return self.create({"kind": kind, "source_type": source_type, "source_uuid": source_uuid,
                            "message": message, "company_db": company_db})

    def action_resolve(self):
        self.write({"status": "resolved", "resolved_by": self.env.uid, "resolved_at": fields.Datetime.now()})
        return True
