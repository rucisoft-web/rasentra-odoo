from odoo import _, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, to_decimal

PAID_STATES = ("paid", "done", "invoiced")


class PosSession(models.Model):
    """Shift kasir Rasentra memakai sesi POS Odoo (port ShiftService).

    Penutupan tetap bisa dilakukan tanpa koneksi ke Central; posting SAP berjalan terpisah.
    """

    _inherit = "pos.session"

    rasentra_closing_counts = fields.Json(string="Hitungan tutup shift", readonly=True, copy=False)
    rasentra_closing_expected = fields.Json(string="Saldo sistem saat tutup", readonly=True, copy=False)
    rasentra_cash_difference = fields.Float(string="Selisih kas", digits=(18, 2), readonly=True, copy=False)
    rasentra_closed_by_id = fields.Many2one("hr.employee", string="Ditutup oleh", readonly=True, copy=False)
    rasentra_closing_approver_id = fields.Many2one("hr.employee", string="Disetujui oleh", readonly=True, copy=False)

    def _rasentra_applies(self):
        return bool(self.config_id.rasentra_outlet_id)

    # ---- kas masuk/keluar -------------------------------------------------------

    def try_cash_in_out(self, _type, amount, reason, extras):
        rasentra = self.filtered(lambda s: s._rasentra_applies())
        if rasentra and not (reason or "").strip():
            raise RasentraError("reason_required", _("Alasan wajib diisi."))
        res = super().try_cash_in_out(_type, amount, reason, extras)
        employee = self.env["hr.employee"].browse((extras or {}).get("employee_id") or []).exists()
        for session in rasentra:
            self.env["rasentra.audit.event"].sudo().record(
                f"cash.cash_{_type}", session, employee=employee, reason=reason,
                amount=money(amount), outlet=session.rasentra_outlet_id,
            )
        return res

    # ---- saldo sistem -----------------------------------------------------------

    def rasentra_expected(self):
        """Saldo sistem per metode bayar Rasentra. Retur (order refund) sudah bernilai negatif
        di pembayaran sesi yang sama, sehingga langsung mengurangi metode bayarnya."""
        self.ensure_one()
        totals = {}
        orders = self.order_ids.filtered(lambda o: o.state in PAID_STATES)
        # Kembalian tunai tercatat sebagai pembayaran negatif (is_change), jadi ikut dijumlah.
        for payment in orders.payment_ids:
            code = payment.payment_method_id._rasentra_code()
            totals[code] = totals.get(code, money(0)) + money(payment.amount)
        moves = sum((money(line.amount) for line in self.sudo().statement_line_ids), money(0))
        totals["cash"] = money(self.cash_register_balance_start) + totals.get("cash", money(0)) + moves
        return {code: str(money(amount)) for code, amount in totals.items()}

    # ---- tutup shift ------------------------------------------------------------

    def _rasentra_threshold(self):
        value = self.env["ir.config_parameter"].sudo().get_param("rasentra.cash_difference_threshold", "10000")
        return to_decimal(value)

    def rasentra_close_check(self, counts, employee_id=None, approval=None):
        """Catat hitungan kasir per metode bayar (`counts` = {kode metode Rasentra: jumlah}).

        Selisih kas di atas ambang butuh PIN kepala outlet. Mengembalikan {"successful": True}
        atau {"kind": "approval_required", ...} agar POS meminta PIN lalu mengulang.
        """
        self.ensure_one()
        if self.state not in ("opened", "closing_control"):
            raise RasentraError.conflict("shift_not_open", _("Shift sudah ditutup."))
        self.env.cr.execute("SELECT id FROM pos_session WHERE id = %s FOR UPDATE", [self.id])
        expected = self.rasentra_expected()
        counted = {code: str(money(amount)) for code, amount in (counts or {}).items()}
        diff = to_decimal(counted.get("cash", "0")) - to_decimal(expected["cash"])
        employee = self._rasentra_employee(employee_id)
        approver = self.env["hr.employee"]
        if abs(diff) > self._rasentra_threshold():
            try:
                approver = self.env["rasentra.approval"].sudo().verify(
                    approval, employee, self.rasentra_outlet_id, money(abs(diff))
                )
            except RasentraError as error:
                if not error.context.get("approval_required"):
                    raise
                return {"kind": "approval_required", "code": error.code, "message": str(error.args[0]),
                        "difference": str(money(diff))}
        self.sudo().write({
            "rasentra_closing_counts": counted,
            "rasentra_closing_expected": expected,
            "rasentra_cash_difference": float(money(diff)),
            "rasentra_closed_by_id": employee.id,
            "rasentra_closing_approver_id": approver.id,
        })
        self.env["rasentra.audit.event"].sudo().record(
            "shift.closed", self, employee=employee, approver=approver, amount=money(diff),
            outlet=self.rasentra_outlet_id, after={"counts": counted, "expected": expected},
        )
        return {"successful": True, "expected": expected, "difference": str(money(diff))}

    def _rasentra_require_counts(self, counted_cash=None):
        for session in self.filtered(lambda s: s._rasentra_applies()):
            if not session.rasentra_closing_expected:
                raise RasentraError("shift_count_required", _("Hitung kas dan simpan hitungan tutup shift dulu."))
            if counted_cash is not None and money(counted_cash) != money(session.rasentra_closing_counts.get("cash", 0)):
                raise RasentraError("shift_count_changed", _("Hitungan kas berubah; simpan ulang hitungan tutup shift."))

    def post_closing_cash_details(self, counted_cash):
        self._rasentra_require_counts(counted_cash)
        return super().post_closing_cash_details(counted_cash)

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        self._rasentra_require_counts()
        return super().close_session_from_ui(bank_payment_method_diff_pairs)

    def rasentra_report(self):
        """Ringkasan laporan tutup shift untuk dicetak dan ditandatangani kasir serta kepala outlet."""
        self.ensure_one()
        orders = self.order_ids.filtered(lambda o: o.state in PAID_STATES)
        sales = orders.filtered(lambda o: not o.lines.filtered("refunded_orderline_id"))
        returns = orders - sales
        payments, refunds = {}, {}
        for bucket, subset in ((payments, sales), (refunds, returns)):
            for payment in subset.payment_ids:
                code = payment.payment_method_id._rasentra_code()
                bucket[code] = bucket.get(code, money(0)) + money(payment.amount)
        net = sum((money(o.amount_total) for o in sales), money(0))
        returned = -sum((money(o.amount_total) for o in returns), money(0))
        channels = {}
        for order in sales:
            channels[order.rasentra_channel] = channels.get(order.rasentra_channel, 0) + 1
        return {
            "orders": len(sales),
            "gross": str(sum((money(o.rasentra_gross_amount) for o in sales), money(0))),
            "discount": str(sum((money(o.rasentra_discount_amount) for o in sales), money(0))),
            "net": str(net),
            "channels": channels,
            "payments": {k: str(v) for k, v in payments.items()},
            "returns": [{"doc_no": o.rasentra_doc_no or o.name, "amount": str(-money(o.amount_total))} for o in returns],
            "refunds": {k: str(-v) for k, v in refunds.items()},
            "net_after_returns": str(net - returned),
            "movements": [
                {"at": fields.Datetime.to_string(line.create_date), "amount": str(money(line.amount)),
                 "reason": line.payment_ref}
                for line in self.sudo().statement_line_ids.sorted("create_date")
            ],
            "expected": self.rasentra_closing_expected or self.rasentra_expected(),
            "counted": self.rasentra_closing_counts or {},
            "difference": str(money(self.rasentra_cash_difference)),
        }
