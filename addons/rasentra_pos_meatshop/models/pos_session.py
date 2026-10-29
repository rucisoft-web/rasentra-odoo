from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty


class PosSession(models.Model):
    _inherit = "pos.session"

    rasentra_outlet_id = fields.Many2one(related="config_id.rasentra_outlet_id", store=True)
    rasentra_business_date = fields.Date(string="Tanggal bisnis", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for session in sessions.filtered("rasentra_outlet_id"):
            session.rasentra_business_date = session.rasentra_outlet_id.business_date()
        return sessions

    def _rasentra_employee(self, employee_id):
        return self.env["hr.employee"].sudo().browse(int(employee_id)).exists() if employee_id else self.env["hr.employee"]

    # ---- RPC dari POS ---------------------------------------------------------

    def rasentra_scan(self, code, order_uuid, employee_id=None, approval=None):
        """Satu kolom scan: Pack ID dikunci di server; selain itu kembalikan False agar POS
        memakai pencarian barcode biasa (SKU dan barcode timbangan)."""
        self.ensure_one()
        lot = self.env["stock.lot"].sudo().search([("name", "=", code), ("is_rasentra_pack", "=", True)], limit=1)
        if not lot:
            return False
        try:
            result = self.env["stock.lot"].sudo().pack_reserve(
                code, order_uuid, self.rasentra_outlet_id, self._rasentra_employee(employee_id),
                self.config_id.rasentra_channel, approval,
            )
        except RasentraError as error:
            if not error.context.get("approval_required"):
                raise
            # Kemasan hold/kedaluwarsa: POS meminta PIN kepala outlet lalu memindai ulang.
            return {"kind": "approval_required", "code": error.code, "message": str(error.args[0])}
        return {"kind": "pack", **result}

    def rasentra_release(self, code, order_uuid, employee_id=None, reason=None):
        self.ensure_one()
        return self.env["stock.lot"].sudo().pack_release(code, order_uuid, self._rasentra_employee(employee_id), reason)

    def rasentra_evaluate(self, lines):
        """Hitung promo untuk keranjang POS. `lines` = [{uuid, product_id, qty, price_unit}].

        Mengembalikan diskon per baris dan total per versi promo; POS menulisnya sebagai baris
        produk "Diskon promo" bernilai negatif agar total struk sama dengan yang dibayar.
        """
        self.ensure_one()
        Product = self.env["product.product"].sudo()
        engine_lines = [
            self.env["rasentra.promotion.version"].engine_line(
                line["uuid"], Product.browse(int(line["product_id"])), line["qty"], line["price_unit"],
                money(qty(line["qty"]) * money(line["price_unit"])),
            )
            for line in lines
        ]
        return self._rasentra_evaluate(engine_lines)

    def _rasentra_evaluate(self, engine_lines):
        Version = self.env["rasentra.promotion.version"].sudo()
        versions = Version.active_for(self.rasentra_outlet_id, self.config_id.rasentra_channel)
        result = Version.evaluate(engine_lines, versions)
        by_uuid = {v.uuid: v for v in versions}
        totals = {}
        for line in result["lines"].values():
            for allocation in line["allocations"]:
                key = allocation["promotion_version_id"]
                totals[key] = totals.get(key, money(0)) + money(allocation["amount"])
        result["promotions"] = [
            {"uuid": key, "name": by_uuid[key].display_name + " " + by_uuid[key].name, "amount": str(amount)}
            for key, amount in totals.items()
        ]
        return result
