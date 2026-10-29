from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from odoo.addons.rasentra_core.tools import RasentraError, money, qty

from ..tools import evaluate

TYPES = [
    ("percent", "Diskon persen"),
    ("amount", "Potongan nominal keranjang"),
    ("special_price", "Harga spesial"),
    ("weight_tier", "Bertingkat per berat"),
    ("buy_x_get_y", "Beli X gratis Y"),
]
STATES = [
    ("draft", "Draft"),
    ("simulated", "Sudah disimulasi"),
    ("published", "Terbit"),
    ("superseded", "Diganti versi baru"),
    ("expired", "Dihentikan"),
]
LINE_TYPES = {"menu": "restaurant_menu", "service": "cooking_service"}
EDITABLE = ("draft", "simulated")
# Kunci aturan yang menyebut produk. Disimpan sebagai kode produk agar sama di Central dan Lokal.
PRODUCT_KEYS = ("buy_product_id", "get_product_id")


def line_type_of(product):
    return LINE_TYPES.get(product.rasentra_type, "retail_product")


class RasentraPromotion(models.Model):
    _name = "rasentra.promotion"
    _description = "Promo Rasentra"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    version_ids = fields.One2many("rasentra.promotion.version", "promotion_id")

    _sql_constraints = [("code_unique", "unique(code)", "Kode promo harus unik.")]


class RasentraPromotionVersion(models.Model):
    """Versi promo (padanan promotion_versions). Alur: draft -> simulated -> published (oleh rekan
    lain) -> superseded / expired. Versi terbit immutable; perubahan = versi baru."""

    _name = "rasentra.promotion.version"
    _description = "Versi promo Rasentra"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "promotion_id, version desc"
    _rec_name = "display_name"
    _rasentra_sync_entity = "promotion_version"

    promotion_id = fields.Many2one("rasentra.promotion", required=True, ondelete="restrict", index=True)
    code = fields.Char(related="promotion_id.code", store=True)
    name = fields.Char(related="promotion_id.name", readonly=False)
    version = fields.Integer(required=True, default=1)
    type = fields.Selection(TYPES, required=True, default="percent", tracking=True)
    scope = fields.Selection([("item", "Per baris"), ("basket", "Keranjang")], required=True, default="item")
    rules = fields.Json(required=True, default=dict, help="Syarat dan manfaat; produk disebut dengan kode produk.")
    channels = fields.Json(help="Daftar kanal; kosong = semua kanal.")
    priority = fields.Integer(default=100)
    stacking = fields.Selection(
        [("exclusive", "Exclusive"), ("stackable", "Bertumpuk"), ("best_benefit", "Manfaat terbesar")],
        default="exclusive", required=True,
    )
    funded_by = fields.Selection(
        [("internal", "Internal"), ("supplier", "Pemasok"), ("bank", "Bank"), ("platform", "Platform")],
        default="internal", required=True,
    )
    starts_at = fields.Datetime(required=True, default=fields.Datetime.now)
    ends_at = fields.Datetime()
    state = fields.Selection(STATES, default="draft", required=True, tracking=True, index=True)
    created_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    published_at = fields.Datetime(readonly=True)
    target_ids = fields.One2many("rasentra.promotion.target", "version_id", string="Outlet target", readonly=True)
    last_simulation = fields.Json(readonly=True)

    _sql_constraints = [("version_unique", "unique(promotion_id, version)", "Nomor versi promo sudah dipakai.")]

    @api.depends("promotion_id.code", "version")
    def _compute_display_name(self):
        for version in self:
            version.display_name = f"{version.promotion_id.code} v{version.version}"

    # ---- immutability ---------------------------------------------------------

    def write(self, vals):
        if not self.env.context.get("rasentra_promo_internal") and not self.env.context.get("rasentra_sync_applying"):
            locked = self.filtered(lambda v: v.state not in EDITABLE)
            if locked and set(vals) - {"message_main_attachment_id"}:
                raise RasentraError.conflict(
                    "promotion_locked", _("Versi yang sudah terbit tidak dapat diubah. Buat versi baru.")
                )
            if set(vals) & {"type", "scope", "rules", "channels", "priority", "stacking", "funded_by", "starts_at",
                            "ends_at"}:
                # Perubahan aturan membatalkan simulasi; penyunting terakhir dianggap pembuat (maker-checker).
                vals = dict(vals, state="draft", created_by=self.env.uid)
        return super().write(vals)

    def unlink(self):
        if any(v.state not in EDITABLE for v in self):
            raise UserError(_("Versi promo yang sudah terbit tidak bisa dihapus."))
        return super().unlink()

    def _internal(self):
        return self.with_context(rasentra_promo_internal=True)

    # ---- engine ---------------------------------------------------------------

    def _engine_promo(self):
        self.ensure_one()
        return {
            "id": self.uuid,
            "type": self.type,
            "scope": self.scope,
            "rules": self.rules or {},
            "priority": self.priority,
            "stacking": self.stacking,
            "funded_by": self.funded_by,
        }

    def _applies_to_channel(self, channel):
        self.ensure_one()
        return not self.channels or channel in self.channels

    @api.model
    def active_for(self, outlet, channel, at=None):
        """Port ActivePromotions::for: versi terbit, outlet ada di snapshot target, dalam jendela waktu."""
        at = at or fields.Datetime.now()
        versions = self.sudo().search([
            ("state", "=", "published"),
            ("starts_at", "<=", at),
            "|", ("ends_at", "=", False), ("ends_at", ">", at),
            ("target_ids.outlet_id", "=", outlet.id),
        ])
        return versions.filtered(lambda v: v._applies_to_channel(channel))

    @api.model
    def engine_line(self, key, product, quantity, unit_price, gross, line_type=None):
        return {
            "key": str(key),
            "product_id": product.default_code or str(product.id),
            "category": product.categ_id.name,
            "line_type": line_type or line_type_of(product),
            "quantity": str(qty(quantity)),
            "unit_price": str(money(unit_price)),
            "gross": str(money(gross)),
        }

    @api.model
    def evaluate(self, lines, versions):
        return evaluate(lines, [v._engine_promo() for v in versions])

    # ---- designer -------------------------------------------------------------

    def simulate(self, outlet, channel, basket):
        """Port PromotionDesigner::simulate. `basket` = [(product.product, kuantitas)]."""
        self.ensure_one()
        if not basket:
            raise RasentraError("basket_empty", _("Isi keranjang contoh minimal satu produk."))
        Price = self.env["rasentra.price.version"]
        lines = []
        for i, (product, quantity) in enumerate(basket, start=1):
            price, _version = Price.resolve(product, outlet, channel)
            lines.append(self.engine_line(f"L{i}", product, quantity, price, money(qty(quantity) * price)))
        others = self.active_for(outlet, channel).filtered(lambda v: v.promotion_id != self.promotion_id)
        channel_ok = self._applies_to_channel(channel)
        before = self.evaluate(lines, others)
        after = self.evaluate(lines, (others | self) if channel_ok else others)
        mine = sum(
            (money(a["amount"]) for line in after["lines"].values() for a in line["allocations"]
             if a["promotion_version_id"] == self.uuid),
            money(0),
        )
        result = {
            "outlet_code": outlet.code,
            "channel": channel,
            "channel_ok": channel_ok,
            "lines": lines,
            "before": before,
            "after": after,
            "gross": str(money(sum(money(line["gross"]) for line in lines))),
            "this_discount": str(mine),
            "other_promos": others.mapped("uuid"),
        }
        if self.state in EDITABLE:
            self._internal().write({"state": "simulated", "last_simulation": result})
            self.env["rasentra.audit.event"].record(
                "promotion.simulated", self, outlet=outlet,
                after={"outlet": outlet.code, "channel": channel, "discount": str(mine)},
            )
        return result

    def publish(self, target):
        """Port PromotionDesigner::publish + PromotionPublisher::publish.

        `target` = {"all": bool, "regions": [kode wilayah], "outlets": [kode outlet]}. Daftar outlet
        dibekukan pada versi ini. Versi lama dari promo yang sama menjadi superseded.
        """
        self.ensure_one()
        if self.state == "published":
            raise RasentraError.conflict("already_published", _("Versi ini sudah diterbitkan; buat versi baru."))
        if self.state != "simulated":
            raise RasentraError.conflict("not_simulated", _("Jalankan simulasi dulu sebelum menerbitkan promo."))
        if self.created_by and self.created_by == self.env.user:
            raise RasentraError.needs_approval("approval_self", _("Pembuat promo tidak dapat menyetujui promonya sendiri."))
        domain = [("active", "=", True)]
        if not target.get("all"):
            domain = expression.AND([domain, ["|", ("code", "in", target.get("outlets") or []),
                                              ("region_id.code", "in", target.get("regions") or [])]])
        outlets = self.env["rasentra.outlet"].sudo().search(domain)
        if not outlets:
            raise RasentraError("no_target", _("Tidak ada outlet target yang aktif."))

        self.env["rasentra.promotion.target"].sudo().create(
            [{"version_id": self.id, "outlet_id": outlet.id} for outlet in outlets]
        )
        self._internal().write({"state": "published", "approved_by": self.env.uid,
                                "published_at": fields.Datetime.now()})
        older = self.search([("promotion_id", "=", self.promotion_id.id), ("id", "!=", self.id),
                             ("state", "=", "published")])
        older._internal().write({"state": "superseded"})
        self.env["rasentra.profile"].publish("promotion_version", self.uuid, self._rasentra_sync_payload(), outlets)
        for old in older:
            self.env["rasentra.profile"].publish(
                "promotion_version", old.uuid, old._rasentra_sync_payload(), old.target_ids.outlet_id
            )
        self.env["rasentra.audit.event"].record(
            "promotion.published", self, after={"outlets": outlets.mapped("code")}
        )
        return True

    def stop(self, reason):
        self.ensure_one()
        if self.state != "published":
            raise RasentraError.conflict("not_published", _("Hanya promo yang sedang terbit yang dapat dihentikan."))
        self._internal().write({"ends_at": fields.Datetime.now(), "state": "expired"})
        self.env["rasentra.profile"].publish(
            "promotion_version", self.uuid, self._rasentra_sync_payload(), self.target_ids.outlet_id
        )
        self.env["rasentra.audit.event"].record("promotion.stopped", self, reason=reason)
        return True

    def new_version(self):
        self.ensure_one()
        if self.search_count([("promotion_id", "=", self.promotion_id.id), ("state", "in", EDITABLE)]):
            raise RasentraError.conflict("draft_exists", _("Promo ini sudah punya versi draft. Lanjutkan versi itu."))
        now = fields.Datetime.now()
        last = max(self.promotion_id.version_ids.mapped("version"))
        new = self.create({
            "promotion_id": self.promotion_id.id,
            "version": last + 1,
            "starts_at": (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if now > self.starts_at else self.starts_at,
            **{f: self[f] for f in ("type", "scope", "rules", "channels", "priority", "stacking", "funded_by",
                                    "ends_at")},
        })
        self.env["rasentra.audit.event"].record("promotion.new_version", new, after={"from_version": self.version})
        return new

    def action_new_version(self):
        new = self.new_version()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id, "view_mode": "form"}

    # ---- sinkron ----------------------------------------------------------------

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "uuid": self.uuid,
            "promotion_code": self.promotion_id.code,
            "promotion_name": self.promotion_id.name,
            "version": self.version,
            "status": self.state,
            "type": self.type,
            "scope": self.scope,
            "rules": self.rules or {},
            "channels": self.channels or None,
            "priority": self.priority,
            "stacking": self.stacking,
            "funded_by": self.funded_by,
            "starts_at": fields.Datetime.to_string(self.starts_at),
            "ends_at": fields.Datetime.to_string(self.ends_at) if self.ends_at else None,
        }

    @api.model
    def _rasentra_sync_snapshot(self, outlet):
        versions = self.search([("state", "=", "published"), ("target_ids.outlet_id", "=", outlet.id)], order="id")
        return [(v.uuid, v._rasentra_sync_payload()) for v in versions]

    @api.model
    def _rasentra_sync_ack(self, device, ack):
        version = self.search([("uuid", "=", ack.get("entity_key"))], limit=1)
        target = version.target_ids.filtered(lambda t: t.outlet_id == device.outlet_id)
        target.write({"ack_status": ack.get("status"), "acked_at": fields.Datetime.now()})

    @api.model
    def _rasentra_sync_apply(self, data):
        """Lokal: upsert per uuid, target = outlet ini (ActivePromotions membaca target)."""
        Promotion = self.env["rasentra.promotion"]
        promotion = Promotion.search([("code", "=", data["promotion_code"])], limit=1)
        if promotion:
            promotion.name = data["promotion_name"]
        else:
            promotion = Promotion.create({"code": data["promotion_code"], "name": data["promotion_name"]})
        vals = {
            "promotion_id": promotion.id,
            "version": data["version"],
            "state": data["status"],
            "type": data["type"],
            "scope": data["scope"],
            "rules": data["rules"],
            "channels": data["channels"],
            "priority": data["priority"],
            "stacking": data["stacking"],
            "funded_by": data["funded_by"],
            "starts_at": data["starts_at"],
            "ends_at": data["ends_at"] or False,
        }
        version = self.search([("uuid", "=", data["uuid"])], limit=1)
        if version:
            version._internal().write(vals)
        else:
            version = self._internal().create({**vals, "uuid": data["uuid"]})
        outlet = self.env["rasentra.profile"].current_outlet()
        if outlet and not version.target_ids.filtered(lambda t: t.outlet_id == outlet):
            self.env["rasentra.promotion.target"].create(
                {"version_id": version.id, "outlet_id": outlet.id, "ack_status": "applied",
                 "acked_at": fields.Datetime.now()}
            )


class RasentraPromotionTarget(models.Model):
    """Snapshot outlet target saat publikasi, plus status penerimaan dari Lokal."""

    _name = "rasentra.promotion.target"
    _description = "Target outlet promo"

    version_id = fields.Many2one("rasentra.promotion.version", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, index=True)
    ack_status = fields.Selection(
        [("pending", "Menunggu"), ("received", "Diterima"), ("applied", "Diterapkan"), ("failed", "Gagal")],
        default="pending", required=True,
    )
    acked_at = fields.Datetime()

    _sql_constraints = [("target_unique", "unique(version_id, outlet_id)", "Outlet sudah menjadi target versi ini.")]
