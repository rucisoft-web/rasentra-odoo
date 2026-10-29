from odoo import api, fields, models

COURSES = [("starter", "Pembuka"), ("main", "Utama"), ("dessert", "Penutup"), ("drink", "Minuman")]


class PosOrder(models.Model):
    _inherit = "pos.order"

    rasentra_queue_no = fields.Integer(string="No. antrean", readonly=True, copy=False)
    rasentra_kitchen_ticket_ids = fields.One2many("rasentra.kitchen.ticket", "pos_order_id", string="Tiket dapur")
    rasentra_split_pending = fields.Boolean(readonly=True, copy=False)

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_ = super()._load_pos_data_fields(config_id)
        return fields_ + ["rasentra_queue_no"] if fields_ else fields_


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    rasentra_course = fields.Selection(COURSES, string="Course")

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["rasentra_course"]

    def unlink(self):
        # Baris yang sudah dikirim ke dapur lalu dihapus kasir: batal atau minta batal di KDS.
        sent = self.filtered(lambda l: l.uuid and l.order_id.state == "draft" and not l.order_id.rasentra_split_pending)
        if sent:
            self.env["rasentra.kitchen"].sudo().line_voided(sent.mapped("uuid"), sent.order_id.employee_id[:1])
        return super().unlink()


class PosSession(models.Model):
    _inherit = "pos.session"

    def rasentra_kitchen_send(self, order_uuid, course=None):
        """Kirim ke Dapur dari POS restoran: hanya item baru atau tambahan kuantitas."""
        self.ensure_one()
        order = self.env["pos.order"].sudo().search([("uuid", "=", order_uuid)], limit=1)
        if not order:
            return {"tickets": 0}
        tickets = self.env["rasentra.kitchen"].send(order, course or None)
        return {"tickets": len(tickets), "stations": sorted(set(tickets.mapped("station"))),
                "bump_codes": tickets.mapped("bump_code"), "queue_no": order.rasentra_queue_no or None}


    def rasentra_kitchen_split_begin(self, order_uuid):
        """Split bill dimulai: penghapusan baris order asal tidak dianggap void dapur."""
        self.ensure_one()
        self.env["pos.order"].sudo().search([("uuid", "=", order_uuid)]).write({"rasentra_split_pending": True})
        return True

    def rasentra_kitchen_split_done(self, original_uuid, new_uuid, moves):
        self.ensure_one()
        Order = self.env["pos.order"].sudo()
        original = Order.search([("uuid", "=", original_uuid)], limit=1)
        new = Order.search([("uuid", "=", new_uuid)], limit=1)
        self.env["rasentra.kitchen"].split_transfer(original, new, moves or [])
        original.write({"rasentra_split_pending": False})
        return True


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    rasentra_modifier_key = fields.Char(
        string="Kunci modifier resep",
        help="Dipakai penguraian resep, mis. extra_butter atau without:BH-ONION (tanpa bawang).")
