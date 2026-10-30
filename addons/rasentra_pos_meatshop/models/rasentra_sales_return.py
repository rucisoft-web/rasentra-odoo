from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty, to_decimal

DISPOSITIONS = [("restock", "Kembali ke stok"), ("quarantine", "Karantina"), ("none", "Tidak kembali ke stok")]
PAID_STATES = ("paid", "done", "invoiced")


class RasentraSalesReturn(models.Model):
    """Retur penjualan dari struk final (port ReturnService).

    Kasir menyiapkan retur lewat RPC (`pos.session.rasentra_return_prepare`): server memeriksa batas
    hari, sisa qty, metode pengembalian, dan PIN kepala outlet, lalu menghitung nilai bersih pro-rata
    (potongan promo ikut kembali sesuai porsinya). Order refund POS baru boleh lunas bila cocok dengan
    retur yang sudah disiapkan; saat itu Pack ID masuk karantina dan event order.returned ke outbox.
    """

    _name = "rasentra.sales.return"
    _inherit = ["rasentra.uuid.mixin"]
    _description = "Retur penjualan Rasentra"
    _order = "id desc"
    _rec_name = "doc_no"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    order_id = fields.Many2one("pos.order", string="Struk asal", required=True, readonly=True, index=True)
    refund_order_uuid = fields.Char(string="UUID order refund POS", required=True, readonly=True, index=True)
    refund_order_id = fields.Many2one("pos.order", string="Order refund", readonly=True)
    session_id = fields.Many2one("pos.session", string="Shift", readonly=True)
    doc_no = fields.Char(string="No. retur", readonly=True, copy=False)
    state = fields.Selection(
        [("prepared", "Disiapkan"), ("done", "Selesai"), ("cancelled", "Batal")],
        default="prepared", required=True, readonly=True, index=True,
    )
    employee_id = fields.Many2one("hr.employee", string="Kasir", readonly=True)
    approver_id = fields.Many2one("hr.employee", string="Disetujui oleh", readonly=True)
    business_date = fields.Date(readonly=True)
    reason = fields.Char(required=True, readonly=True)
    refund_method = fields.Char(required=True, readonly=True)
    refund_ref = fields.Char(readonly=True)
    gross_amount = fields.Float(digits=(18, 2), readonly=True)
    discount_amount = fields.Float(digits=(18, 2), readonly=True)
    net_amount = fields.Float(digits=(18, 2), readonly=True)
    line_ids = fields.One2many("rasentra.sales.return.line", "return_id", readonly=True)

    _sql_constraints = [("doc_no_unique", "unique(doc_no)", "Nomor retur sudah dipakai.")]

    # ---- persiapan -------------------------------------------------------------

    @api.model
    def _return_days(self):
        return int(self.env["ir.config_parameter"].sudo().get_param("rasentra.return_days", "7"))

    @api.model
    def prepare(self, session, refund_order_uuid, order, items, reason, refund_method, employee, approval,
                refund_ref=None):
        """`items` = [{"line_uuid": uuid baris struk asal, "qty": jumlah}]."""
        order = order.sudo()
        if order.state not in PAID_STATES or not order.rasentra_doc_no:
            raise RasentraError.conflict("order_not_final", _("Hanya struk yang sudah selesai yang bisa diretur."))
        outlet = order.rasentra_outlet_id
        today = outlet.business_date()
        days = self._return_days()
        if (today - order.rasentra_business_date).days > days:
            raise RasentraError.conflict("return_expired", _("Retur hanya bisa dalam %s hari sejak transaksi.", days))
        if not (reason or "").strip():
            raise RasentraError("reason_required", _("Alasan retur wajib diisi."))
        if not items:
            raise RasentraError("return_empty", _("Pilih barang yang diretur."))

        sale_lines = order._rasentra_sale_lines()
        rows = []
        for item in items:
            line = sale_lines.filtered(lambda l: l.uuid == item.get("line_uuid"))
            if not line:
                raise RasentraError("return_line_invalid", _("Baris tidak ditemukan pada struk ini."))
            remaining = qty(line.qty) - line._rasentra_returned_qty()
            quantity = qty(item.get("qty"))
            if line._rasentra_pack_code() and quantity != remaining:
                raise RasentraError(
                    "return_pack_whole", _("Pack ID %s diretur utuh (%s kg).", line._rasentra_pack_code(), remaining)
                )
            if quantity <= 0 or quantity > remaining:
                raise RasentraError(
                    "return_quantity",
                    _("Jumlah retur %s melebihi sisa yang bisa diretur (%s).", line.product_id.display_name, remaining),
                )
            rows.append((line, quantity, quantity == remaining))

        lines = [dict(line=line, qty=quantity, **line._rasentra_return_amounts(quantity, last))
                 for line, quantity, last in rows]
        net = sum((l["net"] for l in lines), money(0))
        gross = sum((l["gross"] for l in lines), money(0))
        self._assert_refund_method(order, refund_method, net)
        approver = self.env["rasentra.approval"].sudo().verify(approval, employee, outlet, money(net))

        # Persiapan lama untuk order refund yang sama digantikan (kasir mengubah pilihan baris).
        self.sudo().search([("refund_order_uuid", "=", refund_order_uuid), ("state", "=", "prepared")]).write(
            {"state": "cancelled"}
        )
        record = self.sudo().create({
            "outlet_id": outlet.id,
            "order_id": order.id,
            "refund_order_uuid": refund_order_uuid,
            "session_id": session.id,
            "employee_id": employee.id,
            "approver_id": approver.id,
            "reason": reason.strip(),
            "refund_method": refund_method,
            "refund_ref": refund_ref,
            "gross_amount": float(gross),
            "discount_amount": float(gross - net),
            "net_amount": float(net),
            "line_ids": [
                (0, 0, {
                    "line_no": no,
                    "order_line_id": l["line"].id,
                    "quantity": float(l["qty"]),
                    "gross_amount": float(l["gross"]),
                    "discount_amount": float(l["gross"] - l["net"]),
                    "net_amount": float(l["net"]),
                })
                for no, l in enumerate(lines, start=1)
            ],
        })
        return record

    @api.model
    def refundable(self, order):
        """Sisa nilai yang masih bisa dikembalikan per metode bayar struk ini."""
        paid = {}
        for payment in order.payment_ids:
            code = payment.payment_method_id._rasentra_code()
            paid[code] = paid.get(code, money(0)) + money(payment.amount)
        done = self.sudo().search([("order_id", "=", order.id), ("state", "=", "done")])
        refunded = {}
        for ret in done:
            refunded[ret.refund_method] = refunded.get(ret.refund_method, money(0)) + money(ret.net_amount)
        total = money(order.rasentra_net_amount) - sum(refunded.values(), money(0))
        return {"total": total, **{code: amount - refunded.get(code, money(0)) for code, amount in paid.items()}}

    @api.model
    def _assert_refund_method(self, order, method, net):
        refundable = self.refundable(order)
        if net > refundable["total"]:
            raise RasentraError.conflict("return_exceeds", _("Nilai retur melebihi sisa nilai struk."))
        if method == "cash":
            return  # toko selalu bisa mengembalikan tunai dari laci
        if method not in refundable or net > refundable[method]:
            raise RasentraError(
                "refund_method",
                _("Pengembalian lewat %(m)s melebihi pembayaran %(m)s pada struk ini. Pilih tunai.", m=method),
            )

    # ---- penyelesaian ----------------------------------------------------------

    def _check_refund_order(self, refund_order):
        """Order refund POS harus persis sama dengan retur yang disiapkan."""
        self.ensure_one()
        refunded = refund_order.lines.filtered("refunded_orderline_id")
        expected = {l.order_line_id.id: qty(l.quantity) for l in self.line_ids}
        actual = {}
        for line in refunded:
            actual[line.refunded_orderline_id.id] = actual.get(line.refunded_orderline_id.id, qty(0)) - qty(line.qty)
        if actual != expected:
            raise RasentraError.conflict("return_mismatch", _("Baris refund berbeda dengan retur yang disetujui."))
        if money(refund_order.amount_total) != -money(self.net_amount):
            raise RasentraError.conflict(
                "return_amount_mismatch",
                _("Nilai refund %(a)s berbeda dengan nilai retur %(b)s.", a=-money(refund_order.amount_total),
                  b=money(self.net_amount)),
            )
        methods = {p.payment_method_id._rasentra_code() for p in refund_order.payment_ids}
        if methods - {self.refund_method}:
            raise RasentraError.conflict("refund_method_mismatch", _("Metode pengembalian berbeda dengan yang disetujui."))

    def _finalize(self, refund_order):
        self.ensure_one()
        outlet = self.outlet_id
        self.env.cr.execute("SELECT id FROM rasentra_outlet WHERE id = %s FOR UPDATE", [outlet.id])
        today = refund_order.session_id.rasentra_business_date or outlet.business_date()
        Lot = self.env["stock.lot"].sudo()
        for line in self.line_ids:
            original = line.order_line_id
            # Sisa qty dicek ulang: retur lain bisa selesai di antara persiapan dan pembayaran.
            if qty(line.quantity) > qty(original.qty) - original._rasentra_returned_qty():
                raise RasentraError.conflict("return_quantity", _("Barang ini sudah diretur."))
            line.disposition = original._rasentra_disposition()
            if code := original._rasentra_pack_code():
                Lot.pack_mark_returned(code, self.uuid, self.employee_id, self.reason)
        prefix = f"{outlet.code}-R{today:%y%m%d}-"
        last = self.search([("doc_no", "=like", prefix + "%")], order="doc_no desc", limit=1)
        seq = int(last.doc_no[len(prefix):]) + 1 if last else 1
        self.write({
            "state": "done",
            "doc_no": f"{prefix}{seq:04d}",
            "business_date": today,
            "refund_order_id": refund_order.id,
            "session_id": refund_order.session_id.id,
        })
        refund_order.write({"rasentra_doc_no": self.doc_no, "rasentra_business_date": today})
        self.env["rasentra.sync.outbox"].sudo().record(
            "sales_return", self.uuid, "order.returned", self._payload(), today, outlet=outlet
        )
        self.env["rasentra.audit.event"].sudo().record(
            "order.returned", self, employee=self.employee_id, approver=self.approver_id, reason=self.reason,
            amount=money(self.net_amount), outlet=outlet,
            after={"order": self.order_id.rasentra_doc_no, "refund": self.refund_method, "lines": len(self.line_ids)},
        )

    def _payload(self):
        self.ensure_one()
        order = self.order_id
        line_no = {line.id: no for no, line in enumerate(order._rasentra_sale_lines(), start=1)}
        return {
            "id": self.uuid,
            "doc_no": self.doc_no,
            "original_order_id": order.uuid,
            "original_doc_no": order.rasentra_doc_no,
            "original_business_date": fields.Date.to_string(order.rasentra_business_date),
            "outlet_id": self.outlet_id.code,
            "channel": order.rasentra_channel,
            "business_date": fields.Date.to_string(self.business_date),
            "reason": self.reason,
            "gross_amount": str(money(self.gross_amount)),
            "discount_amount": str(money(self.discount_amount)),
            "net_amount": str(money(self.net_amount)),
            "refund": {"method": self.refund_method, "amount": str(money(self.net_amount)), "ref": self.refund_ref},
            "finalized_at": fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lines": [
                {
                    "line_no": line.line_no,
                    "order_line_no": line_no.get(line.order_line_id.id),
                    "line_type": line.order_line_id.rasentra_line_type or "retail_product",
                    "product_id": line.order_line_id.product_id.default_code,
                    "product_code": line.order_line_id.product_id.default_code,
                    "pack_id": line.order_line_id._rasentra_pack_code() or None,
                    "pack_code": line.order_line_id._rasentra_pack_code() or None,
                    "quantity": str(qty(line.quantity)),
                    "uom": line.order_line_id.product_uom_id.name,
                    "unit_price": str(money(line.order_line_id.price_unit)),
                    "gross_amount": str(money(line.gross_amount)),
                    "discount_amount": str(money(line.discount_amount)),
                    "net_amount": str(money(line.net_amount)),
                    "disposition": line.disposition,
                }
                for line in self.line_ids
            ],
        }


class RasentraSalesReturnLine(models.Model):
    _name = "rasentra.sales.return.line"
    _description = "Baris retur penjualan Rasentra"
    _order = "return_id, line_no"

    return_id = fields.Many2one("rasentra.sales.return", required=True, ondelete="cascade", index=True)
    state = fields.Selection(related="return_id.state", store=True)
    line_no = fields.Integer(required=True)
    order_line_id = fields.Many2one("pos.order.line", string="Baris struk asal", required=True, index=True)
    product_id = fields.Many2one(related="order_line_id.product_id", store=True)
    quantity = fields.Float(digits=(18, 6), required=True)
    gross_amount = fields.Float(digits=(18, 2))
    discount_amount = fields.Float(digits=(18, 2))
    net_amount = fields.Float(digits=(18, 2))
    disposition = fields.Selection(DISPOSITIONS)
