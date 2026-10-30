from decimal import ROUND_HALF_UP, Decimal

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, qty, to_decimal

RECIPE_KINDS = [
    ("menu", "Menu"),
    ("virtual_prep", "Subresep virtual (diurai ke bahan)"),
    ("stocked_prep", "Subresep berstok (saus, kaldu)"),
]
STATES = [("draft", "Draft"), ("approved", "Disetujui"), ("retired", "Pensiun")]
FACTOR_PLACES = Decimal("0.000001")


class RasentraRecipe(models.Model):
    _name = "rasentra.recipe"
    _description = "Resep Rasentra"
    _inherit = ["mail.thread"]
    _order = "product_id"

    product_id = fields.Many2one("product.product", required=True, index=True, tracking=True)
    name = fields.Char(related="product_id.display_name", store=True)
    version_ids = fields.One2many("rasentra.recipe.version", "recipe_id", string="Versi")
    active_version_id = fields.Many2one("rasentra.recipe.version", compute="_compute_active_version_id")

    _sql_constraints = [("product_unique", "unique(product_id)", "Satu produk hanya punya satu resep.")]

    @api.depends("version_ids.state", "version_ids.version")
    def _compute_active_version_id(self):
        for recipe in self:
            recipe.active_version_id = recipe.version_ids.filtered(lambda v: v.state == "approved").sorted(
                "version", reverse=True)[:1]

    @api.model
    def active_version_for(self, product):
        recipe = self.sudo().search([("product_id", "=", product.id)], limit=1)
        return recipe.active_version_id

    def action_new_draft(self):
        self.ensure_one()
        base = self.active_version_id or self.version_ids.sorted("version", reverse=True)[:1]
        version = base.new_version() if base else self.env["rasentra.recipe.version"].create(
            {"recipe_id": self.id, "version": 1})
        return {"type": "ir.actions.act_window", "res_model": version._name, "res_id": version.id, "view_mode": "form"}


class RasentraRecipeVersion(models.Model):
    """Versi resep (port RecipeVersion + RecipeService + RecipeExploder). Versi approved tidak bisa
    diubah; perubahan = versi baru. Histori konsumsi menyimpan versi yang dipakai."""

    _name = "rasentra.recipe.version"
    _description = "Versi resep"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "recipe_id, version desc"
    _rasentra_sync_entity = "recipe_version"

    recipe_id = fields.Many2one("rasentra.recipe", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one(related="recipe_id.product_id", store=True)
    version = fields.Integer(required=True, default=1)
    kind = fields.Selection(RECIPE_KINDS, required=True, default="menu")
    yield_quantity = fields.Float(digits=(18, 6), required=True, default=1.0, string="Hasil standar")
    yield_uom_id = fields.Many2one("uom.uom", string="Satuan hasil")
    state = fields.Selection(STATES, default="draft", required=True, tracking=True, index=True)
    edited_by_id = fields.Many2one("res.users", string="Terakhir disunting", readonly=True)
    approved_by_id = fields.Many2one("res.users", string="Disetujui oleh", readonly=True)
    effective_from = fields.Datetime(string="Berlaku mulai")
    outlet_ids = fields.Many2many("rasentra.outlet", string="Outlet (kosong = semua)")
    line_ids = fields.One2many("rasentra.recipe.line", "version_id", string="Komposisi", copy=True)
    notes = fields.Text()

    _sql_constraints = [
        ("version_unique", "unique(recipe_id, version)", "Nomor versi resep sudah dipakai."),
        ("yield_positive", "check(yield_quantity > 0)", "Hasil standar harus lebih dari nol."),
    ]

    @api.depends("recipe_id", "version")
    def _compute_display_name(self):
        for version in self:
            version.display_name = f"{version.recipe_id.name or ''} v{version.version}"

    # ---- immutabilitas & maker-checker ---------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("edited_by_id", self.env.uid)
        return super().create(vals_list)

    def write(self, vals):
        internal = self.env.context.get("rasentra_recipe_internal")
        if not internal:
            if self.filtered(lambda v: v.state != "draft") and set(vals) - {"message_main_attachment_id"}:
                raise RasentraError("recipe_immutable", _("Versi resep yang sudah disetujui tidak bisa diubah. Buat versi baru."))
            vals = dict(vals, edited_by_id=self.env.uid)
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda v: v.state != "draft"):
            raise RasentraError("recipe_immutable", _("Hanya draft resep yang bisa dihapus."))
        return super().unlink()

    def _internal(self):
        return self.with_context(rasentra_recipe_internal=True)

    def approve(self, approver=None):
        """Maker-checker: penyunting terakhir draft tidak boleh menyetujui draftnya sendiri."""
        self.ensure_one()
        approver = approver or self.env.user
        if self.state != "draft":
            raise RasentraError.conflict("recipe_not_draft", _("Hanya draft yang bisa disetujui."))
        if self.edited_by_id and self.edited_by_id == approver:
            raise RasentraError.needs_approval(
                "approval_self",
                _("Anda yang terakhir menyunting draft resep ini. Minta rekan lain (chef kepala atau admin pusat) untuk menyetujui."),
            )
        if not self.line_ids:
            raise RasentraError("recipe_empty", _("Resep belum punya komposisi."))
        self._assert_acyclic()
        others = self.recipe_id.version_ids.filtered(lambda v: v.state == "approved" and v != self)
        others._internal().write({"state": "retired"})
        self._internal().write({"state": "approved", "approved_by_id": approver.id,
                                "effective_from": self.effective_from or fields.Datetime.now()})
        self.env["rasentra.audit.event"].record("recipe.approved", self, actor=approver)
        self.env["rasentra.profile"].publish("recipe_version", self.uuid, self._rasentra_sync_payload(),
                                             self.outlet_ids or None)
        return self

    def action_approve(self):
        for version in self:
            version.approve()
        return True

    def new_version(self):
        self.ensure_one()
        last = max(self.recipe_id.version_ids.mapped("version"))
        return self.copy({"version": last + 1, "state": "draft", "approved_by_id": False, "effective_from": False,
                          "uuid": False})

    def copy(self, default=None):
        default = dict(default or {})
        if not default.get("uuid"):
            default.pop("uuid", None)
        return super().copy(default)

    def action_new_version(self):
        new = self.new_version()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id, "view_mode": "form"}

    # ---- penguraian ------------------------------------------------------------------

    def explode(self, portions, modifiers=()):
        """Kebutuhan bahan untuk `portions` porsi. Subresep virtual diuraikan ke bahan asal; subresep
        berstok dipotong sebagai barang jadi. Modifier: baris ber-modifier_key hanya ikut bila dipilih;
        "without:<kode>" menghilangkan bahan. Mengembalikan list dict product, quantity (Decimal)."""
        self.ensure_one()
        needs = {}
        self._walk(to_decimal(portions), set(modifiers or ()), needs, {self.recipe_id.id})
        return [{"product": product, "quantity": qty(quantity)} for product, quantity in needs.items()]

    def _walk(self, portions, modifiers, needs, path):
        factor = (portions / to_decimal(self.yield_quantity)).quantize(FACTOR_PLACES, rounding=ROUND_HALF_UP)
        Recipe = self.env["rasentra.recipe"]
        for line in self.line_ids:
            if line.modifier_key and line.modifier_key not in modifiers:
                continue
            if f"without:{line.component_product_id.default_code}" in modifiers:
                continue
            quantity = to_decimal(line.quantity) * factor
            sub = Recipe.active_version_for(line.component_product_id)
            if sub and sub.kind == "virtual_prep":
                if sub.recipe_id.id in path:
                    raise RasentraError("recipe_cycle", _("Resep memiliki siklus dan tidak dapat diuraikan."))
                sub._walk(quantity, modifiers, needs, path | {sub.recipe_id.id})
                continue
            product = line.component_product_id
            needs[product] = needs.get(product, Decimal(0)) + quantity

    def _assert_acyclic(self):
        """DFS pada graf subresep (termasuk subresep berstok dan draft ini sendiri)."""
        Recipe = self.env["rasentra.recipe"]

        def visit(version, path):
            for line in version.line_ids:
                component = line.component_product_id
                if component == self.recipe_id.product_id or component.id in path:
                    raise RasentraError("recipe_cycle", _("Resep %s memuat dirinya sendiri lewat subresep.",
                                                          self.recipe_id.name))
                sub = Recipe.active_version_for(component)
                if sub:
                    visit(sub, path | {component.id})

        visit(self, {self.recipe_id.product_id.id})

    # ---- sinkron ---------------------------------------------------------------------

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "uuid": self.uuid,
            "product_code": self.recipe_id.product_id.default_code,
            "version": self.version,
            "kind": self.kind,
            "yield_quantity": str(qty(self.yield_quantity)),
            "yield_uom": self.yield_uom_id.name or None,
            "status": self.state,
            "effective_from": fields.Datetime.to_string(self.effective_from) if self.effective_from else None,
            "lines": [
                {"product_code": l.component_product_id.default_code, "quantity": str(qty(l.quantity)),
                 "uom": l.uom_id.name or None, "modifier_key": l.modifier_key or None}
                for l in self.line_ids
            ],
        }

    @api.model
    def _rasentra_sync_snapshot(self, outlet):
        versions = self.search([("state", "=", "approved"), "|", ("outlet_ids", "=", False),
                                ("outlet_ids", "in", outlet.ids)], order="id")
        return [(v.uuid, v._rasentra_sync_payload()) for v in versions]

    @api.model
    def _rasentra_sync_apply(self, data):
        """Lokal: upsert per uuid. Versi lain yang approved untuk resep sama dipensiunkan."""
        Product = self.env["product.product"].with_context(active_test=False)
        product = Product.search([("default_code", "=", data["product_code"])], limit=1)
        if not product:
            raise RasentraError("sync_unknown_product", _("Produk %s belum ada di Lokal.", data["product_code"]))
        Recipe = self.env["rasentra.recipe"]
        recipe = Recipe.search([("product_id", "=", product.id)], limit=1) or Recipe.create({"product_id": product.id})
        lines = []
        for line in data["lines"]:
            component = Product.search([("default_code", "=", line["product_code"])], limit=1)
            if not component:
                raise RasentraError("sync_unknown_product", _("Produk %s belum ada di Lokal.", line["product_code"]))
            lines.append((0, 0, {"component_product_id": component.id, "quantity": float(qty(line["quantity"])),
                                 "modifier_key": line.get("modifier_key") or False}))
        vals = {"recipe_id": recipe.id, "version": data["version"], "kind": data["kind"],
                "yield_quantity": float(qty(data["yield_quantity"])), "state": data["status"],
                "effective_from": data.get("effective_from") or False}
        version = self.search([("uuid", "=", data["uuid"])], limit=1)
        if version:
            version._internal().write(dict(vals, line_ids=[(5, 0, 0)] + lines))
        else:
            version = self._internal().create(dict(vals, uuid=data["uuid"], line_ids=lines))
        if version.state == "approved":
            (recipe.version_ids - version).filtered(lambda v: v.state == "approved")._internal().write({"state": "retired"})
        return version


class RasentraRecipeLine(models.Model):
    _name = "rasentra.recipe.line"
    _description = "Komposisi resep"
    _order = "version_id, sequence, id"

    version_id = fields.Many2one("rasentra.recipe.version", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    component_product_id = fields.Many2one("product.product", string="Komponen", required=True)
    quantity = fields.Float(digits=(18, 6), required=True)
    uom_id = fields.Many2one(related="component_product_id.uom_id", string="Satuan")
    modifier_key = fields.Char(string="Kunci modifier", help="Baris hanya dipakai bila modifier ini dipilih, mis. extra_butter.")

    def write(self, vals):
        if not self.env.context.get("rasentra_recipe_internal") and self.version_id.filtered(lambda v: v.state != "draft"):
            raise RasentraError("recipe_immutable", _("Versi resep yang sudah disetujui tidak bisa diubah. Buat versi baru."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get("rasentra_recipe_internal") and lines.version_id.filtered(lambda v: v.state != "draft"):
            raise RasentraError("recipe_immutable", _("Versi resep yang sudah disetujui tidak bisa diubah. Buat versi baru."))
        lines.version_id.filtered(lambda v: v.state == "draft").with_context(rasentra_recipe_internal=True).write(
            {"edited_by_id": self.env.uid})
        return lines
