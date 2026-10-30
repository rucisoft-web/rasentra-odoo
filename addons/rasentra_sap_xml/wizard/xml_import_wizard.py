import base64

from odoo import _, fields, models

from odoo.addons.rasentra_core.tools import RasentraError


class RasentraXmlImportWizard(models.TransientModel):
    _name = "rasentra.xml.import.wizard"
    _description = "Unggah file NMEXML"

    kind = fields.Selection([("MSI", "MSI (invoice penjualan)"), ("MSR", "MSR (pembayaran pelanggan)")],
                            required=True, default="MSI")
    file = fields.Binary(required=True, attachment=False)
    file_name = fields.Char()

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise RasentraError("file_required", _("Pilih file XML."))
        batch = self.env["rasentra.xml.batch"].import_xml(base64.b64decode(self.file), self.file_name or "upload.xml",
                                                          self.kind)
        return {"type": "ir.actions.act_window", "res_model": batch._name, "res_id": batch.id, "view_mode": "form"}
