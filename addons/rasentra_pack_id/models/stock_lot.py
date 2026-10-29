from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty

PACK_STATUSES = [
    ("available", "Tersedia (pusat)"),
    ("allocated", "Dialokasikan"),
    ("shipped", "Dikirim"),
    ("received", "Diterima outlet"),
    ("reserved", "Di keranjang"),
    ("sold", "Terjual"),
    ("hold", "Ditahan"),
    ("damaged", "Rusak / karantina"),
    ("quarantine", "Karantina retur"),
    ("repacked", "Dikemas ulang"),
]
SELLABLE = ("received", "available")


class StockLot(models.Model):
    """Pack ID = satu kemasan daging dengan berat aktual. Port dari tabel `packs` Laravel.

    Produk daging memakai tracking='lot' (bukan serial) karena kuantitasnya dalam kg.
    Penjaga jual ganda: kunci baris (SELECT ... FOR UPDATE) + constraint unik `sold_line_uuid`.
    """

    _inherit = "stock.lot"

    is_rasentra_pack = fields.Boolean(string="Pack ID", index=True)
    net_weight = fields.Float(string="Berat bersih (kg)", digits=(18, 6))
    weigh_source = fields.Char(string="Sumber timbang")
    packed_at = fields.Datetime(string="Waktu kemas")
    pack_expiry_date = fields.Date(string="Kedaluwarsa")
    label_price = fields.Float(string="Harga label", digits=(18, 2))
    rasentra_batch_no = fields.Char(string="Batch produksi")
    production_date = fields.Date(string="Tanggal produksi")
    rasentra_location_type = fields.Selection(
        [("central", "Gudang pusat"), ("transit", "Transit"), ("outlet", "Outlet"), ("return", "Retur")],
        string="Posisi",
        default="central",
    )
    rasentra_outlet_id = fields.Many2one("rasentra.outlet", string="Outlet", index=True)
    pack_status = fields.Selection(PACK_STATUSES, string="Status pack", default="available", index=True)
    reserved_order_uuid = fields.Char(copy=False, index=True)
    sold_line_uuid = fields.Char(copy=False)
    lock_version = fields.Integer(default=0, copy=False)
    pack_event_ids = fields.One2many("rasentra.pack.event", "lot_id", string="Riwayat")

    _sql_constraints = [
        ("sold_line_unique", "unique(sold_line_uuid)", "Pack ID ini sudah terjual pada baris lain."),
        ("net_weight_positive", "check(not is_rasentra_pack or net_weight > 0)", "Berat Pack ID harus lebih dari nol."),
    ]

    def init(self):
        # Pack ID unik global dan tidak pernah dipakai ulang (lot biasa hanya unik per produk + company).
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS stock_lot_rasentra_pack_code_uniq "
            "ON stock_lot (name) WHERE is_rasentra_pack"
        )

    # ------------------------------------------------------------------ helpers

    @api.model
    def _lock_pack(self, code):
        """Ambil Pack ID dengan kunci baris. Transaksi lain yang memindai pack sama menunggu."""
        self.env.cr.execute(
            "SELECT id FROM stock_lot WHERE name = %s AND is_rasentra_pack FOR UPDATE", [(code or "").strip()]
        )
        row = self.env.cr.fetchone()
        if not row:
            raise RasentraError(
                "pack_unknown",
                _("Pack ID %s tidak dikenal. Jangan menebak berat; hubungi kepala outlet.", code),
                404,
            )
        pack = self.sudo().browse(row[0])
        pack.invalidate_recordset()
        return pack

    def _pack_event(self, event, to_status, employee=None, source_type=None, source_ref=None, reason=None):
        self.ensure_one()
        self.env["rasentra.pack.event"].sudo().create(
            {
                "lot_id": self.id,
                "event": event,
                "from_status": self.pack_status,
                "to_status": to_status,
                "employee_id": employee.id if employee else False,
                "source_type": source_type,
                "source_ref": source_ref,
                "reason": reason,
            }
        )

    def _is_expired(self):
        return bool(self.pack_expiry_date) and self.pack_expiry_date < fields.Date.context_today(self)

    # ------------------------------------------------------------------ penjualan

    @api.model
    def pack_reserve(self, code, order_uuid, outlet, employee, channel=None, approval=None):
        """Pindai Pack ID ke keranjang (port OrderService::addPack). Dipanggil lewat RPC dari POS.

        Mengembalikan data baris: produk, berat, harga/kg, nilai bruto dan versi harga.
        """
        pack = self._lock_pack(code)
        if pack.pack_status == "reserved" and pack.reserved_order_uuid == order_uuid:
            raise RasentraError.conflict("pack_already_in_cart", _("Kemasan ini sudah ada di keranjang."))
        if pack.pack_status == "sold" or pack.sold_line_uuid:
            raise RasentraError.conflict("pack_already_sold", _("Kemasan ini sudah terjual."))
        if pack.pack_status == "reserved":
            raise RasentraError.conflict("pack_reserved", _("Kemasan sedang dipakai transaksi lain."))
        if pack.rasentra_outlet_id != outlet or pack.rasentra_location_type != "outlet":
            raise RasentraError.conflict("pack_other_outlet", _("Kemasan bukan stok outlet ini atau belum diterima."))

        approver = None
        expired = pack._is_expired()
        if pack.pack_status == "hold" or expired:
            approver = self.env["rasentra.approval"].verify(approval, employee, outlet)
        elif pack.pack_status not in SELLABLE:
            raise RasentraError.conflict(
                "pack_not_sellable", _("Status kemasan %s tidak dapat dijual.", pack.pack_status)
            )

        unit_price, version = self.env["rasentra.price.version"].resolve(pack.product_id, outlet, channel)
        weight = qty(pack.net_weight)
        gross = money(weight * unit_price)

        pack._pack_event(
            "reserved", "reserved", employee, "order", order_uuid,
            f"approved_by:{approver.id}" if approver else None,
        )
        pack.write(
            {"pack_status": "reserved", "reserved_order_uuid": order_uuid, "lock_version": pack.lock_version + 1}
        )
        if approver:
            self.env["rasentra.audit.event"].record(
                "pack.sell_override", pack, employee=employee, approver=approver,
                reason="expired" if expired else "hold", outlet=outlet,
            )
        return {
            "lot_id": pack.id,
            "pack_code": pack.name,
            "product_id": pack.product_id.id,
            "quantity": str(weight),
            "uom": pack.product_uom_id.name,
            "unit_price": str(unit_price),
            "gross_amount": str(gross),
            "label_price": str(money(pack.label_price)) if pack.label_price else None,
            "price_version_uuid": version.uuid,
            "approved_by": approver.id if approver else None,
        }

    @api.model
    def pack_release(self, code, order_uuid, employee=None, reason=None):
        """Lepas pack dari keranjang (void baris). Tidak melakukan apa pun bila pack bukan milik order ini."""
        pack = self._lock_pack(code)
        if pack.pack_status != "reserved" or pack.reserved_order_uuid != order_uuid:
            return False
        pack._pack_event("released", "received", employee, "order", order_uuid, reason)
        pack.write({"pack_status": "received", "reserved_order_uuid": False, "lock_version": pack.lock_version + 1})
        return True

    @api.model
    def pack_mark_sold(self, code, order_uuid, line_uuid, employee=None):
        """Finalisasi penjualan: pack terjual tepat sekali (port OrderService::deductStock)."""
        pack = self._lock_pack(code)
        if pack.sold_line_uuid:
            raise RasentraError.conflict("pack_already_sold", _("Kemasan sudah terjual pada transaksi lain."))
        if pack.pack_status != "reserved" or pack.reserved_order_uuid != order_uuid:
            raise RasentraError.conflict("pack_not_reserved", _("Kemasan tidak ada di keranjang transaksi ini."))
        pack._pack_event("sold", "sold", employee, "order", order_uuid)
        pack.write(
            {
                "pack_status": "sold",
                "sold_line_uuid": line_uuid,
                "reserved_order_uuid": False,
                "lock_version": pack.lock_version + 1,
            }
        )
        return True

    @api.model
    def pack_mark_returned(self, code, return_uuid, employee=None, reason=None):
        """Retur penjualan: Pack ID selalu masuk karantina; petugas memutuskan kembali ke stok atau waste."""
        pack = self._lock_pack(code)
        if pack.pack_status != "sold":
            raise RasentraError.conflict("pack_not_sold", _("Kemasan %s tidak berstatus terjual.", code))
        pack._pack_event("returned", "quarantine", employee, "sales_return", return_uuid, reason)
        pack.write({"pack_status": "quarantine", "sold_line_uuid": False, "lock_version": pack.lock_version + 1})
        return True
