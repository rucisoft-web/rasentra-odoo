from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, qty
from odoo.addons.rasentra_promo.models.rasentra_promotion import line_type_of

CUSTOMER_CHANNELS = ("takeaway", "delivery")


class PosOrder(models.Model):
    _inherit = "pos.order"

    rasentra_outlet_id = fields.Many2one(related="config_id.rasentra_outlet_id", store=True)
    rasentra_channel = fields.Selection(related="config_id.rasentra_channel", store=True)
    rasentra_business_date = fields.Date(string="Tanggal bisnis", readonly=True, index=True)
    rasentra_doc_no = fields.Char(string="No. struk Rasentra", readonly=True, copy=False, index=True)
    rasentra_gross_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_discount_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_net_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_promotion_snapshot = fields.Json(readonly=True)
    rasentra_review = fields.Boolean(string="Perlu ditinjau", readonly=True, copy=False,
                                     help="Hitungan promo atau harga server berbeda dengan yang dibayar di kasir.")
    rasentra_print_count = fields.Integer(readonly=True, copy=False)
    customer_name = fields.Char()
    customer_phone = fields.Char()
    delivery_address = fields.Text()
    promised_at = fields.Datetime()
    fulfilment_note = fields.Text()

    _sql_constraints = [
        ("rasentra_doc_no_unique", "unique(rasentra_doc_no)", "Nomor struk Rasentra sudah dipakai."),
    ]

    # ---- finalisasi -------------------------------------------------------------

    def _rasentra_applies(self):
        return bool(self.config_id.rasentra_outlet_id) and not self.lines.filtered("refunded_orderline_id")

    def _process_saved_order(self, draft):
        finalize = not draft and self.state == "draft" and self._rasentra_applies()
        if finalize:
            # Diperiksa sebelum Odoo menandai lunas: kesalahan di sini membatalkan seluruh sinkron order,
            # sehingga order tetap di antrean POS dan tidak pernah lunas tanpa Pack ID terjual.
            self.sudo()._rasentra_check_before_paid()
        res = super()._process_saved_order(draft)
        if finalize and self.state in ("paid", "done", "invoiced") and not self.rasentra_doc_no:
            # Kasir POS tidak perlu hak baca master Rasentra; sudo tetap menyimpan uid kasir untuk audit.
            self.sudo()._rasentra_finalize()
        return res

    def _rasentra_sale_lines(self):
        return self.lines.filtered(lambda line: not line.rasentra_promo_uuid)

    def _rasentra_check_before_paid(self):
        self.ensure_one()
        if self.rasentra_channel in CUSTOMER_CHANNELS:
            if not self.customer_name or not self.customer_phone:
                raise RasentraError("customer_required", _("Isi nama dan nomor telepon pemesan."))
            if self.rasentra_channel == "delivery" and not self.delivery_address:
                raise RasentraError("address_required", _("Isi alamat antar untuk pesanan delivery."))
        Lot = self.env["stock.lot"].sudo()
        for line in self._rasentra_sale_lines():
            code = line._rasentra_pack_code()
            if line.product_id.rasentra_type == "meat_pack" and not code:
                raise RasentraError(
                    "weighed_needs_pack", _("%s harus dijual lewat scan Pack ID.", line.product_id.display_name)
                )
            if not code:
                continue
            pack = Lot.search([("name", "=", code), ("is_rasentra_pack", "=", True)], limit=1)
            if not pack:
                raise RasentraError("pack_unknown", _("Pack ID %s tidak dikenal.", code), 404)
            if qty(line.qty) != qty(pack.net_weight):
                raise RasentraError.conflict(
                    "pack_qty_mismatch", _("Berat baris %s harus sama dengan berat kemasan.", code)
                )

    def _rasentra_finalize(self):
        """Port OrderService::finalize setelah Odoo mencatat pembayaran: Pack ID terjual tepat sekali,
        alokasi promo dihitung ulang di server, nomor struk terbit, event masuk outbox."""
        self.ensure_one()
        outlet = self.rasentra_outlet_id
        self.env.cr.execute("SELECT id FROM rasentra_outlet WHERE id = %s FOR UPDATE", [outlet.id])
        business_date = self.session_id.rasentra_business_date or outlet.business_date(self.date_order)
        employee = self.employee_id
        Lot = self.env["stock.lot"].sudo()
        Version = self.env["rasentra.promotion.version"].sudo()
        Price = self.env["rasentra.price.version"].sudo()
        review = []

        sale_lines = self._rasentra_sale_lines()
        engine_lines = []
        for line in sale_lines:
            if code := line._rasentra_pack_code():
                Lot.pack_mark_sold(code, self.uuid, line.uuid, employee)
            gross = money(qty(line.qty) * money(line.price_unit) * (1 - qty(line.discount) / 100))
            version = False
            if line.product_id.rasentra_type:
                try:
                    price, version = Price.resolve(line.product_id, outlet, self.rasentra_channel, self.date_order)
                except RasentraError:
                    price = None
                if price is not None and money(line.price_unit) != price:
                    review.append(f"harga {line.product_id.default_code}: kasir {money(line.price_unit)}, server {price}")
            line.write({"rasentra_gross_amount": float(gross), "rasentra_line_type": line_type_of(line.product_id),
                        "rasentra_price_version_id": version.id if version else False})
            engine_lines.append(Version.engine_line(line.uuid, line.product_id, line.qty, line.price_unit, gross))

        result = self.session_id._rasentra_evaluate(engine_lines)
        charged = -sum((money(l.price_subtotal_incl) for l in self.lines - sale_lines), money(0))
        if money(result["total_discount"]) != charged:
            review.append(f"promo: kasir {charged}, server {result['total_discount']}")
        allocations = []
        for line in sale_lines:
            computed = result["lines"][line.uuid]
            line.write({"rasentra_discount_amount": float(money(computed["discount"])),
                        "rasentra_net_amount": float(money(computed["net"]))})
            allocations += [
                {"line_id": line.id, "promotion_version_uuid": a["promotion_version_id"],
                 "amount": float(money(a["amount"])), "funded_by": a["funded_by"]}
                for a in computed["allocations"]
            ]
        self.env["rasentra.discount.allocation"].sudo().create(allocations)

        gross_total = sum((money(l.rasentra_gross_amount) for l in sale_lines), money(0))
        self.write({
            "rasentra_business_date": business_date,
            "rasentra_doc_no": self._rasentra_next_doc_no(outlet, business_date),
            "rasentra_gross_amount": float(gross_total),
            "rasentra_discount_amount": float(charged),
            "rasentra_net_amount": float(money(self.amount_total)),
            "rasentra_promotion_snapshot": {"applied": result["applied"],
                                            "evaluated_at": fields.Datetime.to_string(fields.Datetime.now())},
            "rasentra_review": bool(review),
        })
        Audit = self.env["rasentra.audit.event"]
        if review:
            Audit.record("order.review_needed", self, employee=employee, reason="; ".join(review), outlet=outlet)
        self.env["rasentra.sync.outbox"].record(
            "order", self.uuid, "order.finalized", self._rasentra_payload(), business_date, outlet=outlet
        )
        Audit.record("order.finalized", self, employee=employee, amount=money(self.amount_total), outlet=outlet)

    def _rasentra_next_doc_no(self, outlet, business_date):
        prefix = f"{outlet.code}-{business_date:%y%m%d}-"
        last = self.search([("rasentra_doc_no", "=like", prefix + "%")], order="rasentra_doc_no desc", limit=1)
        seq = int(last.rasentra_doc_no[len(prefix):]) + 1 if last else 1
        return f"{prefix}{seq:05d}"

    def _rasentra_payload(self):
        """Isi event order.finalized, bentuknya sama dengan OrderService::payload Laravel.

        Id lintas instalasi memakai uuid (order, baris, pembayaran) dan kode (outlet, produk,
        Pack ID), karena id database Lokal tidak dikenal Central.
        """
        self.ensure_one()
        sale_lines = self._rasentra_sale_lines()
        return {
            "id": self.uuid,
            "doc_no": self.rasentra_doc_no,
            "outlet_id": self.rasentra_outlet_id.code,
            "channel": self.rasentra_channel,
            "customer": {"name": self.customer_name, "phone": self.customer_phone} if self.customer_name else None,
            "business_date": fields.Date.to_string(self.rasentra_business_date),
            "gross_amount": str(money(self.rasentra_gross_amount)),
            "discount_amount": str(money(self.rasentra_discount_amount)),
            "net_amount": str(money(self.rasentra_net_amount)),
            "finalized_at": fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lines": [
                {
                    "id": line.uuid,
                    "line_no": no,
                    "line_type": line.rasentra_line_type,
                    "product_id": line.product_id.default_code,
                    "product_code": line.product_id.default_code,
                    "pack_id": line._rasentra_pack_code() or None,
                    "pack_code": line._rasentra_pack_code() or None,
                    "cooking_job_id": None,
                    "quantity": str(qty(line.qty)),
                    "uom": line.product_uom_id.name,
                    "unit_price": str(money(line.price_unit)),
                    "gross_amount": str(money(line.rasentra_gross_amount)),
                    "discount_amount": str(money(line.rasentra_discount_amount)),
                    "net_amount": str(money(line.rasentra_net_amount)),
                    "discounts": [
                        {"promotion_version_id": a.promotion_version_uuid, "amount": str(money(a.amount)),
                         "funded_by": a.funded_by}
                        for a in line.rasentra_allocation_ids
                    ],
                }
                for no, line in enumerate(sale_lines, start=1)
            ],
            "payments": [
                {
                    "id": payment.uuid or str(payment.id),
                    "method": payment.payment_method_id._rasentra_code(),
                    "amount": str(money(payment.amount)),
                    "status": "succeeded",
                    "provider": None,
                    "provider_ref": payment.transaction_id or None,
                }
                for payment in self.payment_ids.filtered(lambda p: not p.is_change)
            ],
        }

    def action_rasentra_reprint(self):
        """Cetak ulang struk memakai nomor yang sama; print_count naik dan tercatat di audit."""
        for order in self:
            order.rasentra_print_count += 1
            self.env["rasentra.audit.event"].record(
                "receipt.reprinted", order, outlet=order.rasentra_outlet_id, after={"count": order.rasentra_print_count}
            )
        return True


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    rasentra_line_type = fields.Char(readonly=True)
    rasentra_promo_uuid = fields.Char(string="Versi promo (baris diskon)", index=True)
    rasentra_price_version_id = fields.Many2one("rasentra.price.version", readonly=True)
    rasentra_label_price = fields.Float(digits=(18, 2))
    rasentra_gross_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_discount_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_net_amount = fields.Float(digits=(18, 2), readonly=True)
    rasentra_allocation_ids = fields.One2many("rasentra.discount.allocation", "line_id", readonly=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["rasentra_promo_uuid", "rasentra_label_price"]

    def _rasentra_pack_code(self):
        self.ensure_one()
        if not self.product_id.rasentra_type:
            return False
        names = self.pack_lot_ids.mapped("lot_name")
        return names[0] if names else False
