import base64
import hashlib
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .importers import IMPORTERS, SELECTION, read_csv

MAX_ERRORS = 200


class RasentraMigrationBatch(models.Model):
    _name = "rasentra.migration.batch"
    _description = "Impor data awal migrasi (CSV)"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    wave_id = fields.Many2one("rasentra.migration.wave", string="Gelombang", index=True)
    entity = fields.Selection(SELECTION, string="Data", required=True)
    file = fields.Binary(string="File CSV", attachment=True)
    file_name = fields.Char(string="Nama file")
    sha256 = fields.Char(string="SHA-256", readonly=True, index=True)
    state = fields.Selection(
        [("draft", "Belum dicek"), ("checked", "Lolos pemeriksaan"), ("rejected", "Ada error"),
         ("imported", "Sudah diimpor")],
        string="Status", default="draft", required=True, readonly=True, tracking=True,
    )
    row_count = fields.Integer(string="Jumlah baris", readonly=True)
    error_count = fields.Integer(string="Jumlah error", readonly=True)
    error_html = fields.Html(string="Hasil pemeriksaan", readonly=True, sanitize=True)
    imported_count = fields.Integer(string="Tercatat", readonly=True)
    imported_by_id = fields.Many2one("res.users", string="Diimpor oleh", readonly=True)
    imported_at = fields.Datetime(string="Waktu impor", readonly=True)
    entity_note = fields.Text(string="Petunjuk kolom", compute="_compute_entity_note")

    @api.depends("entity", "file_name")
    def _compute_name(self):
        labels = dict(SELECTION)
        for batch in self:
            batch.name = f"{labels.get(batch.entity, '')} · {batch.file_name or '-'}"

    @api.depends("entity")
    def _compute_entity_note(self):
        for batch in self:
            importer = IMPORTERS.get(batch.entity)
            batch.entity_note = importer.note if importer else False

    def write(self, vals):
        if self.filtered(lambda b: b.state == "imported") and set(vals) & {"file", "entity", "file_name"}:
            raise UserError(_("File yang sudah diimpor tidak bisa diganti. Buat impor baru."))
        if set(vals) & {"file", "entity"}:
            vals = {**vals, "state": "draft", "error_html": False, "error_count": 0}
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda b: b.state == "imported"):
            raise UserError(_("Riwayat impor yang sudah diterapkan tidak bisa dihapus."))
        return super().unlink()

    # ------------------------------------------------------------------ alur

    def _importer(self):
        # Hanya Admin pusat yang bisa membuka model ini; penulisan lintas modul (produk, pegawai, stok) memakai sudo.
        return IMPORTERS[self.entity](self.env(su=True))

    def _rows(self):
        if not self.file:
            raise UserError(_("Unggah file CSV dulu."))
        content = base64.b64decode(self.file)
        return content, *read_csv(content)

    def action_check(self):
        for batch in self:
            content, header, rows = batch._rows()
            errors = batch._importer().check(header, rows)
            batch.write({
                "sha256": hashlib.sha256(content).hexdigest(), "row_count": len(rows), "error_count": len(errors),
                "state": "rejected" if errors else "checked", "error_html": batch._render(errors, len(rows)),
            })
        return True

    def action_import(self):
        self.ensure_one()
        if self.state == "imported":
            raise UserError(_("File ini sudah diimpor."))
        self.action_check()
        if self.state != "checked":
            return True
        importer = self._importer()
        if importer.stock and self.search_count([
            ("sha256", "=", self.sha256), ("entity", "=", self.entity), ("state", "=", "imported"),
            ("id", "!=", self.id),
        ]):
            raise UserError(_("File saldo stok yang sama sudah pernah diimpor. Stok tidak dibukukan dua kali."))
        _content, _header, rows = self._rows()
        count = importer.apply(rows)
        self.write({"state": "imported", "imported_count": count, "imported_by_id": self.env.uid,
                    "imported_at": fields.Datetime.now()})
        self.env["rasentra.audit.event"].record("migration.imported", self, reason=self.name,
                                                 after={"entity": self.entity, "rows": len(rows), "records": count})
        if self.wave_id:
            self.wave_id.message_post(body=_("Impor %(name)s: %(count)s data tercatat.", name=self.name, count=count))
        return True

    def action_download_template(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"/rasentra/migration/template/{self.entity}.csv",
                "target": "download"}

    @staticmethod
    def _render(errors, rows):
        if not errors:
            return (f"<p class='text-success mb-0'><b>{rows} baris lolos pemeriksaan.</b> "
                    "Tekan Impor untuk menuliskannya.</p>")
        body = "".join(f"<tr><td>{line}</td><td>{escape(message)}</td></tr>" for line, message in errors[:MAX_ERRORS])
        more = f"<p>…dan {len(errors) - MAX_ERRORS} error lain.</p>" if len(errors) > MAX_ERRORS else ""
        return (f"<p class='text-danger'><b>{len(errors)} error</b> dari {rows} baris. Perbaiki di file lalu unggah "
                "ulang; tidak ada data yang ditulis.</p><table class='table table-sm'><thead><tr><th>Baris</th>"
                f"<th>Masalah</th></tr></thead><tbody>{body}</tbody></table>{more}")
