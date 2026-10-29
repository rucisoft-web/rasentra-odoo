from odoo import models

from odoo.addons.rasentra_core.tools import RasentraError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _rasentra_cooking_call(self, func):
        try:
            return func()
        except RasentraError as error:
            if not error.context.get("approval_required"):
                raise
            return {"kind": "approval_required", "code": error.code, "message": str(error.args[0])}

    def rasentra_cooking_request(self, order_uuid, pack_code, instructions, employee_id=None):
        """Tambah jasa memasak untuk Pack ID yang sudah di keranjang order ini."""
        self.ensure_one()
        Job = self.env["rasentra.cooking.job"].sudo()
        job = Job.request_for_pack(self.rasentra_outlet_id, order_uuid, pack_code, instructions or {},
                                   self._rasentra_employee(employee_id))
        return job._to_pos()

    def rasentra_cooking_from_receipt(self, order_uuid, receipt_doc_no, pack_code, instructions, employee_id=None):
        """Masak daging yang sudah dibayar di kasir retail: hanya jasa yang ditagih."""
        self.ensure_one()
        result = self.env["rasentra.cooking.job"].sudo().request_from_receipt(
            self.rasentra_outlet_id, order_uuid, receipt_doc_no, pack_code, instructions or {},
            self._rasentra_employee(employee_id))
        return result if isinstance(result, dict) else result._to_pos()

    def rasentra_cooking_cancel(self, job_uuid, reason, employee_id=None, approval=None):
        self.ensure_one()
        job = self.env["rasentra.cooking.job"].sudo().search([("uuid", "=", job_uuid)], limit=1)
        if not job:
            return {"kind": "cancelled", "status": "unknown", "remove_pack": False}
        return self._rasentra_cooking_call(
            lambda: job.cancel(self._rasentra_employee(employee_id), reason, approval))
