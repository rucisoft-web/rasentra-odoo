from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty

from .rasentra_cooking_fee_rule import COOKING_METHODS

JOB_STATUSES = [
    ("requested", "Diminta"),
    ("pack_handed_over", "Pack diserahkan ke dapur"),
    ("cooking", "Dimasak"),
    ("served", "Disajikan"),
    ("cancelled_before_cook", "Batal sebelum masak"),
    ("cancelled_after_cook", "Batal setelah masak"),
]
DONENESS = [("rare", "Rare"), ("medium_rare", "Medium rare"), ("medium", "Medium"), ("medium_well", "Medium well"),
            ("well_done", "Well done")]
ACTIVE = ("requested", "pack_handed_over", "cooking", "served")


class RasentraCookingJob(models.Model):
    """Permintaan memasak satu Pack ID (port CookingJob + CookingService). Daging dijual satu kali sebagai
    baris retail berdasarkan Pack ID; jasa memasak adalah baris terpisah (cooking_service)."""

    _name = "rasentra.cooking.job"
    _description = "Cooking job"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "id desc"
    _rec_name = "uuid"

    outlet_id = fields.Many2one("rasentra.outlet", required=True, readonly=True, index=True)
    order_uuid = fields.Char(required=True, readonly=True, index=True, help="uuid pos.order restoran yang menagih jasa")
    pos_order_id = fields.Many2one("pos.order", readonly=True, index=True)
    service_line_uuid = fields.Char(readonly=True, index=True)
    lot_id = fields.Many2one("stock.lot", string="Pack ID", required=True, readonly=True, index=True)
    entitlement_id = fields.Many2one("rasentra.service.entitlement", readonly=True)
    raw_weight = fields.Float(digits=(18, 6), readonly=True)
    portions = fields.Integer(default=1, readonly=True)
    method = fields.Selection(COOKING_METHODS, readonly=True)
    doneness = fields.Selection(DONENESS, readonly=True)
    sauce = fields.Char(readonly=True)
    allergy_note = fields.Char(readonly=True)
    rule_id = fields.Many2one("rasentra.cooking.fee.rule", readonly=True)
    rule_version = fields.Integer(readonly=True)
    fee_amount = fields.Float(digits=(18, 2), readonly=True)
    status = fields.Selection(JOB_STATUSES, default="requested", required=True, readonly=True, index=True)
    handed_over_by_id = fields.Many2one("hr.employee", readonly=True)
    requested_by_id = fields.Many2one("hr.employee", readonly=True)
    cancel_reason = fields.Char(readonly=True)

    def _instructions(self):
        self.ensure_one()
        return {k: v for k, v in {
            "pack_id": self.lot_id.name, "raw_weight": str(qty(self.raw_weight)), "portions": self.portions,
            "method": self.method or None, "doneness": self.doneness or None, "sauce": self.sauce or None,
            "allergy": self.allergy_note or None,
        }.items() if v}

    def _to_pos(self):
        self.ensure_one()
        rule = self.rule_id
        return {
            "kind": "job",
            "job_uuid": self.uuid,
            "fee": str(money(self.fee_amount)),
            "service_product_id": rule.service_product_id.id,
            "label": f"{rule.service_product_id.name} {rule.quantity_label(self.raw_weight, self.portions)}",
            "pack_code": self.lot_id.name,
            "from_receipt": bool(self.entitlement_id),
        }

    # ---- membuat job -------------------------------------------------------------------

    @api.model
    def _create_job(self, outlet, order_uuid, pack, raw_weight, instructions, employee, entitlement=None):
        rule = self.env["rasentra.cooking.fee.rule"].rule_for(outlet, instructions.get("method"))
        portions = max(1, int(instructions.get("portions") or 1))
        return self.sudo().create({
            "outlet_id": outlet.id,
            "order_uuid": order_uuid,
            "lot_id": pack.id,
            "entitlement_id": entitlement.id if entitlement else False,
            "raw_weight": float(qty(raw_weight)),
            "portions": portions,
            "method": instructions.get("method") or False,
            "doneness": instructions.get("doneness") or False,
            "sauce": instructions.get("sauce") or False,
            "allergy_note": instructions.get("allergy_note") or False,
            "rule_id": rule.id,
            "rule_version": rule.version,
            "fee_amount": float(rule.fee(raw_weight, portions)),
            "requested_by_id": employee.id if employee else False,
        })

    @api.model
    def request_for_pack(self, outlet, order_uuid, pack_code, instructions, employee=None):
        """Daging belum dibayar: pack sudah di keranjang order ini (reserved), tambahkan jasa memasak."""
        pack = self.env["stock.lot"]._lock_pack(pack_code)
        if pack.pack_status != "reserved" or pack.reserved_order_uuid != order_uuid:
            raise RasentraError("not_pack_line", _("Cooking fee hanya untuk baris kemasan daging di keranjang ini."))
        if self.search_count([("lot_id", "=", pack.id), ("status", "in", ACTIVE)]):
            raise RasentraError.conflict("pack_already_has_job", _("Kemasan ini sudah dipesan untuk dimasak."))
        return self._create_job(outlet, order_uuid, pack, pack.net_weight, instructions, employee)

    @api.model
    def request_from_receipt(self, outlet, order_uuid, receipt_doc_no, pack_code, instructions, employee=None):
        """Daging sudah dibayar di kasir retail: restoran memakai struk + Pack ID asal dan hanya menagih
        jasa/tambahan. Hak layanan dipakai sekali; pemakaian ulang ditolak dan diaudit."""
        receipt = self.env["pos.order"].sudo().search(
            [("rasentra_outlet_id", "=", outlet.id), ("rasentra_doc_no", "=", (receipt_doc_no or "").strip()),
             ("state", "in", ("paid", "done", "invoiced"))], limit=1)
        if not receipt:
            raise RasentraError("receipt_not_found", _("Struk tidak ditemukan atau belum lunas di outlet ini."), 404)
        line = receipt.lines.filtered(lambda l: l._rasentra_pack_code() == (pack_code or "").strip())[:1]
        if not line:
            raise RasentraError.conflict("pack_not_on_receipt", _("Kemasan tidak tercantum pada struk tersebut."))
        pack = self.env["stock.lot"]._lock_pack(pack_code)
        Entitlement = self.env["rasentra.service.entitlement"].sudo()
        entitlement = Entitlement.search([("receipt_order_id", "=", receipt.id), ("lot_id", "=", pack.id)], limit=1)
        if entitlement:
            self.env.cr.execute("SELECT id FROM rasentra_service_entitlement WHERE id = %s FOR UPDATE", [entitlement.id])
            entitlement.invalidate_recordset()
        else:
            entitlement = Entitlement.create({"receipt_order_id": receipt.id, "lot_id": pack.id,
                                              "remaining_weight": line.qty, "status": "open"})
        if entitlement.status != "open":
            self.env["rasentra.audit.event"].record(
                "cooking.entitlement_reuse_blocked", entitlement, employee=employee, outlet=outlet,
                after={"receipt": receipt.rasentra_doc_no, "pack": pack.name, "order_uuid": order_uuid})
            return {"kind": "blocked", "code": "entitlement_used",
                    "message": _("Hak layanan untuk struk dan Pack ID ini sudah dipakai.")}
        job = self._create_job(outlet, order_uuid, pack, line.qty, instructions, employee, entitlement)
        entitlement.write({"status": "used", "remaining_weight": 0})
        return job

    # ---- dapur & pembatalan --------------------------------------------------------------

    def hand_over(self, employee):
        for job in self.sudo().filtered(lambda j: j.status == "requested"):
            job.write({"status": "pack_handed_over", "handed_over_by_id": employee.id if employee else False})
        return self

    def mark_cooking(self):
        self.sudo().filtered(lambda j: j.status in ("requested", "pack_handed_over")).write({"status": "cooking"})

    def mark_served(self):
        self.sudo().filtered(lambda j: j.status in ACTIVE).write({"status": "served"})

    def cancel(self, employee, reason, approval=None):
        """Sebelum dimasak: jasa batal, pack tetap milik keranjang (atau hak layanan dibuka lagi).
        Sesudah dimasak: butuh PIN kepala outlet; daging belum terjual dicatat sebagai waste dan tidak
        kembali tersedia. Mengembalikan dict untuk POS: baris mana yang harus dihapus."""
        self.ensure_one()
        if not (reason or "").strip():
            raise RasentraError("reason_required", _("Alasan wajib diisi."))
        self.env.cr.execute("SELECT id FROM rasentra_cooking_job WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if self.status in ("cancelled_before_cook", "cancelled_after_cook"):
            return {"kind": "cancelled", "status": self.status, "remove_pack": False}
        if self.status in ("requested", "pack_handed_over"):
            self.write({"status": "cancelled_before_cook", "cancel_reason": reason})
            if self.entitlement_id:
                self.entitlement_id.write({"status": "open", "remaining_weight": self.raw_weight})
            self.env["rasentra.audit.event"].record("cooking.cancel_before_cook", self, employee=employee,
                                                    reason=reason, outlet=self.outlet_id)
            return {"kind": "cancelled", "status": self.status, "remove_pack": False}

        approver = self.env["rasentra.approval"].verify(approval, employee, self.outlet_id)
        pack = self.env["stock.lot"]._lock_pack(self.lot_id.name)
        remove_pack = False
        if pack.pack_status != "sold":
            # Daging belum terjual tetapi sudah dimasak: keluar sebagai waste, tidak kembali tersedia.
            ledger = self.env["rasentra.stock.ledger"]
            source = self.env["rasentra.inventory"]._pack_location(pack, self.outlet_id)
            doc = self.env["rasentra.stock.adjustment"].record(
                "waste", self.outlet_id,
                [{"product": pack.product_id, "pack": pack, "quantity": pack.net_weight, "from_state": "available",
                  "to_state": None}],
                employee=employee, approver=approver, reason=_("Batal setelah dimasak: %s", reason),
                source_type="cooking_job", source_ref=self.uuid)
            doc.move_ids = [(6, 0, ledger.move(pack.product_id, pack.net_weight, source,
                                               ledger.virtual(self.outlet_id.company_id, "scrap"), doc.doc_no, lot=pack).ids)]
            pack._pack_event("consumed_cancelled", "damaged", employee, "cooking_job", self.uuid, reason)
            pack.write({"pack_status": "damaged", "reserved_order_uuid": False})
            remove_pack = True
        self.write({"status": "cancelled_after_cook", "cancel_reason": reason})
        self.env["rasentra.audit.event"].record("cooking.cancel_after_cook", self, employee=employee, approver=approver,
                                                reason=reason, outlet=self.outlet_id)
        return {"kind": "cancelled", "status": self.status, "remove_pack": remove_pack, "pack_code": pack.name}


class RasentraServiceEntitlement(models.Model):
    """Hak layanan masak dari struk retail yang sudah lunas: satu struk + Pack ID dipakai sekali."""

    _name = "rasentra.service.entitlement"
    _description = "Hak layanan masak"
    _order = "id desc"

    receipt_order_id = fields.Many2one("pos.order", required=True, readonly=True, index=True)
    lot_id = fields.Many2one("stock.lot", string="Pack ID", required=True, readonly=True)
    remaining_weight = fields.Float(digits=(18, 6), readonly=True)
    status = fields.Selection([("open", "Terbuka"), ("used", "Terpakai")], default="open", required=True, readonly=True)
    outlet_id = fields.Many2one(related="receipt_order_id.rasentra_outlet_id")

    _sql_constraints = [("receipt_pack_unique", "unique(receipt_order_id, lot_id)",
                         "Hak layanan untuk struk dan Pack ID ini sudah ada.")]
