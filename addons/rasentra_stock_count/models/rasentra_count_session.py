from odoo import _, api, fields, models

from odoo.addons.rasentra_core.models.rasentra_approval import APPROVER_ROLES
from odoo.addons.rasentra_core.tools import RasentraError, qty

OPENER_ROLES = ("outlet_head", "admin", "warehouse")
COUNTED_PACK_STATUSES = ("received", "available", "reserved", "hold")


class RasentraCountSession(models.Model):
    """Stok opname (port StockCountService). Petugas hitung tidak melihat saldo sistem (blind
    count); saldo pembanding diambil per cutoff, sehingga penjualan selama menghitung tidak
    mengacaukan selisih. Selisih di atas ambang wajib dihitung ulang oleh petugas berbeda
    sebelum kepala outlet menyetujui dan penyesuaian diposting."""

    _name = "rasentra.count.session"
    _description = "Sesi opname Rasentra"
    _inherit = ["rasentra.uuid.mixin", "mail.thread"]
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    count_type = fields.Selection(
        [("full", "Penuh"), ("cycle", "Siklus"), ("special", "Khusus")],
        string="Jenis opname", required=True, default="cycle", readonly=True,
    )
    blind = fields.Boolean(default=True, readonly=True, string="Hitung buta")
    cutoff_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, string="Cut-off")
    recount_threshold = fields.Float(digits=(18, 6), default=0.05, readonly=True, string="Ambang hitung ulang")
    state = fields.Selection(
        [("counting", "Menghitung"), ("recount", "Hitung ulang"), ("review", "Review"), ("approved", "Disetujui")],
        default="counting", required=True, readonly=True, tracking=True,
    )
    current_round = fields.Integer(default=1, readonly=True, string="Ronde")
    recount_product_ids = fields.Many2many("product.product", string="Produk hitung ulang", readonly=True)
    created_by_id = fields.Many2one("hr.employee", string="Dibuka oleh", readonly=True)
    approved_by_id = fields.Many2one("hr.employee", string="Disetujui oleh", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    summary = fields.Json(readonly=True)
    line_ids = fields.One2many("rasentra.count.line", "session_id", readonly=True)
    adjustment_id = fields.Many2one("rasentra.stock.adjustment", readonly=True, string="Dokumen penyesuaian")
    summary_html = fields.Html(compute="_compute_summary_html", sanitize=False)

    @api.depends("outlet_id", "cutoff_at")
    def _compute_name(self):
        for session in self:
            session.name = f"OP {session.outlet_id.code or ''} {fields.Datetime.to_string(session.cutoff_at) or ''}".strip()

    def _compute_summary_html(self):
        for session in self:
            rows = session.summary or []
            if not rows:
                session.summary_html = False
                continue
            body = "".join(
                f"<tr class='{'table-warning' if r['flagged'] else ''}'><td>{r['code'] or ''}</td><td>{r['name']}</td>"
                f"<td class='text-end'>{r['system']}</td><td class='text-end'>{r['counted']}</td>"
                f"<td class='text-end'>{r['variance']}</td><td>{r['round']}</td>"
                f"<td>{', '.join(r['missing_packs'])}</td></tr>"
                for r in rows
            )
            session.summary_html = (
                "<table class='table table-sm'><thead><tr><th>Kode</th><th>Produk</th><th>Sistem</th>"
                "<th>Hitung</th><th>Selisih</th><th>Ronde</th><th>Pack belum dihitung</th></tr></thead>"
                f"<tbody>{body}</tbody></table>"
            )

    # ------------------------------------------------------------------ alur

    @api.model
    def open(self, employee, outlet, count_type="cycle", blind=True, threshold="0.050"):
        if not employee or employee.rasentra_role not in OPENER_ROLES:
            raise RasentraError(
                "forbidden_role", _("Hanya kepala outlet atau petugas gudang yang dapat membuat sesi opname."), 403
            )
        session = self.sudo().create(
            {
                "outlet_id": outlet.id,
                "count_type": count_type,
                "blind": blind,
                "recount_threshold": float(qty(threshold)),
                "created_by_id": employee.id,
            }
        )
        self.env["rasentra.audit.event"].record("count.opened", session, employee=employee, outlet=outlet)
        return session

    def record_scan(self, employee, code, quantity, location_code):
        """Catat satu scan. Pack ID dihitung sebagai berat bersihnya; SKU wajib kuantitas."""
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM rasentra_count_session WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if self.state not in ("counting", "recount"):
            raise RasentraError.conflict("count_closed", _("Sesi opname tidak sedang menghitung."))
        # Lokasi milik outlet, ditambah lokasi stok gudang yang dipakai outlet (tanpa penanda outlet).
        stock_location = self.env["rasentra.stock.ledger"].location(self.outlet_id, "stock")
        location = self.env["stock.location"].sudo().search(
            ["|", ("rasentra_outlet_id", "=", self.outlet_id.id), ("id", "=", stock_location.id),
             "|", ("barcode", "=", location_code), ("name", "=", location_code)], limit=1,
        )
        if not location:
            raise RasentraError(
                "location_unknown", _("Lokasi %s tidak dikenal. Scan QR lokasi dulu.", location_code), 404
            )
        code = (code or "").strip()
        pack = self.env["stock.lot"].sudo().search([("name", "=", code), ("is_rasentra_pack", "=", True)], limit=1)
        if pack:
            if pack.rasentra_outlet_id != self.outlet_id:
                raise RasentraError.conflict(
                    "pack_other_outlet", _("Pack %s tercatat milik outlet lain. Pisahkan dan laporkan.", code)
                )
            product, amount = pack.product_id, qty(pack.net_weight)
        else:
            product = self.env["rasentra.inventory"]._product_by_code(code)
            if product.rasentra_type == "meat_pack":
                raise RasentraError("scan_pack", _("Produk timbang dihitung per Pack ID. Scan label kemasan."))
            amount = qty(quantity or 0)
            if amount <= 0:
                raise RasentraError("quantity_required", _("Isi jumlah hitungan."))

        round_no = self.current_round
        if round_no > 1:
            if product not in self.recount_product_ids:
                raise RasentraError.conflict("not_in_recount", _("Produk ini tidak termasuk daftar hitung ulang."))
            first = self.line_ids.filtered(lambda l: l.round == 1 and l.product_id == product)
            if employee in first.counted_by_id:
                raise RasentraError.conflict(
                    "recount_same_counter", _("Hitung ulang harus oleh petugas yang berbeda dari hitungan pertama.")
                )
        if pack and self.line_ids.filtered(lambda l: l.round == round_no and l.lot_id == pack):
            raise RasentraError.conflict("pack_already_counted", _("Pack %s sudah dihitung di ronde ini.", code))
        return self.env["rasentra.count.line"].sudo().create(
            {
                "session_id": self.id,
                "round": round_no,
                "location_id": location.id,
                "product_id": product.id,
                "lot_id": pack.id if pack else False,
                "quantity": float(amount),
                "counted_by_id": employee.id if employee else False,
            }
        )

    def progress(self, employee):
        """Progres untuk petugas hitung. Pada blind count tidak memuat saldo sistem."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.round == self.current_round).sorted("id", reverse=True)
        return {
            "session": {"id": self.id, "type": self.count_type, "blind": self.blind, "status": self.state,
                        "current_round": self.current_round},
            "recount_products": [{"id": p.id, "code": p.default_code, "name": p.name} for p in self.recount_product_ids]
            if self.current_round > 1 else [],
            "my_lines": [
                {"id": l.id, "product": l.product_id.name, "quantity": str(qty(l.quantity)),
                 "uom": l.product_id.uom_id.name, "pack": l.lot_id.name or None}
                for l in lines.filtered(lambda l: l.counted_by_id == employee)[:30]
            ],
            "total_lines": len(lines),
        }

    def _assert_approver(self, employee):
        if not employee or employee.rasentra_role not in APPROVER_ROLES:
            raise RasentraError("forbidden_role", _("Review dan persetujuan opname hanya oleh kepala outlet."), 403)

    def review(self, employee):
        """Bandingkan hitungan dengan saldo per cutoff. Ronde 1 dengan selisih di atas ambang → hitung ulang."""
        self.ensure_one()
        self._assert_approver(employee)
        if self.state not in ("counting", "recount", "review"):
            raise RasentraError.conflict("count_closed", _("Sesi opname sudah ditutup."))
        report = self._report()
        flagged = [r["product_id"] for r in report if r["flagged"]]
        if self.current_round == 1 and flagged:
            self.sudo().write({"state": "recount", "current_round": 2,
                               "recount_product_ids": [(6, 0, flagged)], "summary": report})
        else:
            self.sudo().write({"state": "review", "summary": report})
        return {"status": self.state, "current_round": self.current_round, "lines": report}

    def approve(self, employee):
        """Kepala outlet memposting penyesuaian sebesar selisih final."""
        self.ensure_one()
        self._assert_approver(employee)
        if self.state != "review":
            raise RasentraError.conflict(
                "count_not_reviewed", _("Review hasil hitung (dan hitung ulang bila diminta) sebelum menyetujui.")
            )
        if employee.rasentra_outlet_id != self.outlet_id and employee.rasentra_role != "admin":
            raise RasentraError("forbidden_outlet", _("Penyetuju bukan dari outlet ini."), 403)
        if employee in self.line_ids.counted_by_id:
            raise RasentraError.conflict("approval_self", _("Petugas hitung tidak bisa menyetujui hasilnya sendiri."))

        report = self._report()
        ledger = self.env["rasentra.stock.ledger"]
        stock = ledger.location(self.outlet_id, "stock")
        loss = ledger.virtual(self.outlet_id.company_id, "inventory")
        Product = self.env["product.product"]
        adjusted = []
        for row in report:
            variance = qty(row["variance"])
            if not variance:
                continue
            more = variance > 0
            adjusted.append({"product": Product.browse(row["product_id"]), "quantity": abs(variance),
                             "from_state": None if more else "available", "to_state": "available" if more else None})
        doc = self.env["rasentra.stock.adjustment"].record(
            "count", self.outlet_id, adjusted, employee=employee, approver=employee,
            reason=_("Stok opname %s", self.count_type), source_type="count_session", source_ref=self.uuid,
        )
        moves = self.env["stock.move"]
        for line in adjusted:
            src, dst = (loss, stock) if line["to_state"] else (stock, loss)
            moves |= ledger.move(line["product"], line["quantity"], src, dst, doc.doc_no if doc else self.name)
        if doc:
            doc.move_ids = [(6, 0, moves.ids)]
        self.sudo().write({"state": "approved", "approved_by_id": employee.id, "approved_at": fields.Datetime.now(),
                           "summary": report, "adjustment_id": doc.id if doc else False})
        self.env["rasentra.audit.event"].record(
            "count.approved", self, employee=employee, approver=employee, outlet=self.outlet_id,
            after={"adjusted_products": len(adjusted)},
        )
        return self

    def _report(self):
        self.ensure_one()
        ledger = self.env["rasentra.stock.ledger"]
        stock = ledger.location(self.outlet_id, "stock")
        products = self.line_ids.product_id
        if self.count_type == "full":
            # Opname penuh: produk bersaldo yang tidak dihitung sama sekali dianggap nol.
            quants = self.env["stock.quant"].sudo().search([("location_id", "child_of", stock.id), ("quantity", "!=", 0)])
            products |= quants.product_id
        threshold = qty(self.recount_threshold)
        report = []
        for product in products.sorted("name"):
            own = self.line_ids.filtered(lambda l: l.product_id == product)
            round_no = max(own.mapped("round") or [1])
            current = own.filtered(lambda l: l.round == round_no)
            counted = qty(sum(current.mapped("quantity")))
            system = ledger.balance(product, stock, at=self.cutoff_at)
            variance = qty(counted - system)
            missing = []
            if product.rasentra_type == "meat_pack":
                missing = self.env["stock.lot"].sudo().search(
                    [("is_rasentra_pack", "=", True), ("rasentra_outlet_id", "=", self.outlet_id.id),
                     ("product_id", "=", product.id), ("pack_status", "in", COUNTED_PACK_STATUSES),
                     ("id", "not in", current.lot_id.ids)], order="name",
                ).mapped("name")
            report.append(
                {
                    "product_id": product.id,
                    "code": product.default_code,
                    "name": product.name,
                    "uom": product.uom_id.name,
                    "round": round_no,
                    "system": str(system),
                    "counted": str(counted),
                    "variance": str(variance),
                    "flagged": abs(variance) > threshold,
                    "missing_packs": missing,
                }
            )
        return report


class RasentraCountLine(models.Model):
    _name = "rasentra.count.line"
    _description = "Hasil hitung opname"
    _order = "id desc"

    session_id = fields.Many2one("rasentra.count.session", required=True, ondelete="cascade", index=True)
    round = fields.Integer(required=True, default=1, string="Ronde")
    location_id = fields.Many2one("stock.location", required=True, string="Lokasi")
    product_id = fields.Many2one("product.product", required=True, string="Produk")
    lot_id = fields.Many2one("stock.lot", string="Pack ID")
    quantity = fields.Float(digits=(18, 6), required=True, string="Jumlah")
    counted_by_id = fields.Many2one("hr.employee", string="Petugas")
    counted_at = fields.Datetime(default=fields.Datetime.now, readonly=True, string="Waktu hitung")


class RasentraCountSessionActions(models.Model):
    _inherit = "rasentra.count.session"

    def _my_employee(self):
        employee = self.env.user.employee_id
        if not employee:
            raise RasentraError("employee_required", _("Pengguna ini belum terhubung ke karyawan Rasentra."))
        return employee

    @api.model
    def action_open_new(self):
        outlet = self.env["rasentra.profile"].current_outlet() or self.env["rasentra.outlet"].search([], limit=1)
        session = self.open(self._my_employee(), outlet)
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": session.id, "view_mode": "form"}

    def action_review(self):
        self.review(self._my_employee())

    def action_approve(self):
        self.approve(self._my_employee())
