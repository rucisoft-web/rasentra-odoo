from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money


class PosOrder(models.Model):
    _inherit = "pos.order"

    rasentra_cooking_job_ids = fields.One2many("rasentra.cooking.job", "pos_order_id", string="Cooking job")

    def _rasentra_check_before_paid(self):
        super()._rasentra_check_before_paid()
        Job = self.env["rasentra.cooking.job"].sudo()
        for line in self.lines.filtered("rasentra_cooking_job_uuid"):
            job = Job.search([("uuid", "=", line.rasentra_cooking_job_uuid)], limit=1)
            if not job or job.order_uuid != self.uuid:
                raise RasentraError("cooking_job_unknown", _("Cooking job baris %s tidak dikenal.", line.full_product_name))
            if job.status.startswith("cancelled"):
                raise RasentraError.conflict("cooking_job_cancelled", _("Cooking job sudah dibatalkan; hapus baris jasanya."))
            if money(line.price_subtotal_incl) != money(job.fee_amount):
                raise RasentraError.conflict(
                    "cooking_fee_mismatch",
                    _("Nilai jasa masak harus %(fee)s sesuai aturan tarif.", fee=money(job.fee_amount)))

    def _rasentra_finalize(self):
        res = super()._rasentra_finalize()
        Job = self.env["rasentra.cooking.job"].sudo()
        for line in self.lines.filtered("rasentra_cooking_job_uuid"):
            Job.search([("uuid", "=", line.rasentra_cooking_job_uuid)]).write(
                {"pos_order_id": self.id, "service_line_uuid": line.uuid})
        return res

    def _rasentra_payload(self):
        payload = super()._rasentra_payload()
        jobs = {line.uuid: line.rasentra_cooking_job_uuid for line in self.lines if line.rasentra_cooking_job_uuid}
        for line in payload.get("lines") or []:
            if line["id"] in jobs:
                line["cooking_job_id"] = jobs[line["id"]]
        return payload


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    rasentra_cooking_job_uuid = fields.Char(string="Cooking job", index=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["rasentra_cooking_job_uuid"]

    def _rasentra_promo_eligible(self):
        # Diskon daging tidak mendiskon jasa memasak.
        return not self.rasentra_cooking_job_uuid and super()._rasentra_promo_eligible()
