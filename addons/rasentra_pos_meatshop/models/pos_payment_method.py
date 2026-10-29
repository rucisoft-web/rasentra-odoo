from odoo import api, fields, models

METHODS = [
    ("cash", "Tunai"),
    ("qris", "QRIS"),
    ("edc", "EDC terintegrasi"),
    ("edc_manual", "EDC manual"),
    ("voucher", "Voucher"),
    ("points", "Poin"),
]


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    rasentra_method = fields.Selection(METHODS, string="Metode Rasentra",
                                       help="Kode metode bayar di event order.finalized (sama dengan Laravel).")

    def _rasentra_code(self):
        self.ensure_one()
        return self.rasentra_method or ("cash" if self.is_cash_count else "edc_manual")

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["rasentra_method"]
