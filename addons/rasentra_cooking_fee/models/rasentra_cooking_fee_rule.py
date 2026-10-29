from decimal import ROUND_HALF_UP, Decimal

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty, to_decimal

BASES = [("per_kg", "Per kg mentah"), ("per_pack", "Per pack"), ("per_portion", "Per porsi"), ("tiered", "Bertingkat per kg")]
COOKING_METHODS = [("grill", "Grill"), ("pan_sear", "Pan sear"), ("fry", "Goreng"), ("steam", "Kukus"), ("bbq", "Bakar")]


class RasentraCookingFeeRule(models.Model):
    """Tarif jasa memasak (port CookingFeeRule). Aturan yang sudah terbit tidak diubah; perubahan =
    supersede menjadi versi baru dan versi lama berakhir saat versi baru mulai berlaku."""

    _name = "rasentra.cooking.fee.rule"
    _description = "Aturan cooking fee"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "code, version desc"
    _rasentra_sync_entity = "cooking_fee_rule"

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    version = fields.Integer(required=True, default=1)
    state = fields.Selection([("draft", "Draft"), ("published", "Terbit"), ("superseded", "Digantikan")],
                             default="draft", required=True, tracking=True)
    outlet_id = fields.Many2one("rasentra.outlet", string="Outlet (kosong = semua)")
    method = fields.Selection(COOKING_METHODS, string="Metode masak (kosong = semua)")
    basis = fields.Selection(BASES, required=True, default="per_kg")
    rate = fields.Float(digits=(18, 2), required=True)
    minimum_fee = fields.Float(digits=(18, 2))
    tiers = fields.Json(help='Mis. [{"up_to": "1.000", "rate": "45000"}, {"up_to": "2.000", "rate": "40000"}]')
    included_product_ids = fields.Many2many("product.product", string="Item termasuk paket")
    service_product_id = fields.Many2one(
        "product.product", required=True, string="Produk jasa",
        default=lambda self: self.env.ref("rasentra_cooking_fee.product_cooking_service", raise_if_not_found=False),
    )
    recipe_version_id = fields.Many2one("rasentra.recipe.version", string="Resep jasa (butter, bumbu, saus)")
    effective_from = fields.Datetime(required=True, default=fields.Datetime.now)
    effective_to = fields.Datetime()

    _sql_constraints = [("code_version_unique", "unique(code, version)", "Versi aturan cooking fee sudah ada.")]

    def write(self, vals):
        if not self.env.context.get("rasentra_fee_internal") and self.filtered(lambda r: r.state != "draft"):
            raise RasentraError("fee_rule_immutable", _("Aturan cooking fee yang sudah terbit tidak bisa diubah. Buat versi baru."))
        return super().write(vals)

    def _internal(self):
        return self.with_context(rasentra_fee_internal=True)

    def action_publish(self):
        for rule in self:
            if rule.state != "draft":
                continue
            previous = self.search([("code", "=", rule.code), ("state", "=", "published"), ("id", "!=", rule.id)])
            previous._internal().write({"state": "superseded", "effective_to": rule.effective_from})
            rule._internal().write({"state": "published"})
            self.env["rasentra.audit.event"].record("cooking_fee.published", rule, after={"version": rule.version})
            self.env["rasentra.profile"].publish("cooking_fee_rule", rule.uuid, rule._rasentra_sync_payload(),
                                                 rule.outlet_id or None)
        return True

    def new_version(self):
        self.ensure_one()
        last = max(self.search([("code", "=", self.code)]).mapped("version"))
        return self.copy({"version": last + 1, "state": "draft", "effective_from": fields.Datetime.now(),
                          "effective_to": False})

    def action_new_version(self):
        new = self.new_version()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id, "view_mode": "form"}

    # ---- tarif -------------------------------------------------------------------------

    @api.model
    def rule_for(self, outlet, method=None, at=None):
        """Aturan paling spesifik: outlet dulu lalu semua outlet, metode dulu lalu semua metode, versi terbaru."""
        at = at or fields.Datetime.now()
        rules = self.sudo().search([
            ("state", "in", ("published", "superseded")), ("effective_from", "<=", at),
            "|", ("effective_to", "=", False), ("effective_to", ">", at),
            "|", ("outlet_id", "=", False), ("outlet_id", "=", outlet.id),
            "|", ("method", "=", False), ("method", "=", method or False),
        ])
        if not rules:
            raise RasentraError("fee_rule_missing", _("Tarif cooking fee belum diatur untuk outlet ini."))
        return rules.sorted(lambda r: (0 if r.outlet_id else 1, 0 if r.method else 1, -r.version))[0]

    def fee(self, raw_weight, portions):
        """per_kg = berat × tarif; per_pack = tarif; per_portion = porsi × tarif; tiered = berat × tarif
        tingkat yang berlaku; minimal minimum_fee, dibulatkan ke rupiah."""
        self.ensure_one()
        weight = qty(raw_weight)
        if self.basis == "per_kg":
            amount = weight * to_decimal(self.rate)
        elif self.basis == "per_pack":
            amount = to_decimal(self.rate)
        elif self.basis == "per_portion":
            amount = to_decimal(int(portions)) * to_decimal(self.rate)
        elif self.basis == "tiered":
            amount = weight * self._tier_rate(weight)
        else:
            raise RasentraError("fee_basis_invalid", _("Dasar tarif cooking fee tidak dikenal."))
        minimum = to_decimal(self.minimum_fee)
        return money((minimum if amount < minimum else amount).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    def _tier_rate(self, weight):
        for tier in self.tiers or []:
            if weight <= to_decimal(tier["up_to"]):
                return to_decimal(tier["rate"])
        return to_decimal(self.rate)

    def quantity_label(self, raw_weight, portions):
        if self.basis in ("per_kg", "tiered"):
            return f"{qty(raw_weight):.3f} kg"
        if self.basis == "per_portion":
            return f"{int(portions)} porsi"
        return "1 pack"

    # ---- sinkron -----------------------------------------------------------------------

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "uuid": self.uuid, "code": self.code, "name": self.name, "version": self.version, "status": self.state,
            "outlet_uuid": self.outlet_id.uuid or None, "method": self.method or None, "basis": self.basis,
            "rate": str(money(self.rate)), "minimum_fee": str(money(self.minimum_fee)), "tiers": self.tiers or [],
            "service_product_code": self.service_product_id.default_code,
            "recipe_version_uuid": self.recipe_version_id.uuid or None,
            "effective_from": fields.Datetime.to_string(self.effective_from),
            "effective_to": fields.Datetime.to_string(self.effective_to) if self.effective_to else None,
        }

    @api.model
    def _rasentra_sync_snapshot(self, outlet):
        rules = self.search([("state", "=", "published"), "|", ("outlet_id", "=", False), ("outlet_id", "=", outlet.id)])
        return [(r.uuid, r._rasentra_sync_payload()) for r in rules]

    @api.model
    def _rasentra_sync_apply(self, data):
        product = self.env["product.product"].with_context(active_test=False).search(
            [("default_code", "=", data["service_product_code"])], limit=1)
        vals = {
            "code": data["code"], "name": data["name"], "version": data["version"], "state": data["status"],
            "outlet_id": self.env["rasentra.outlet"].search([("uuid", "=", data["outlet_uuid"])], limit=1).id
            if data.get("outlet_uuid") else False,
            "method": data.get("method") or False, "basis": data["basis"], "rate": float(data["rate"]),
            "minimum_fee": float(data["minimum_fee"]), "tiers": data.get("tiers") or [],
            "service_product_id": product.id,
            "recipe_version_id": self.env["rasentra.recipe.version"].search(
                [("uuid", "=", data.get("recipe_version_uuid"))], limit=1).id if data.get("recipe_version_uuid") else False,
            "effective_from": data["effective_from"], "effective_to": data.get("effective_to") or False,
        }
        rule = self.search([("uuid", "=", data["uuid"])], limit=1)
        if rule:
            rule._internal().write(vals)
        else:
            self._internal().create(dict(vals, uuid=data["uuid"]))
