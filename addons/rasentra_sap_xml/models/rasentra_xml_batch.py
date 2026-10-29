import base64
import hashlib
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from odoo import _, api, fields, models

from odoo.addons.rasentra_core.tools import RasentraError, money, to_decimal

from .. import tools

STEP4 = Decimal("0.0001")
DOC_STATUSES = [("staged", "Staging"), ("waiting_dependency", "Menunggu invoice"), ("posted", "Terposting"),
                ("error", "Error")]


def _num(value):
    """String NMEXML ke Decimal; hilang atau kosong = None (dibedakan dari nol)."""
    return None if value is None or value == "" else to_decimal(value)


def _date(value):
    if not value:
        return False
    head = value[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return False


class RasentraXmlBatch(models.Model):
    """Satu file NMEXML yang diterima (port NmexmlImporter). File asli disimpan sebagai lampiran beserta SHA-256
    dan tidak pernah diubah. Keunikan dokumen ditentukan oleh (sistem, cabang, jenis, nomor sumber), bukan nama
    atau hash file, sehingga file yang sama dengan nama berbeda tidak menghasilkan dokumen ganda."""

    _name = "rasentra.xml.batch"
    _description = "Impor XML NMEXML"
    _order = "id desc"
    _rec_name = "file_name"

    kind = fields.Selection([("MSI", "MSI (invoice penjualan)"), ("MSR", "MSR (pembayaran pelanggan)")],
                            string="Jenis file", required=True, readonly=True)
    file_name = fields.Char(required=True, readonly=True)
    sha256 = fields.Char(readonly=True, index=True, string="SHA-256")
    attachment_id = fields.Many2one("ir.attachment", readonly=True, string="File")
    status = fields.Selection([("received", "Diterima"), ("staged", "Staging"), ("rejected", "Ditolak")],
                              default="received", required=True, readonly=True)
    error_code = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
    document_count = fields.Integer(readonly=True, string="Jumlah dokumen")
    duplicate_count = fields.Integer(readonly=True, string="Duplikat")
    summary = fields.Json(readonly=True)
    summary_text = fields.Text(compute="_compute_summary_text", string="Ringkasan")
    document_ids = fields.One2many("rasentra.xml.document", "batch_id", readonly=True)
    imported_by_id = fields.Many2one(
        "res.users", string="Diimpor oleh", default=lambda self: self.env.user, readonly=True
    )

    def _compute_summary_text(self):
        for batch in self:
            s = batch.summary or {}
            if not s:
                batch.summary_text = batch.error_message or ""
                continue
            parts = [
                _("Invoice: %s, baris: %s (pecahan %s, diskon %s), pembayaran: %s",
                  s.get("invoices"), s.get("lines"), s.get("fractional_lines"), s.get("discount_lines"),
                  s.get("receipts")),
                _("Total invoice: Rp%s · total pembayaran: Rp%s", s.get("invoice_total"), s.get("payment_total")),
            ]
            for diff in s.get("rounding_differences") or []:
                parts.append(_("Selisih %(no)s: sumber %(s)s, hitung %(c)s, selisih %(d)s", no=diff["invoice_no"],
                               s=diff["source"], c=diff["calculated"], d=diff["difference"]))
            if s.get("duplicates"):
                parts.append(_("Duplikat dilewati: %s", ", ".join(s["duplicates"])))
            if s.get("waiting_dependency"):
                parts.append(_("Menunggu invoice: %s", ", ".join(s["waiting_dependency"])))
            batch.summary_text = "\n".join(parts)

    def write(self, vals):
        if set(vals) & {"kind", "file_name", "sha256", "attachment_id"} and any(b.attachment_id for b in self):
            raise RasentraError("xml_batch_immutable", _("File impor XML tidak bisa diubah."))
        return super().write(vals)

    @api.model
    def import_xml(self, content, file_name, kind):
        """Simpan file, parse aman, lalu staging. File yang ditolak tetap tercatat (status rejected) agar ada
        jejak siapa mengunggah apa; dokumen tidak dibuat."""
        if kind not in ("MSI", "MSR"):
            raise RasentraError("xml_kind_invalid", _("Jenis file harus MSI atau MSR."))
        if isinstance(content, str):
            content = content.encode()
        sha = hashlib.sha256(content).hexdigest()
        batch = self.sudo().create({"kind": kind, "file_name": file_name, "sha256": sha})
        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"{kind}-{sha}.xml", "datas": base64.b64encode(content), "mimetype": "application/xml",
            "res_model": self._name, "res_id": batch.id,
        })
        batch.attachment_id = attachment
        try:
            with self.env.cr.savepoint():
                parsed = tools.parse(content)
                batch._stage(parsed)
        except RasentraError as exc:
            batch.write({"status": "rejected", "error_code": exc.code,
                         "error_message": str(exc.args[0] if exc.args else exc)})
        self.env["rasentra.audit.event"].record(
            "xml.imported", batch, after={"file": file_name, "status": batch.status,
                                          "documents": batch.document_count, "duplicates": batch.duplicate_count})
        if kind == "MSI" and batch.status == "staged":
            self.env["rasentra.xml.document"].release_waiting_receipts()
        return batch

    def _stage(self, parsed):
        self.ensure_one()
        Document = self.env["rasentra.xml.document"].sudo()
        summary = {"invoices": 0, "lines": 0, "fractional_lines": 0, "discount_lines": 0, "receipts": 0,
                   "invoice_total": "0", "payment_total": "0", "rounding_differences": [], "duplicates": [],
                   "waiting_dependency": []}
        invoice_total = payment_total = Decimal(0)
        created = dupes = 0

        for inv in parsed["invoices"]:
            calc = Decimal(0)
            for line in inv["lines"]:
                quantity = _num(line["quantity"]) or Decimal(0)
                pct = _num(line["discount_pct"]) or Decimal(0)
                # Dasar per baris: qty x harga x (1 - diskon%/100), sebelum diskon header dan pajak.
                calc += (quantity * (_num(line["unit_price"]) or Decimal(0)) * (100 - pct) / 100).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP)
                summary["lines"] += 1
                if quantity != quantity.to_integral_value(rounding=ROUND_DOWN):
                    summary["fractional_lines"] += 1
                if pct:
                    summary["discount_lines"] += 1
            source = _num(inv["invoice_amount"]) or Decimal(0)
            diff = (source - calc).quantize(STEP4, rounding=ROUND_HALF_UP)
            calc4 = calc.quantize(STEP4, rounding=ROUND_HALF_UP)
            if diff:
                summary["rounding_differences"].append({"invoice_no": inv["invoice_no"], "source": str(source),
                                                        "calculated": str(calc4), "difference": str(diff)})
            if Document._exists("SALESINVOICE", inv["branch_code"], inv["invoice_no"]):
                dupes += 1
                summary["duplicates"].append(inv["invoice_no"])
                continue
            Document.create({
                "batch_id": self.id, "doc_type": "SALESINVOICE", "branch_code": inv["branch_code"] or "",
                "source_no": inv["invoice_no"] or "", "business_date": _date(inv["invoice_date"]),
                "legacy_customer_code": inv["customer_id"], "legacy_warehouse_code": inv["warehouse_id"],
                "document_total_source": str(source), "document_total_calculated": str(calc4),
                "rounding_difference": str(diff), "header": inv["raw"],
                "line_ids": [(0, 0, {
                    "source_line_key": line["source_line_key"], "legacy_item_code": line["item_no"],
                    "quantity": line["quantity"] if line["quantity"] not in (None, "") else False,
                    "uom": line["unit"], "unit_price": line["unit_price"] if line["unit_price"] not in (None, "") else False,
                    "line_discount_pct": line["discount_pct"], "raw": line["raw"],
                }) for line in inv["lines"]],
            })
            created += 1
            summary["invoices"] += 1
            invoice_total += source

        for rcp in parsed["receipts"]:
            amount = sum((_num(a["amount"]) or Decimal(0) for a in rcp["allocations"]), Decimal(0))
            branch = rcp["branch_code"] or ""
            waiting = any(not Document._exists("SALESINVOICE", branch, a["invoice_no"]) for a in rcp["allocations"])
            if Document._exists("CUSTOMERRECEIPT", branch, rcp["sequence_no"]):
                dupes += 1
                summary["duplicates"].append(rcp["sequence_no"])
                continue
            cheque = _num(rcp["cheque_amount"])
            Document.create({
                "batch_id": self.id, "doc_type": "CUSTOMERRECEIPT", "branch_code": branch,
                "source_no": rcp["sequence_no"] or "", "business_date": _date(rcp["payment_date"]),
                "legacy_customer_code": rcp["bill_to_id"],
                "document_total_source": str(cheque) if cheque is not None else False,
                "document_total_calculated": str(amount), "rounding_difference": str((cheque or Decimal(0)) - amount),
                "header": rcp["raw"], "status": "waiting_dependency" if waiting else "staged",
                "line_ids": [(0, 0, {
                    "ref_invoice_no": a["invoice_no"],
                    "amount": str(money(a["amount"])) if a["amount"] not in (None, "") else False, "raw": a["raw"],
                }) for a in rcp["allocations"]],
            })
            if waiting:
                summary["waiting_dependency"].append(rcp["sequence_no"])
            created += 1
            summary["receipts"] += 1
            payment_total += amount

        summary["invoice_total"] = str(money(invoice_total))
        summary["payment_total"] = str(money(payment_total))
        self.write({"document_count": created, "duplicate_count": dupes, "status": "staged", "summary": summary})


class RasentraXmlDocument(models.Model):
    _name = "rasentra.xml.document"
    _description = "Dokumen sumber XML"
    _inherit = ["rasentra.uuid.mixin"]
    _order = "business_date desc, source_no"
    _rec_name = "source_no"

    batch_id = fields.Many2one("rasentra.xml.batch", required=True, readonly=True, ondelete="restrict", index=True)
    system = fields.Char(default="NMEXML", required=True, readonly=True)
    branch_code = fields.Char(readonly=True, index=True, string="Kode cabang")
    doc_type = fields.Selection([("SALESINVOICE", "Invoice penjualan"), ("CUSTOMERRECEIPT", "Pembayaran pelanggan")],
                                string="Jenis dokumen", required=True, readonly=True, index=True)
    source_no = fields.Char(required=True, readonly=True, index=True, string="No. sumber")
    business_date = fields.Date(readonly=True, string="Tanggal bisnis")
    legacy_customer_code = fields.Char(readonly=True, string="Kode pelanggan lama")
    legacy_warehouse_code = fields.Char(readonly=True)
    # Disimpan sebagai teks desimal agar nilai sumber tidak tersentuh pembulatan float.
    document_total_source = fields.Char(readonly=True)
    document_total_calculated = fields.Char(readonly=True)
    rounding_difference = fields.Char(readonly=True)
    has_difference = fields.Boolean(compute="_compute_has_difference", store=True)
    header = fields.Json(readonly=True)
    status = fields.Selection(DOC_STATUSES, default="staged", required=True, readonly=True, index=True)
    line_ids = fields.One2many("rasentra.xml.line", "document_id", readonly=True)

    _sql_constraints = [("source_unique", "unique(system, branch_code, doc_type, source_no)",
                         "Dokumen sumber ini sudah pernah diimpor.")]

    @api.depends("rounding_difference")
    def _compute_has_difference(self):
        for doc in self:
            doc.has_difference = bool(_num(doc.rounding_difference))

    @api.model
    def _exists(self, doc_type, branch, source_no):
        return bool(self.sudo().search_count([("system", "=", "NMEXML"), ("branch_code", "=", branch or ""),
                                              ("doc_type", "=", doc_type), ("source_no", "=", source_no or "")]))

    @api.model
    def release_waiting_receipts(self):
        released = 0
        for rcp in self.sudo().search([("doc_type", "=", "CUSTOMERRECEIPT"), ("status", "=", "waiting_dependency")]):
            if all(self._exists("SALESINVOICE", rcp.branch_code, line.ref_invoice_no) for line in rcp.line_ids):
                rcp.status = "staged"
                released += 1
        return released


class RasentraXmlLine(models.Model):
    _name = "rasentra.xml.line"
    _description = "Baris dokumen sumber XML"
    _order = "id"

    document_id = fields.Many2one("rasentra.xml.document", required=True, ondelete="cascade", index=True)
    source_line_key = fields.Char()
    legacy_item_code = fields.Char(help="Kode barang apa adanya (nol di depan dipertahankan).")
    quantity = fields.Char()
    uom = fields.Char()
    unit_price = fields.Char()
    line_discount_pct = fields.Char()
    ref_invoice_no = fields.Char()
    amount = fields.Char()
    raw = fields.Json()
