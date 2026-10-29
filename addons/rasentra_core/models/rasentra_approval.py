from odoo import _, api, models

from ..tools import RasentraError, to_decimal

APPROVER_ROLES = ("outlet_head", "admin")


class RasentraApproval(models.AbstractModel):
    """Otorisasi supervisor dengan PIN, port dari App\\Domain\\Sales\\Approval.

    PIN mempercepat input di layar sentuh, tetapi tetap divalidasi di server: penyetuju harus
    aktif, satu outlet, berperan supervisor, bukan pembuat transaksi, dan limitnya cukup.
    """

    _name = "rasentra.approval"
    _description = "Approval Rasentra"

    @api.model
    def verify(self, approval, requester, outlet, amount=0):
        """`approval` = {"approver_id": id hr.employee, "pin": "1234"}; `requester` = hr.employee."""
        if not approval or not approval.get("approver_id") or not approval.get("pin"):
            raise RasentraError.needs_approval("approval_required", _("Butuh persetujuan kepala outlet."))
        approver = self.env["hr.employee"].sudo().browse(int(approval["approver_id"])).exists()
        if (
            not approver
            or not approver.active
            or approver.rasentra_role not in APPROVER_ROLES
            or (approver.rasentra_role != "admin" and approver.rasentra_outlet_id != outlet)
            or not approver.pin
            or approver.pin != str(approval["pin"])
        ):
            raise RasentraError.needs_approval("approval_invalid", _("PIN atau penyetuju tidak sah."))
        if requester and approver == requester:
            raise RasentraError.needs_approval("approval_self", _("Penyetuju harus orang yang berbeda."))
        if to_decimal(amount) > to_decimal(approver.approval_limit):
            raise RasentraError.needs_approval("approval_limit", _("Nominal melebihi limit penyetuju."))
        return approver
