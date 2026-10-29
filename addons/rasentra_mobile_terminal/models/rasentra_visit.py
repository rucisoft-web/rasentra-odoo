import secrets

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money


class RasentraVisit(models.Model):
    """Kunjungan tamu di satu meja (port Visit + TableService). Setiap kunjungan punya token sendiri,
    sehingga pesanan tidak pernah masuk ke tamu sebelumnya setelah meja dibayar dan dibuka lagi."""

    _name = "rasentra.visit"
    _description = "Kunjungan meja"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "id desc"
    _rec_name = "visit_token"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    table_id = fields.Many2one("restaurant.table", required=True, readonly=True, index=True)
    visit_token = fields.Char(required=True, readonly=True, copy=False, index=True,
                              default=lambda self: secrets.token_hex(32))
    guest_count = fields.Integer(readonly=True)
    waiter_id = fields.Many2one("hr.employee", string="Pelayan", readonly=True)
    status = fields.Selection([("open", "Buka"), ("closed", "Tutup")], default="open", required=True, readonly=True,
                              index=True)
    opened_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    bill_requested_at = fields.Datetime(readonly=True)
    closed_at = fields.Datetime(readonly=True)
    order_ids = fields.One2many("pos.order", "rasentra_visit_id", string="Pesanan")
    amount_total = fields.Float(compute="_compute_amount_total", digits=(18, 2))

    _sql_constraints = [("token_unique", "unique(visit_token)", "Token kunjungan harus unik.")]

    def _compute_amount_total(self):
        for visit in self:
            visit.amount_total = sum(visit.order_ids.mapped("amount_total"))

    def init(self):
        # Satu kunjungan terbuka per meja (padanan kunci meja Laravel).
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS rasentra_visit_open_table_uniq "
            "ON rasentra_visit (table_id) WHERE status = 'open'"
        )

    @api.model
    def open_for(self, order):
        """Buka kunjungan saat order meja pertama kali tersimpan; order lain di meja yang sama ikut kunjungan itu."""
        table = order.table_id
        visit = self.search([("table_id", "=", table.id), ("status", "=", "open")], limit=1)
        if visit:
            return visit
        visit = self.create({
            "outlet_id": order.config_id.rasentra_outlet_id.id, "table_id": table.id,
            "guest_count": order.customer_count, "waiter_id": order.employee_id.id or False,
        })
        self.env["rasentra.audit.event"].record(
            "table.opened", visit, employee=order.employee_id, outlet=visit.outlet_id,
            after={"table": table.table_number, "guests": order.customer_count})
        return visit

    def move_to(self, table, employee=None):
        self.ensure_one()
        if table.floor_id.pos_config_ids and self.table_id.floor_id.pos_config_ids and \
                not (table.floor_id.pos_config_ids & self.table_id.floor_id.pos_config_ids):
            raise RasentraError("table_unknown", _("Meja tujuan tidak ditemukan di outlet ini."), 404)
        before = self.table_id.table_number
        self.write({"table_id": table.id})
        self.env["rasentra.audit.event"].record("table.moved", self, employee=employee, outlet=self.outlet_id,
                                                before={"table": before}, after={"table": table.table_number})

    def request_bill(self, employee=None):
        self.ensure_one()
        if self.status != "open":
            raise RasentraError.conflict("visit_closed", _("Meja ini sudah dibayar dan ditutup."))
        orders = self.order_ids.filtered(lambda o: o.state == "draft")
        if not orders.lines:
            raise RasentraError.conflict("order_empty", _("Belum ada pesanan untuk ditagih."))
        if not self.bill_requested_at:
            self.write({"bill_requested_at": fields.Datetime.now()})
        self.env["rasentra.audit.event"].record("table.bill_requested", self, employee=employee, outlet=self.outlet_id,
                                                amount=money(sum(orders.mapped("amount_total"))))
        return self

    def _close_if_done(self, empty=False):
        for visit in self.filtered(lambda v: v.status == "open"):
            if any(o.state == "draft" for o in visit.order_ids):
                continue
            visit.write({"status": "closed", "closed_at": fields.Datetime.now()})
            self.env["rasentra.audit.event"].record("table.closed_empty" if empty else "table.closed", visit,
                                                    outlet=visit.outlet_id)


class PosOrder(models.Model):
    _inherit = "pos.order"

    rasentra_visit_id = fields.Many2one("rasentra.visit", string="Kunjungan", readonly=True, index=True, copy=False)

    def _rasentra_sync_visit(self):
        Visit = self.env["rasentra.visit"].sudo()
        for order in self.sudo():
            if not order.config_id.rasentra_outlet_id or not order.table_id:
                continue
            if order.state == "draft":
                if not order.rasentra_visit_id or order.rasentra_visit_id.status != "open":
                    order.rasentra_visit_id = Visit.open_for(order)
                elif order.rasentra_visit_id.table_id != order.table_id:
                    target = Visit.search([("table_id", "=", order.table_id.id), ("status", "=", "open")], limit=1)
                    if target:
                        # Pindah ke meja yang sudah terisi = gabung ke kunjungan meja itu.
                        old = order.rasentra_visit_id
                        order.rasentra_visit_id = target
                        self.env["rasentra.audit.event"].record(
                            "table.merged", target, employee=order.employee_id, outlet=target.outlet_id,
                            before={"table": old.table_id.table_number}, after={"table": order.table_id.table_number})
                        old._close_if_done()
                    else:
                        order.rasentra_visit_id.move_to(order.table_id, order.employee_id)
                if order.customer_count and order.rasentra_visit_id.guest_count != order.customer_count:
                    order.rasentra_visit_id.write({"guest_count": order.customer_count})
            elif order.rasentra_visit_id:
                order.rasentra_visit_id._close_if_done(empty=order.state == "cancel" and not order.lines)

    def _process_saved_order(self, draft):
        res = super()._process_saved_order(draft)
        self._rasentra_sync_visit()
        return res

    def write(self, vals):
        res = super().write(vals)
        if "state" in vals or "table_id" in vals:
            self.filtered("rasentra_visit_id")._rasentra_sync_visit()
        return res

    def unlink(self):
        visits = self.sudo().mapped("rasentra_visit_id")
        res = super().unlink()
        visits.exists()._close_if_done(empty=True)
        return res


class PosSession(models.Model):
    _inherit = "pos.session"

    def rasentra_table_map(self):
        """Peta meja untuk tablet: kosong / terisi / minta tagihan, item siap dan sedang dimasak, belum dikirim."""
        self.ensure_one()
        outlet = self.rasentra_outlet_id
        visits = self.env["rasentra.visit"].sudo().search([("outlet_id", "=", outlet.id), ("status", "=", "open")])
        Item = self.env["rasentra.kitchen.item"].sudo()
        result = {}
        for visit in visits:
            orders = visit.order_ids.filtered(lambda o: o.state == "draft")
            items = Item.search([("ticket_id.order_uuid", "in", orders.mapped("uuid"))])
            sent_lines = set(items.mapped("line_uuid"))
            unsent = len(orders.lines.filtered(lambda l: l.product_id.kitchen_station and l.uuid not in sent_lines))
            result[visit.table_id.id] = {
                "status": "billing" if visit.bill_requested_at else "occupied",
                "guests": visit.guest_count,
                "waiter": visit.waiter_id.name or None,
                "opened_at": fields.Datetime.to_string(visit.opened_at),
                "amount": str(money(sum(orders.mapped("amount_total")))),
                "ready": len(items.filtered(lambda i: i.status == "ready")),
                "cooking": len(items.filtered(lambda i: i.status in ("queued", "acknowledged", "in_preparation"))),
                "unsent": unsent,
            }
        return result

    def rasentra_request_bill(self, order_uuid, employee_id=None):
        self.ensure_one()
        order = self.env["pos.order"].sudo().search([("uuid", "=", order_uuid)], limit=1)
        if not order.rasentra_visit_id:
            return False
        order.rasentra_visit_id.request_bill(self._rasentra_employee(employee_id))
        return True
