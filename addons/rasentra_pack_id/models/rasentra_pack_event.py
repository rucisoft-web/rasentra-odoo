from odoo import fields, models

from .stock_lot import PACK_STATUSES


class RasentraPackEvent(models.Model):
    """Riwayat status Pack ID (padanan pack_events), append-only."""

    _name = "rasentra.pack.event"
    _description = "Riwayat Pack ID"
    _order = "occurred_at desc, id desc"

    lot_id = fields.Many2one("stock.lot", required=True, ondelete="restrict", index=True)
    event = fields.Char(required=True)
    from_status = fields.Selection(PACK_STATUSES)
    to_status = fields.Selection(PACK_STATUSES)
    actor_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    employee_id = fields.Many2one("hr.employee")
    reason = fields.Char()
    source_type = fields.Char()
    source_ref = fields.Char(index=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now)
