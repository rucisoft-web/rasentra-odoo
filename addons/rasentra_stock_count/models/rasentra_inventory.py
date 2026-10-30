from datetime import timedelta

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.models.rasentra_approval import APPROVER_ROLES
from odoo.addons.rasentra_core.tools import RasentraError, qty

PACK_IN_QUARANTINE = ("quarantine", "damaged")
PACK_ON_HAND = ("received", "available", "hold")


class RasentraInventory(models.AbstractModel):
    """Rasentra Inventory Lokal: penerimaan, karantina, waste dan cek stok.

    Port ReceivingService dan StockAdjustmentService. Petugas memakai handheld; setiap keputusan
    stok butuh kepala outlet (langsung, atau PIN bila dilakukan petugas gudang).
    """

    _name = "rasentra.inventory"
    _description = "Rasentra Inventory"

    # ------------------------------------------------------------------ helpers

    @api.model
    def _ledger(self):
        return self.env["rasentra.stock.ledger"]

    @api.model
    def _pack_location(self, pack, outlet):
        """Lokasi internal tempat pack berada sekarang (quant positif), default stok jual outlet."""
        quant = self.env["stock.quant"].sudo().search(
            [("lot_id", "=", pack.id), ("quantity", ">", 0), ("location_id.usage", "=", "internal")], limit=1
        )
        return quant.location_id or self._ledger().location(outlet, "stock")

    @api.model
    def _approver(self, employee, approval, outlet):
        if employee and employee.rasentra_role in APPROVER_ROLES and (
            employee.rasentra_outlet_id == outlet or employee.rasentra_role == "admin"
        ):
            return employee
        return self.env["rasentra.approval"].verify(approval, employee, outlet)

    @api.model
    def _own_pack(self, code, outlet):
        pack = self.env["stock.lot"]._lock_pack(code)
        if pack.rasentra_outlet_id != outlet:
            raise RasentraError.conflict("pack_other_outlet", _("Pack %s bukan milik outlet ini.", code))
        return pack

    @api.model
    def _product_by_code(self, code):
        product = self.env["product.product"].sudo().search(
            ["|", ("default_code", "=", code), ("barcode", "=", code)], limit=1
        )
        if not product:
            raise RasentraError("code_unknown", _("Kode %s tidak dikenal.", code), 404)
        return product

    # ------------------------------------------------------------------ penerimaan

    @api.model
    def expected(self, outlet):
        """Pack dalam perjalanan ke outlet ini (belum discan terima)."""
        return self.env["stock.lot"].sudo().search(
            [("is_rasentra_pack", "=", True), ("rasentra_outlet_id", "=", outlet.id),
             ("pack_status", "in", ("shipped", "allocated"))], order="name",
        )

    @api.model
    def receive(self, outlet, code, employee, action="accept", reason=None):
        """Scan terima satu Pack ID. Tolak = masuk karantina tanpa menambah stok jual."""
        Lot = self.env["stock.lot"]
        pack = Lot._lock_pack((code or "").strip())
        if pack.rasentra_outlet_id != outlet:
            raise RasentraError.conflict("pack_other_outlet", _("Pack %s bukan kiriman untuk outlet ini.", code))
        if pack.pack_status in ("received", "available", "reserved", "sold"):
            raise RasentraError.conflict("pack_already_received", _("Pack %s sudah diterima sebelumnya.", code))
        if pack.pack_status not in ("shipped", "allocated"):
            raise RasentraError.conflict(
                "pack_not_shipped", _("Pack %s berstatus %s, tidak bisa diterima.", code, pack.pack_status)
            )
        ledger = self._ledger()
        transit = ledger.virtual(outlet.company_id, "transit")
        if action == "reject":
            if not (reason or "").strip():
                raise RasentraError("reason_required", _("Alasan penolakan wajib diisi."))
            ledger.move(pack.product_id, pack.net_weight, transit, ledger.location(outlet, "quarantine"),
                        f"Tolak terima {pack.name}", lot=pack)
            pack._pack_event("received_rejected", "damaged", employee, "pack_receipt", pack.name, reason)
            pack.write({"pack_status": "damaged", "rasentra_location_type": "outlet"})
            self.env["rasentra.audit.event"].record("receiving.rejected", pack, employee=employee, reason=reason, outlet=outlet)
            return pack
        ledger.move(pack.product_id, pack.net_weight, transit, ledger.location(outlet, "stock"),
                    f"Terima {pack.name}", lot=pack)
        pack._pack_event("received", "received", employee, "pack_receipt", pack.name)
        pack.write({"pack_status": "received", "rasentra_location_type": "outlet"})
        return pack

    # ------------------------------------------------------------------ cek stok

    @api.model
    def check(self, outlet, code):
        """Cek stok: Pack ID → status dan kedaluwarsa; SKU → saldo stok jual dan karantina."""
        code = (code or "").strip()
        warn_days = int(self.env["ir.config_parameter"].sudo().get_param("rasentra.expiry_warning_days", 2))
        pack = self.env["stock.lot"].sudo().search([("name", "=", code), ("is_rasentra_pack", "=", True)], limit=1)
        ledger = self._ledger()
        if pack:
            today = outlet.business_date()
            return {
                "kind": "pack",
                "code": pack.name,
                "product": pack.product_id.display_name,
                "net_weight": str(qty(pack.net_weight)),
                "status": pack.pack_status,
                "outlet": pack.rasentra_outlet_id.code,
                "expires_at": fields.Date.to_string(pack.pack_expiry_date) if pack.pack_expiry_date else None,
                "expiry_warning": bool(pack.pack_expiry_date and pack.pack_expiry_date <= today + timedelta(days=warn_days)),
            }
        product = self._product_by_code(code)
        return {
            "kind": "product",
            "code": product.default_code,
            "product": product.display_name,
            "uom": product.uom_id.name,
            "available": str(ledger.balance(product, ledger.location(outlet, "stock"))),
            "quarantine": str(ledger.balance(product, ledger.location(outlet, "quarantine"))),
        }

    @api.model
    def expiring(self, outlet, days=None):
        days = days if days is not None else int(
            self.env["ir.config_parameter"].sudo().get_param("rasentra.expiry_warning_days", 2)
        )
        limit = outlet.business_date() + timedelta(days=days)
        return self.env["stock.lot"].sudo().search(
            [("is_rasentra_pack", "=", True), ("rasentra_outlet_id", "=", outlet.id),
             ("pack_status", "in", PACK_ON_HAND), ("pack_expiry_date", "!=", False),
             ("pack_expiry_date", "<=", limit)], order="pack_expiry_date",
        )

    # ------------------------------------------------------------------ karantina & waste

    @api.model
    def quarantine(self, outlet):
        """Isi karantina outlet: pack per kode dan barang non-pack per produk."""
        packs = self.env["stock.lot"].sudo().search(
            [("is_rasentra_pack", "=", True), ("rasentra_outlet_id", "=", outlet.id),
             ("pack_status", "in", PACK_IN_QUARANTINE)], order="pack_expiry_date, name",
        )
        location = self._ledger().location(outlet, "quarantine")
        quants = self.env["stock.quant"].sudo().read_group(
            [("location_id", "child_of", location.id), ("lot_id.is_rasentra_pack", "!=", True)],
            ["quantity:sum"], ["product_id"],
        )
        items = []
        for row in quants:
            if row["quantity"] > 0:
                product = self.env["product.product"].browse(row["product_id"][0])
                items.append({"code": product.default_code, "product": product.name,
                              "quantity": str(qty(row["quantity"])), "uom": product.uom_id.name})
        return {
            "packs": [
                {"pack_code": p.name, "product": p.product_id.name, "net_weight": str(qty(p.net_weight)),
                 "status": p.pack_status, "expires_at": fields.Date.to_string(p.pack_expiry_date) or None,
                 "reason": (p.pack_event_ids.filtered(lambda e: e.to_status in PACK_IN_QUARANTINE)[:1]).reason}
                for p in packs
            ],
            "items": items,
        }

    @api.model
    def waste(self, outlet, employee, code, quantity, reason, approval=None, source="available"):
        return self._decide("waste", outlet, employee, code, quantity, reason, approval, source)

    @api.model
    def release(self, outlet, employee, code, quantity, reason, approval=None):
        return self._decide("release", outlet, employee, code, quantity, reason, approval, "quarantine")

    @api.model
    def hold(self, outlet, employee, code, reason):
        """Tahan pack (hampir kedaluwarsa / cek QC): tidak bisa dijual tanpa PIN kepala outlet."""
        if not (reason or "").strip():
            raise RasentraError("reason_required", _("Alasan wajib diisi."))
        pack = self._own_pack(code, outlet)
        if pack.pack_status not in ("received", "available"):
            raise RasentraError.conflict(
                "pack_not_holdable", _("Pack %s berstatus %s, tidak bisa ditahan.", code, pack.pack_status)
            )
        pack._pack_event("hold", "hold", employee, None, None, reason)
        pack.write({"pack_status": "hold"})
        self.env["rasentra.audit.event"].record("pack.hold", pack, employee=employee, reason=reason, outlet=outlet)
        return pack

    @api.model
    def _decide(self, kind, outlet, employee, code, quantity, reason, approval, source):
        if not (reason or "").strip():
            raise RasentraError("reason_required", _("Alasan wajib diisi."))
        approver = self._approver(employee, approval, outlet)
        ledger = self._ledger()
        stock_loc = ledger.location(outlet, "stock")
        quarantine_loc = ledger.location(outlet, "quarantine")
        code = (code or "").strip()
        pack = self.env["stock.lot"].sudo().search([("name", "=", code), ("is_rasentra_pack", "=", True)], limit=1)
        if pack:
            pack = self._own_pack(code, outlet)
            in_quarantine = pack.pack_status in PACK_IN_QUARANTINE
            if kind == "release" and not in_quarantine:
                raise RasentraError.conflict(
                    "pack_not_quarantined", _("Pack %s tidak sedang di karantina (status %s).", code, pack.pack_status)
                )
            if kind == "waste" and not in_quarantine and pack.pack_status not in PACK_ON_HAND:
                raise RasentraError.conflict(
                    "pack_not_wasteable", _("Pack %s berstatus %s, tidak bisa dibuang.", code, pack.pack_status)
                )
            product = pack.product_id
            amount = qty(pack.net_weight)
            state = "quarantine" if in_quarantine else "available"
            source_loc = self._pack_location(pack, outlet)
        else:
            product = self._product_by_code(code)
            if product.tracking == "lot" and product.rasentra_type == "meat_pack":
                raise RasentraError("pack_required", _("Produk timbang diproses per Pack ID. Scan label pack-nya."))
            state = "quarantine" if kind == "release" else source
            amount = qty(quantity or 0)
            if amount <= 0:
                raise RasentraError("quantity_required", _("Isi jumlah barang."))
            source_loc = quarantine_loc if state == "quarantine" else stock_loc
            balance = ledger.balance(product, source_loc)
            if amount > balance:
                label = _("karantina") if state == "quarantine" else _("stok")
                raise RasentraError.conflict(
                    "quantity_exceeds",
                    _("Jumlah melebihi saldo %s %s (%s %s).", label, product.name, balance, product.uom_id.name),
                )

        doc = self.env["rasentra.stock.adjustment"].record(
            kind, outlet,
            [{"product": product, "pack": pack or None, "quantity": amount, "from_state": state,
              "to_state": "available" if kind == "release" else None}],
            employee=employee, approver=approver, reason=reason,
        )
        if kind == "release":
            moves = ledger.move(product, amount, source_loc, stock_loc, doc.doc_no, lot=pack or None) \
                if source_loc != stock_loc else self.env["stock.move"]
        else:
            moves = ledger.move(product, amount, source_loc, ledger.virtual(outlet.company_id, "scrap"),
                                doc.doc_no, lot=pack or None)
        doc.move_ids = [(6, 0, moves.ids)]
        if pack:
            to_status = "received" if kind == "release" else "wasted"
            pack._pack_event("released" if kind == "release" else "wasted", to_status, employee,
                             "stock_adjustment", doc.uuid, reason)
            pack.write({"pack_status": to_status, "reserved_order_uuid": False})
        self.env["rasentra.audit.event"].record(
            "stock.released" if kind == "release" else "stock.wasted", doc, employee=employee, approver=approver,
            reason=reason, outlet=outlet,
            after={"doc_no": doc.doc_no, "code": code, "quantity": str(amount), "from": state},
        )
        return doc
