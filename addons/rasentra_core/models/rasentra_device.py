import hashlib
import secrets

from odoo import _, api, fields, models


class RasentraDevice(models.Model):
    """Perangkat dan server outlet yang boleh memanggil API. Token hanya disimpan sebagai SHA-256."""

    _name = "rasentra.device"
    _description = "Perangkat Rasentra"
    _order = "outlet_id, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="outlet_id.company_id", store=True)
    app = fields.Selection(
        [
            ("lokal", "Server Rasentra Lokal"),
            ("pos", "Rasentra POS"),
            ("mobile", "Mobile Terminal"),
            ("kitchen", "Rasentra Kitchen"),
            ("inventory", "Rasentra Inventory"),
        ],
        required=True,
        default="lokal",
    )
    token_hash = fields.Char(readonly=True, copy=False, groups="base.group_system")
    has_token = fields.Boolean(compute="_compute_has_token")
    active = fields.Boolean(default=True)
    last_seen_at = fields.Datetime(readonly=True)

    _sql_constraints = [("code_unique", "unique(code)", "Kode perangkat harus unik.")]

    @api.depends_context("uid")
    def _compute_has_token(self):
        for device in self:
            device.has_token = bool(device.sudo().token_hash)

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def rotate_token(self):
        """Buat token baru dan kembalikan teks aslinya. Teks asli tidak disimpan."""
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.sudo().write({"token_hash": self._hash(token), "active": True})
        self.env["rasentra.audit.event"].record("device.token_rotated", self, outlet=self.outlet_id)
        return token

    def action_rotate_token(self):
        token = self.rotate_token()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Token baru untuk %s", self.code),
                "message": _("Salin sekarang, token tidak akan ditampilkan lagi: %s", token),
                "sticky": True,
                "type": "warning",
            },
        }

    def action_revoke(self):
        self.sudo().write({"token_hash": False, "active": False})
        for device in self:
            self.env["rasentra.audit.event"].record("device.revoked", device, outlet=device.outlet_id)

    @api.model
    def authenticate(self, token):
        """Kembalikan perangkat aktif pemilik token, atau recordset kosong."""
        if not token:
            return self.browse()
        device = self.sudo().search([("token_hash", "=", self._hash(token)), ("active", "=", True)], limit=1)
        if device:
            device.last_seen_at = fields.Datetime.now()
        return device
