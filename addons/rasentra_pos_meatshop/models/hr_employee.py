from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def _load_pos_data_fields(self, config_id):
        # Peran dipakai POS untuk memilih penyetuju (kepala outlet) saat override kemasan.
        return super()._load_pos_data_fields(config_id) + ["rasentra_role"]
