from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, qty, to_decimal


class RasentraProductionBatch(models.Model):
    """Produksi batch dapur (port RecipeService::produce/produceFromRecipe).

    Keputusan rancangan: memakai model sendiri + stock.move, bukan mrp.production, karena alurnya satu
    layar timbang (input, output aktual, susut beralasan) dan tidak butuh work order/BoM routing MRP.
    """

    _name = "rasentra.production.batch"
    _description = "Produksi batch dapur"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "id desc"
    _rec_name = "doc_no"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    kind = fields.Selection([("cutting", "Potong & porsi"), ("recipe", "Resep berstok")], required=True, readonly=True)
    recipe_version_id = fields.Many2one("rasentra.recipe.version", readonly=True)
    inputs = fields.Json(readonly=True)
    outputs = fields.Json(readonly=True)
    expected_quantity = fields.Float(digits=(18, 6), readonly=True)
    loss_quantity = fields.Float(digits=(18, 6), readonly=True)
    loss_percent = fields.Float(digits=(5, 2), readonly=True)
    loss_reason = fields.Char(readonly=True)
    notes = fields.Text(readonly=True)
    employee_id = fields.Many2one("hr.employee", readonly=True)
    adjustment_id = fields.Many2one("rasentra.stock.adjustment", readonly=True)
    doc_no = fields.Char(related="adjustment_id.doc_no", store=True)
    produced_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    summary = fields.Text(compute="_compute_summary")

    def _compute_summary(self):
        for batch in self:
            ins = ", ".join(f"{i['name']} {i['quantity']}" for i in batch.inputs or [])
            outs = ", ".join(f"{o['name']} {o['quantity']}" for o in batch.outputs or [])
            batch.summary = f"Masuk: {ins}\nHasil: {outs}"

    # ---- aturan -------------------------------------------------------------------------

    @api.model
    def loss_reasons(self):
        raw = self.env["ir.config_parameter"].sudo().get_param("rasentra.production_loss_reasons") or ""
        return [r.strip() for r in raw.split("|") if r.strip()]

    @api.model
    def _tolerance_percent(self):
        return to_decimal(self.env["ir.config_parameter"].sudo().get_param("rasentra.production_loss_tolerance_percent", "2"))

    @api.model
    def _check_loss(self, base, loss, reason):
        if loss <= 0 or not base:
            return
        limit = base * self._tolerance_percent() / 100
        if loss > limit:
            if not (reason or "").strip():
                raise RasentraError("loss_reason_required", _("Susut produksi di atas toleransi. Pilih alasan susut."))
            if reason not in self.loss_reasons():
                raise RasentraError("loss_reason_invalid", _("Alasan susut harus dipilih dari daftar."))

    @api.model
    def produce(self, outlet, employee, inputs, outputs, loss_reason=None, notes=None):
        """Potong & porsi: bahan keluar, hasil (dan produk samping/trimming) masuk dengan berat aktual.
        `inputs`/`outputs`: list (product, quantity[, kind]). Susut = input - output."""
        total_in = sum((qty(q) for _p, q, *_r in inputs), qty(0))
        total_out = sum((qty(q) for _p, q, *_r in outputs), qty(0))
        loss = total_in - total_out
        if loss < 0:
            raise RasentraError("production_balance", _("Hasil produksi melebihi bahan masuk."))
        self._check_loss(total_in, loss, loss_reason)
        return self._book("cutting", outlet, employee, inputs, outputs, loss, total_in, loss_reason, None, notes)

    @api.model
    def produce_from_recipe(self, outlet, employee, version, quantity, actual_output, actual_inputs=None,
                            loss_reason=None, notes=None):
        """Resep berstok (saus, kaldu): bahan standar mengikuti resep, petugas boleh mengoreksi pemakaian.
        Susut = hasil standar - hasil timbang aktual."""
        if version.kind != "stocked_prep" or version.state != "approved":
            raise RasentraError("recipe_not_producible", _("Hanya resep berstok yang sudah disetujui yang bisa diproduksi."))
        quantity, actual_output = qty(quantity), qty(actual_output)
        if quantity <= 0 or actual_output <= 0:
            raise RasentraError("quantity_required", _("Isi jumlah produksi dan hasil timbang."))
        actual_inputs = actual_inputs or {}
        inputs = []
        for need in version.explode(quantity):
            actual = qty(actual_inputs.get(need["product"].id, need["quantity"]))
            if actual < 0:
                raise RasentraError("quantity_invalid", _("Pemakaian bahan tidak boleh negatif."))
            if actual > 0:
                inputs.append((need["product"], actual, need["quantity"]))
        loss = max(quantity - actual_output, qty(0))
        self._check_loss(quantity, loss, loss_reason)
        return self._book("recipe", outlet, employee, inputs, [(version.recipe_id.product_id, actual_output, "main")],
                          loss, quantity, loss_reason, version, notes, expected=quantity)

    @api.model
    def _book(self, kind, outlet, employee, inputs, outputs, loss, base, loss_reason, version, notes, expected=0):
        ledger = self.env["rasentra.stock.ledger"]
        kitchen = self.env["rasentra.kitchen"]._kitchen_location(outlet)
        production = ledger.virtual(outlet.company_id, "production")

        def row(product, quantity, extra):
            return {"product_id": product.id, "code": product.default_code, "name": product.name,
                    "quantity": str(qty(quantity)), "uom": product.uom_id.name, **extra}

        in_rows = [row(p, q, {"standard": str(qty(r[0]))} if r else {}) for p, q, *r in inputs]
        out_rows = [row(p, q, {"kind": r[0] if r else "main"}) for p, q, *r in outputs]
        reason = (_("Produksi resep") if kind == "recipe" else _("Potong & porsi")) + (
            f" · susut: {loss_reason}" if loss_reason else "")
        doc = self.env["rasentra.stock.adjustment"].record(
            "production", outlet,
            [{"product": p, "quantity": q, "from_state": "available", "to_state": None} for p, q, *_r in inputs]
            + [{"product": p, "quantity": q, "from_state": None, "to_state": "available"} for p, q, *_r in outputs],
            employee=employee, reason=reason, source_type="production")
        moves = self.env["stock.move"]
        for product, quantity, *_rest in inputs:
            moves |= ledger.move(product, quantity, kitchen, production, doc.doc_no)
        for product, quantity, *_rest in outputs:
            moves |= ledger.move(product, quantity, production, kitchen, doc.doc_no)
        doc.move_ids = [(6, 0, moves.ids)]
        batch = self.sudo().create({
            "outlet_id": outlet.id, "kind": kind, "recipe_version_id": version.id if version else False,
            "inputs": in_rows, "outputs": out_rows, "expected_quantity": float(qty(expected)),
            "loss_quantity": float(qty(loss)), "loss_percent": float(loss / base * 100) if base else 0,
            "loss_reason": loss_reason or False, "notes": notes or False,
            "employee_id": employee.id if employee else False, "adjustment_id": doc.id,
        })
        self.env["rasentra.audit.event"].record("production.recorded", batch, employee=employee, reason=loss_reason,
                                                outlet=outlet, after={"doc_no": doc.doc_no, "loss": str(qty(loss))})
        return batch


class RasentraProductionWizard(models.TransientModel):
    """Form potong & porsi di backend: timbang bahan masuk, hasil utama, trimming; susut dihitung."""

    _name = "rasentra.production.wizard"
    _description = "Catat produksi potong & porsi"

    outlet_id = fields.Many2one(
        "rasentra.outlet", required=True,
        default=lambda self: self.env["rasentra.profile"].current_outlet() or self.env["rasentra.outlet"].search(
            [("has_restaurant", "=", True)], limit=1))
    input_ids = fields.One2many("rasentra.production.wizard.line", "wizard_id", domain=[("side", "=", "input")])
    output_ids = fields.One2many("rasentra.production.wizard.line", "wizard_id", domain=[("side", "=", "output")])
    loss_reason = fields.Selection(selection="_loss_reason_selection", string="Alasan susut")
    notes = fields.Text()
    loss_preview = fields.Char(compute="_compute_loss_preview", string="Susut")

    @api.model
    def _loss_reason_selection(self):
        return [(r, r) for r in self.env["rasentra.production.batch"].loss_reasons()]

    @api.depends("input_ids.quantity", "output_ids.quantity")
    def _compute_loss_preview(self):
        for wizard in self:
            total_in = sum(wizard.input_ids.mapped("quantity"))
            loss = total_in - sum(wizard.output_ids.mapped("quantity"))
            wizard.loss_preview = f"{loss:.3f} ({(loss / total_in * 100) if total_in else 0:.2f}%)"

    def action_record(self):
        self.ensure_one()
        batch = self.env["rasentra.production.batch"].sudo().produce(
            self.outlet_id, self.env.user.employee_id,
            [(l.product_id, l.quantity) for l in self.input_ids],
            [(l.product_id, l.quantity, l.kind or "main") for l in self.output_ids],
            self.loss_reason or None, self.notes,
        )
        return {"type": "ir.actions.act_window", "res_model": batch._name, "res_id": batch.id, "view_mode": "form"}


class RasentraProductionWizardLine(models.TransientModel):
    _name = "rasentra.production.wizard.line"
    _description = "Baris produksi"

    wizard_id = fields.Many2one("rasentra.production.wizard", ondelete="cascade")
    side = fields.Selection([("input", "Bahan"), ("output", "Hasil")], required=True, default="input")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(digits=(18, 3), required=True)
    kind = fields.Selection([("main", "Hasil utama"), ("trimming", "Trimming / produk samping")], default="main")
