from odoo import fields, models

from odoo.addons.rasentra_core.models.product_template import KITCHEN_STATIONS

ITEM_STATUSES = [
    ("queued", "Baru"),
    ("acknowledged", "Diterima"),
    ("in_preparation", "Dimasak"),
    ("ready", "Siap"),
    ("served", "Disajikan"),
    ("cancel_requested", "Minta batal"),
    ("cancelled", "Batal"),
]


class RasentraKitchenTicket(models.Model):
    """Satu kiriman ke satu station (padanan kitchen_tickets). Kode bump dicetak sebagai barcode."""

    _name = "rasentra.kitchen.ticket"
    _description = "Tiket dapur"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "id"
    _rec_name = "bump_code"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, index=True)
    pos_order_id = fields.Many2one("pos.order", index=True, ondelete="set null")
    order_uuid = fields.Char(required=True, index=True)
    station = fields.Selection(KITCHEN_STATIONS, required=True, index=True)
    sequence = fields.Integer(default=1)
    bump_code = fields.Char(required=True, index=True)
    label = fields.Char()
    channel = fields.Char()
    course = fields.Char()
    item_ids = fields.One2many("rasentra.kitchen.item", "ticket_id")

    _sql_constraints = [("bump_code_unique", "unique(bump_code)", "Kode bump sudah dipakai.")]


class RasentraKitchenItem(models.Model):
    """Satu baris pesanan di satu tiket (padanan ticket_items). Kuantitas = delta yang dikirim."""

    _name = "rasentra.kitchen.item"
    _description = "Item dapur"
    _order = "id"

    ticket_id = fields.Many2one("rasentra.kitchen.ticket", required=True, ondelete="cascade", index=True)
    outlet_id = fields.Many2one(related="ticket_id.outlet_id", store=True)
    station = fields.Selection(related="ticket_id.station", store=True)
    line_uuid = fields.Char(required=True, index=True)
    pos_order_line_id = fields.Many2one("pos.order.line", ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(digits=(18, 3), required=True)
    instructions = fields.Json()
    modifier_keys = fields.Json()
    cooking_job_uuid = fields.Char(index=True)
    status = fields.Selection(ITEM_STATUSES, default="queued", required=True, index=True)
    acknowledged_at = fields.Datetime()
    started_at = fields.Datetime()
    ready_at = fields.Datetime()
    served_at = fields.Datetime()
    bumped_by_id = fields.Many2one("hr.employee")
    cancel_reason = fields.Char()
    recipe_version_id = fields.Many2one("rasentra.recipe.version", string="Versi resep dipakai")
