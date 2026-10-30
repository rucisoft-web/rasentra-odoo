import json
import logging
import time

from odoo import _, api, fields, models
from odoo.modules import module

from odoo.addons.rasentra_core.tools import money

from ..tools import FakeSapClient, SapTimeout, ServiceLayerClient

_logger = logging.getLogger(__name__)

STATUSES = [
    ("pending", "Menunggu"),
    ("validated", "Tervalidasi"),
    ("waiting_dependency", "Menunggu dokumen induk"),
    ("posting", "Sedang diposting"),
    ("posted", "Terposting"),
    ("partially_posted", "Sebagian terposting"),
    ("failed", "Gagal"),
    ("needs_review", "Perlu diperiksa"),
]


class RasentraSapDocument(models.Model):
    """Satu dokumen SAP per objek per sumber (port SapPostingService).

    Penjualan diposting ke instance SAP milik CV pemilik outlet; invoice dan pembayaran berhasil/gagal
    sendiri-sendiri. Sebelum membuat dokumen, SAP dicari dulu lewat referensi sumber (U_POS_SRC) agar
    timeout atau crash setelah commit SAP tidak menggandakan dokumen.
    """

    _name = "rasentra.sap.document"
    _inherit = ["rasentra.uuid.mixin"]
    _description = "Dokumen SAP"
    _order = "id desc"
    _rec_name = "source_ref"

    company_db = fields.Char(required=True, index=True, readonly=True)
    source_type = fields.Char(required=True, readonly=True)
    source_uuid = fields.Char(required=True, index=True, readonly=True)
    source_ref = fields.Char(compute="_compute_source_ref", store=True)
    hq_order_id = fields.Many2one("rasentra.hq.order", readonly=True, index=True)
    hq_stock_adjustment_id = fields.Many2one("rasentra.hq.stock.adjustment", readonly=True, index=True)
    sap_object = fields.Char(required=True, readonly=True)
    status = fields.Selection(STATUSES, default="pending", required=True, index=True, readonly=True)
    doc_entry = fields.Integer(readonly=True)
    doc_num = fields.Integer(readonly=True)
    posted_amount = fields.Float(digits=(18, 2), readonly=True)
    posting_date = fields.Date(readonly=True)
    request_payload = fields.Json(readonly=True)
    response_payload = fields.Json(readonly=True)
    request_text = fields.Text(compute="_compute_texts")
    response_text = fields.Text(compute="_compute_texts")
    attempts = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)

    _sql_constraints = [
        ("source_object_unique", "unique(company_db, source_type, source_uuid, sap_object)",
         "Dokumen SAP untuk sumber dan objek ini sudah ada."),
    ]

    @api.depends("source_type", "source_uuid")
    def _compute_source_ref(self):
        for doc in self:
            doc.source_ref = f"{doc.source_type}:{doc.source_uuid}"

    def _compute_texts(self):
        for doc in self:
            doc.request_text = json.dumps(doc.request_payload, indent=2, ensure_ascii=False) if doc.request_payload else ""
            doc.response_text = json.dumps(doc.response_payload, indent=2, ensure_ascii=False) if doc.response_payload else ""

    # ---- klien -----------------------------------------------------------------

    @api.model
    def _client(self, company_db):
        """Service Layer bila instance dikonfigurasi (rasentra.sap.<db>.url), selain itu mode simulasi."""
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param(f"rasentra.sap.{company_db}.url") or params.get_param("rasentra.sap.url")
        if not url:
            return FakeSapClient(self.env, company_db)
        get = lambda key: params.get_param(f"rasentra.sap.{company_db}.{key}") or params.get_param(f"rasentra.sap.{key}")
        return ServiceLayerClient({
            "company_db": company_db, "url": url, "username": get("username"), "password": get("password"),
            "verify": (get("verify") or "1") not in ("0", "false"),
        })

    # ---- mapping ---------------------------------------------------------------

    @api.model
    def _missing_mappings(self, company_db, product_codes, methods):
        Mapping = self.env["rasentra.sap.mapping"].sudo()
        missing = [f"product:{c}" for c in product_codes if not Mapping.lookup(company_db, "product", c)]
        missing += [f"payment_method:{m}" for m in methods if not Mapping.lookup(company_db, "payment_method", m)]
        return list(dict.fromkeys(missing))

    @api.model
    def _lock(self, source_uuid):
        """Kunci per sumber (pengganti Cache::lock): sesi lain yang memposting sumber sama dilewati."""
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", [source_uuid])
        return self.env.cr.fetchone()[0]

    # ---- posting satu objek ------------------------------------------------------

    @api.model
    def _post(self, company_db, source_type, source_uuid, sap_object, payload, hq_order=None, hq_adjustment=None):
        doc = self.sudo().search([("company_db", "=", company_db), ("source_type", "=", source_type),
                                  ("source_uuid", "=", source_uuid), ("sap_object", "=", sap_object)], limit=1)
        if not doc:
            doc = self.sudo().create({
                "company_db": company_db, "source_type": source_type, "source_uuid": source_uuid,
                "sap_object": sap_object, "request_payload": payload,
                "hq_order_id": hq_order.id if hq_order else False,
                "hq_stock_adjustment_id": hq_adjustment.id if hq_adjustment else False,
            })
        self.env.cr.execute("SELECT id FROM rasentra_sap_document WHERE id = %s FOR UPDATE", [doc.id])
        if doc.status == "posted":
            return doc  # retry melanjutkan tahap yang belum selesai saja
        if not doc.request_payload or doc.status == "waiting_dependency":
            doc.request_payload = payload
        client = self._client(company_db)
        ref = doc.source_ref
        try:
            # Pemeriksaan hasil sebelum (ulang) posting.
            existing = client.find_by_source_ref(sap_object, ref)
            if existing:
                doc.write({"status": "posted", "doc_entry": existing["DocEntry"], "doc_num": existing["DocNum"],
                           "response_payload": existing, "last_error": False})
                return doc
            doc.write({"status": "posting", "attempts": doc.attempts + 1})
            result = client.create(sap_object, dict(payload, U_POS_SRC=ref))
            doc.write({
                "status": "posted", "doc_entry": result["DocEntry"], "doc_num": result["DocNum"],
                "response_payload": result, "posted_amount": float(money(payload.get("DocTotal") or 0)),
                "posting_date": fields.Date.context_today(self), "last_error": False,
            })
        except SapTimeout as error:
            # Hasil belum pasti: jangan buat ulang; pemulihan memeriksa referensi di SAP dulu.
            doc.write({"status": "needs_review", "last_error": str(error)})
        except Exception as error:  # noqa: BLE001 - kesalahan SAP apa pun dicatat per dokumen
            _logger.info("Posting SAP %s %s gagal: %s", sap_object, ref, error)
            doc.write({"status": "failed", "last_error": str(error)})
        return doc

    # ---- penjualan dan retur ------------------------------------------------------

    @api.model
    def post_order(self, order):
        """Posting satu rasentra.hq.order: penjualan = Invoice + IncomingPayment;
        retur = CreditNote (merujuk invoice asal) + VendorPayment (uang kembali)."""
        order = order.sudo()
        company_db = order.outlet_id.company_id.sap_company_db
        source_type = "order" if order.kind == "sale" else "sales_return"
        if not company_db:
            self.env["rasentra.integration.exception"].sudo().raise_open(
                "missing_mapping", source_type, order.uuid, _("Perusahaan pemilik outlet belum punya database SAP."))
            return order._set_sap_state("failed")
        if not self._lock(order.uuid):
            return "locked"
        methods = order.payment_ids.mapped("method")
        missing = self._missing_mappings(company_db, order.line_ids.mapped("product_code"), methods)
        if missing:
            self.env["rasentra.integration.exception"].sudo().raise_open(
                "missing_mapping", source_type, order.uuid,
                _("Mapping SAP %(db)s belum ada: %(m)s", db=company_db, m=", ".join(missing)), company_db)
            return order._set_sap_state("failed")
        if order.kind == "sale":
            return self._post_sale(company_db, order)
        return self._post_return(company_db, order)

    def _post_sale(self, company_db, order):
        invoice = self._post(company_db, "order", order.uuid, "Invoices", self._invoice_payload(company_db, order), order)
        if invoice.status != "posted":
            return order._set_sap_state(invoice.status)
        payment = self._post(company_db, "order", order.uuid, "IncomingPayments",
                             self._payment_payload(company_db, order, invoice.doc_entry), order)
        return order._set_sap_state("posted" if payment.status == "posted" else "partially_posted")

    def _post_return(self, company_db, order):
        original = order.original_order_id
        invoice = self.sudo().search([("company_db", "=", company_db), ("source_type", "=", "order"),
                                      ("source_uuid", "=", order.original_order_uuid),
                                      ("sap_object", "=", "Invoices"), ("status", "=", "posted")], limit=1)
        if not invoice:
            doc = self.sudo().search([("company_db", "=", company_db), ("source_type", "=", "sales_return"),
                                      ("source_uuid", "=", order.uuid), ("sap_object", "=", "CreditNotes")], limit=1)
            vals = {"status": "waiting_dependency",
                    "last_error": _("Menunggu invoice struk %s terposting.", original.doc_no or order.original_order_uuid)}
            if doc:
                doc.write(vals)
            else:
                self.sudo().create(dict(vals, company_db=company_db, source_type="sales_return",
                                        source_uuid=order.uuid, sap_object="CreditNotes", hq_order_id=order.id))
            return order._set_sap_state("waiting_dependency")
        memo = self._post(company_db, "sales_return", order.uuid, "CreditNotes",
                          self._credit_note_payload(company_db, order, invoice), order)
        if memo.status != "posted":
            return order._set_sap_state(memo.status)
        refund = self._post(company_db, "sales_return", order.uuid, "VendorPayments",
                            self._refund_payload(company_db, order, memo), order)
        return order._set_sap_state("posted" if refund.status == "posted" else "partially_posted")

    # ---- penyesuaian stok ----------------------------------------------------------

    @api.model
    def post_stock_adjustment(self, adjustment):
        """Barang keluar (waste, opname kurang, bahan produksi) = Goods Issue (InventoryGenExits); barang
        masuk (opname lebih, hasil produksi) = Goods Receipt (InventoryGenEntries). Lepas karantina hanya
        memindah status di outlet, jadi tidak perlu dokumen SAP."""
        adjustment = adjustment.sudo()
        exits = adjustment.line_ids.filtered(lambda l: not l.to_state)
        entries = adjustment.line_ids.filtered(lambda l: not l.from_state)
        if not exits and not entries:
            return adjustment._set_sap_state("not_required")
        company_db = adjustment.outlet_id.company_id.sap_company_db
        Exception_ = self.env["rasentra.integration.exception"].sudo()
        if not company_db:
            Exception_.raise_open("missing_mapping", "stock_adjustment", adjustment.uuid,
                                  _("Perusahaan pemilik outlet belum punya database SAP."))
            return adjustment._set_sap_state("failed")
        missing = self._missing_mappings(company_db, adjustment.line_ids.mapped("product_code"), [])
        if missing:
            Exception_.raise_open("missing_mapping", "stock_adjustment", adjustment.uuid,
                                  _("Mapping SAP %(db)s belum ada: %(m)s", db=company_db, m=", ".join(missing)), company_db)
            return adjustment._set_sap_state("failed")
        if not self._lock(adjustment.uuid):
            return "locked"
        statuses = []
        for sap_object, lines in (("InventoryGenExits", exits), ("InventoryGenEntries", entries)):
            if lines:
                doc = self._post(company_db, "stock_adjustment", adjustment.uuid, sap_object,
                                 self._stock_payload(company_db, adjustment, lines), hq_adjustment=adjustment)
                statuses.append(doc.status)
        posted = statuses.count("posted")
        state = "posted" if posted == len(statuses) else ("partially_posted" if posted else statuses[0])
        return adjustment._set_sap_state(state)

    def _stock_payload(self, company_db, adjustment, lines):
        warehouse = self._code(company_db, "outlet", adjustment.outlet_id.code).sap_code or None
        # Akun lawan per jenis penyesuaian (mis. biaya waste); tanpa mapping memakai akun bawaan gudang.
        account = self._code(company_db, "account", adjustment.kind).sap_code or None
        labels = {"waste": "Waste", "count": "Selisih stok opname", "release": "Lepas karantina",
                  "production": "Produksi dapur"}
        return {
            "DocDate": fields.Date.to_string(adjustment.business_date),
            "Reference2": adjustment.doc_no,
            "Comments": f"{labels.get(adjustment.kind, adjustment.kind)} {adjustment.doc_no}: {adjustment.reason or ''}".strip(),
            "DocumentLines": [
                self._compact({
                    "ItemCode": self._code(company_db, "product", line.product_code).sap_code,
                    "Quantity": str(line.quantity), "WarehouseCode": warehouse, "AccountCode": account,
                    "U_POS_PACK": line.pack_code or None,
                })
                for line in lines
            ],
        }

    # ---- payload -----------------------------------------------------------------

    def _code(self, company_db, entity_type, key):
        return self.env["rasentra.sap.mapping"].sudo().lookup(company_db, entity_type, key)

    @staticmethod
    def _compact(values):
        return {k: v for k, v in values.items() if v is not None and v is not False}

    def _invoice_payload(self, company_db, order):
        warehouse = self._code(company_db, "outlet", order.outlet_id.code).sap_code or None
        customer = self._code(company_db, "customer", "walk_in").sap_code or "C-UMUM"
        lines = []
        for line in order.line_ids:
            item = self._code(company_db, "product", line.product_code)
            unit = money(line.gross_amount) / money(line.quantity) if line.quantity else money(0)
            lines.append(self._compact({
                "ItemCode": item.sap_code, "Quantity": str(line.quantity), "UnitPrice": str(money(unit)),
                "LineTotal": str(money(line.net_amount)), "WarehouseCode": warehouse, "TaxCode": item.tax_code or None,
                "U_POS_LINE_TYPE": line.line_type, "U_POS_PACK": line.pack_code or None,
            }))
        return {"CardCode": customer, "DocDate": fields.Date.to_string(order.business_date),
                "NumAtCard": order.doc_no, "DocTotal": str(money(order.net_amount)), "DocumentLines": lines}

    def _payment_payload(self, company_db, order, invoice_doc_entry):
        cash = sum((money(p.amount) for p in order.payment_ids if p.method == "cash"), money(0))
        transfers = [
            {"Account": self._code(company_db, "payment_method", p.method).sap_code, "Sum": str(money(p.amount))}
            for p in order.payment_ids if p.method != "cash"
        ]
        return self._compact({
            "DocDate": fields.Date.to_string(order.business_date),
            "DocTotal": str(money(order.net_amount)),
            "CashSum": str(cash) if cash > 0 else None,
            "CashAccount": self._code(company_db, "payment_method", "cash").sap_code if cash > 0 else None,
            "PaymentInvoices": [{"DocEntry": invoice_doc_entry, "SumApplied": str(money(order.net_amount))}],
            "TransferAccounts": transfers,
        })

    def _credit_note_payload(self, company_db, order, invoice):
        original_lines = order.original_order_id.line_ids.sorted("line_no").mapped("line_no")
        payload = order.mapped("inbox_id").payload or {}
        line_ref = {l["line_no"]: l.get("order_line_no") for l in payload.get("lines") or []}
        lines = []
        for line in order.line_ids:
            item = self._code(company_db, "product", line.product_code)
            base_no = line_ref.get(line.line_no)
            quantity = -line.quantity
            unit = money(-line.gross_amount) / money(quantity) if quantity else money(0)
            lines.append(self._compact({
                "ItemCode": item.sap_code, "Quantity": str(quantity), "UnitPrice": str(money(unit)),
                "LineTotal": str(-money(line.net_amount)),
                "WarehouseCode": (invoice.request_payload.get("DocumentLines") or [{}])[0].get("WarehouseCode"),
                "TaxCode": item.tax_code or None,
                # Menyalin dari invoice asal agar SAP menautkan retur ke penjualannya.
                "BaseType": 13 if base_no else None,
                "BaseEntry": invoice.doc_entry if base_no else None,
                "BaseLine": original_lines.index(base_no) if base_no in original_lines else None,
                "U_POS_LINE_TYPE": line.line_type, "U_POS_PACK": line.pack_code or None,
                "U_POS_DISPOSITION": line.disposition or None,
            }))
        return {
            "CardCode": invoice.request_payload.get("CardCode") or "C-UMUM",
            "DocDate": fields.Date.to_string(order.business_date), "NumAtCard": order.doc_no,
            "Comments": f"Retur struk {order.original_order_id.doc_no or ''}: {payload.get('reason') or ''}".strip(),
            "DocTotal": str(-money(order.net_amount)), "DocumentLines": lines,
        }

    def _refund_payload(self, company_db, order, memo):
        method = order.payment_ids[:1].method or "cash"
        account = self._code(company_db, "payment_method", method).sap_code
        amount = str(-money(order.net_amount))
        return self._compact({
            "DocType": "rCustomer", "CardCode": memo.request_payload.get("CardCode") or "C-UMUM",
            "DocDate": fields.Date.to_string(order.business_date), "DocTotal": amount,
            "CashSum": amount if method == "cash" else None, "CashAccount": account if method == "cash" else None,
            "TransferSum": amount if method != "cash" else None,
            "TransferAccount": account if method != "cash" else None,
            "PaymentInvoices": [{"DocEntry": memo.doc_entry, "InvoiceType": "it_CredItnote", "SumApplied": amount}],
        })

    # ---- antrean, pemulihan, kesehatan --------------------------------------------

    @api.model
    def _commit(self):
        # Posting SAP bersifat eksternal: tiap dokumen di-commit sendiri di cron (bukan saat uji).
        if not module.current_test:
            self.env.cr.commit()

    @api.model
    def post_pending(self, limit=200):
        """Posting rasentra.hq.order yang belum terposting (cron tiap 5 menit). Ringkasan per status."""
        orders = self.env["rasentra.hq.order"].sudo().search(
            [("sap_state", "in", ("pending", "failed", "partially_posted", "waiting_dependency"))],
            order="business_date, id", limit=limit,
        )
        summary = {}
        for order in orders:
            state = self.post_order(order)
            summary[state] = summary.get(state, 0) + 1
            self._commit()
        adjustments = self.env["rasentra.hq.stock.adjustment"].sudo().search(
            [("sap_state", "in", ("pending", "failed", "partially_posted"))], order="business_date, id", limit=limit,
        )
        for adjustment in adjustments:
            state = self.post_stock_adjustment(adjustment)
            summary[state] = summary.get(state, 0) + 1
            self._commit()
        return summary

    @api.model
    def recover(self):
        """Dokumen needs_review: cek SAP lewat referensi dulu; ditemukan = posted, tidak = boleh diulang."""
        for doc in self.sudo().search([("status", "in", ("needs_review", "posting"))]):
            try:
                existing = self._client(doc.company_db).find_by_source_ref(doc.sap_object, doc.source_ref)
            except Exception as error:  # noqa: BLE001
                doc.last_error = str(error)
                continue
            if existing:
                doc.write({"status": "posted", "doc_entry": existing["DocEntry"], "doc_num": existing["DocNum"],
                           "response_payload": existing, "last_error": False})
            else:
                doc.write({"status": "failed", "last_error": _("Tidak ditemukan di SAP; aman diposting ulang.")})
            if doc.hq_order_id:
                doc.hq_order_id._set_sap_state(doc.hq_order_id._sap_state_from_documents())
            if doc.hq_stock_adjustment_id:
                doc.hq_stock_adjustment_id._set_sap_state(doc.hq_stock_adjustment_id._sap_state_from_documents())
            self._commit()

    @api.model
    def check_health(self):
        """Cek koneksi Service Layer per instance SAP (cron 15 menit); hasil terakhir di parameter sistem."""
        params = self.env["ir.config_parameter"].sudo()
        result = {}
        for company_db in set(self.env["res.company"].sudo().search([]).mapped("sap_company_db")) - {False}:
            started = time.monotonic()
            try:
                row = {"ok": True, **self._client(company_db).ping()}
            except Exception as error:  # noqa: BLE001
                row = {"ok": False, "error": str(error)[:300]}
            row.update(ms=int((time.monotonic() - started) * 1000), at=fields.Datetime.now().isoformat())
            params.set_param(f"rasentra.sap.health.{company_db}", json.dumps(row))
            result[company_db] = row
        return result

    def action_post_now(self):
        for order in self.hq_order_id:
            self.post_order(order)
        for adjustment in self.hq_stock_adjustment_id:
            self.post_stock_adjustment(adjustment)
        return True
