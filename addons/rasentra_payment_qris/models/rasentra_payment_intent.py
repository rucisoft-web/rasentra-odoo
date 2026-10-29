import hashlib

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money

STATUSES = [
    ("pending", "Menunggu pelanggan"),
    ("succeeded", "Berhasil"),
    ("failed", "Gagal"),
    ("uncertain", "Belum pasti (cek status)"),
    ("cancelled", "Dibatalkan"),
]
FINAL = ("succeeded", "failed", "cancelled")


class RasentraPaymentIntent(models.Model):
    """Pembayaran QRIS/EDC terintegrasi (port PaymentService).

    Status "uncertain" (timeout provider) tidak boleh dianggap gagal: kasir wajib cek status ke
    provider sebelum meminta pelanggan membayar ulang. Hasil provider idempoten dan status final
    tidak mundur; nominal berbeda ditolak dan dicatat payment.amount_mismatch.
    Integrasi provider sungguhan (mis. Midtrans/Xendit) masih rancangan; provider "simulasi" dipakai
    untuk uji dan demo.
    """

    _name = "rasentra.payment.intent"
    _inherit = ["rasentra.uuid.mixin"]
    _description = "Pembayaran QRIS/EDC"
    _order = "id desc"
    _rec_name = "provider_ref"

    session_id = fields.Many2one("pos.session", required=True, readonly=True, index=True)
    outlet_id = fields.Many2one(related="session_id.rasentra_outlet_id", store=True)
    order_uuid = fields.Char(required=True, readonly=True, index=True)
    payment_method_id = fields.Many2one("pos.payment.method", required=True, readonly=True)
    method = fields.Char(required=True, readonly=True)
    amount = fields.Float(digits=(18, 2), required=True, readonly=True)
    status = fields.Selection(STATUSES, default="pending", required=True, readonly=True, index=True)
    provider = fields.Char(default="simulasi", readonly=True)
    provider_ref = fields.Char(readonly=True, index=True, copy=False)
    qr_string = fields.Char(readonly=True)
    verified_by_api = fields.Boolean(readonly=True)

    _sql_constraints = [("provider_ref_unique", "unique(provider, provider_ref)", "Referensi provider sudah dipakai.")]

    @api.model
    def start(self, session, order_uuid, method, amount):
        amount = money(amount)
        if amount <= 0:
            raise RasentraError("payment_amount_invalid", _("Nominal pembayaran harus lebih dari nol."))
        intent = self.sudo().create({
            "session_id": session.id, "order_uuid": order_uuid, "payment_method_id": method.id,
            "method": method._rasentra_code(), "amount": float(amount),
        })
        ref = f"RSN-{intent.uuid[-12:].upper()}"
        # Payload QR contoh (bukan EMVCo resmi) sampai provider sungguhan dipasang.
        digest = hashlib.sha256(f"{ref}:{amount}".encode()).hexdigest()[:8].upper()
        intent.write({"provider_ref": ref, "qr_string": f"00020101021226{ref}5303360540{amount}6304{digest}"})
        return intent

    def apply_provider_result(self, status, amount):
        """Hasil dari provider (webhook atau query status). Idempoten.

        Nominal berbeda tidak dilempar sebagai exception agar catatan audit tidak ikut di-rollback;
        pemanggil menerima False dan status pembayaran tidak berubah.
        """
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM rasentra_payment_intent WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if money(amount) != money(self.amount):
            self.env["rasentra.audit.event"].sudo().record(
                "payment.amount_mismatch", self, reason=f"provider={money(amount)}", outlet=self.outlet_id,
                amount=money(amount),
            )
            return False
        if self.status in FINAL:
            return self  # notifikasi berulang atau urutan terbalik: status final tidak mundur
        self.sudo().write({"status": status, "verified_by_api": True})
        return self

    def mark_uncertain(self):
        for intent in self.filtered(lambda i: i.status == "pending"):
            intent.sudo().status = "uncertain"
        return self

    def cancel(self):
        """Batal hanya untuk yang belum pasti dibayar; uncertain harus dicek ke provider dulu."""
        for intent in self:
            if intent.status != "pending":
                raise RasentraError.conflict("payment_not_cancellable", _("Cek status ke provider dulu."))
            intent.sudo().status = "cancelled"
        return self

    def query_provider(self):
        """Tanya status ke provider. Simulasi: status tersimpan apa adanya."""
        self.ensure_one()
        return self.status

    def action_simulate_paid(self):
        """Tombol demo: provider simulasi melaporkan pembayaran berhasil."""
        for intent in self:
            intent.apply_provider_result("succeeded", intent.amount)
        return True

    def _rasentra_wire(self):
        self.ensure_one()
        return {"uuid": self.uuid, "status": self.status, "amount": str(money(self.amount)),
                "provider_ref": self.provider_ref, "qr_string": self.qr_string}
