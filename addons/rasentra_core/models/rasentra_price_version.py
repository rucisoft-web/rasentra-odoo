from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from ..tools import RasentraError, money

CHANNELS = [
    ("retail", "Retail"),
    ("restaurant", "Restoran"),
    ("takeaway", "Takeaway"),
    ("delivery", "Delivery"),
]


class RasentraPriceVersion(models.Model):
    """Versi harga per outlet dan kanal, padanan price_versions. Versi published tidak bisa diubah."""

    _name = "rasentra.price.version"
    _description = "Versi harga Rasentra"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "effective_from desc, id desc"

    code = fields.Char(required=True, tracking=True)
    outlet_id = fields.Many2one("rasentra.outlet", help="Kosong = berlaku untuk semua outlet.")
    channel = fields.Selection(CHANNELS, help="Kosong = semua kanal.")
    effective_from = fields.Datetime(required=True, default=fields.Datetime.now)
    effective_to = fields.Datetime()
    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published")], default="draft", required=True, tracking=True
    )
    note = fields.Char()
    item_ids = fields.One2many("rasentra.price.item", "version_id", string="Harga")
    published_by = fields.Many2one("res.users", readonly=True)
    published_at = fields.Datetime(readonly=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)

    _sql_constraints = [("code_unique", "unique(code)", "Kode versi harga harus unik.")]

    def write(self, vals):
        if any(v.state == "published" for v in self) and set(vals) - {"message_main_attachment_id"}:
            raise UserError(_("Versi harga yang sudah dipublikasi tidak bisa diubah. Buat versi baru."))
        return super().write(vals)

    def unlink(self):
        if any(v.state == "published" for v in self):
            raise UserError(_("Versi harga yang sudah dipublikasi tidak bisa dihapus."))
        return super().unlink()

    def action_publish(self):
        for version in self:
            if version.state != "draft":
                raise UserError(_("Hanya versi draft yang bisa dipublikasi."))
            if not version.item_ids:
                raise UserError(_("Versi harga %s belum berisi harga.", version.code))
            super(RasentraPriceVersion, version).write(
                {"state": "published", "published_by": self.env.uid, "published_at": fields.Datetime.now()}
            )
            self.env["rasentra.audit.event"].record(
                "price_version.published", version, outlet=version.outlet_id, after={"code": version.code}
            )
        self._after_publish()
        return True

    def _after_publish(self):
        """Kait untuk addon sinkron: Central membuat publikasi ke outlet di sini."""

    def action_copy_to_draft(self):
        self.ensure_one()
        new = self.copy(
            {
                "code": f"{self.code}-{fields.Datetime.now():%Y%m%d%H%M%S}",
                "state": "draft",
                "effective_from": fields.Datetime.now(),
                "item_ids": [(0, 0, {"product_id": i.product_id.id, "unit_price": i.unit_price}) for i in self.item_ids],
            }
        )
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id, "view_mode": "form"}

    @api.model
    def resolve(self, product, outlet, channel=None, at=None):
        """Harga aktif untuk produk di outlet + kanal (padanan PriceResolver).

        Urutan: versi khusus outlet sebelum versi semua outlet, versi khusus kanal sebelum
        semua kanal, lalu effective_from terbaru. Mengembalikan (Decimal harga, versi).
        """
        at = at or fields.Datetime.now()
        domain = [
            ("product_id", "=", product.id),
            ("version_id.state", "=", "published"),
            ("version_id.effective_from", "<=", at),
            "|", ("version_id.effective_to", "=", False), ("version_id.effective_to", ">", at),
            "|", ("version_id.outlet_id", "=", False), ("version_id.outlet_id", "=", outlet.id),
        ]
        channel_domain = [("version_id.channel", "=", False)]
        if channel:
            channel_domain = expression.OR([channel_domain, [("version_id.channel", "=", channel)]])
        items = self.env["rasentra.price.item"].sudo().search(expression.AND([domain, channel_domain]))
        if not items:
            raise RasentraError("price_not_found", _("Harga belum tersedia untuk produk ini di outlet."))
        best = min(
            items,
            key=lambda i: (
                0 if i.version_id.outlet_id else 1,
                0 if i.version_id.channel else 1,
                -i.version_id.effective_from.timestamp(),
                -i.version_id.id,
            ),
        )
        return money(best.unit_price), best.version_id


class RasentraPriceItem(models.Model):
    _name = "rasentra.price.item"
    _description = "Harga per produk dalam versi"
    _order = "product_id"

    version_id = fields.Many2one("rasentra.price.version", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", required=True, index=True)
    unit_price = fields.Float(string="Harga satuan", digits=(18, 2), required=True)

    _sql_constraints = [
        ("product_unique", "unique(version_id, product_id)", "Produk muncul dua kali dalam satu versi harga."),
        ("price_positive", "check(unit_price >= 0)", "Harga tidak boleh negatif."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        self._check_draft(self.env["rasentra.price.version"].browse([v.get("version_id") for v in vals_list]))
        return super().create(vals_list)

    def write(self, vals):
        self._check_draft(self.version_id)
        return super().write(vals)

    def unlink(self):
        self._check_draft(self.version_id)
        return super().unlink()

    def _check_draft(self, versions):
        if any(v.state == "published" for v in versions):
            raise UserError(_("Harga di versi yang sudah dipublikasi tidak bisa diubah."))
