from odoo.tests import TransactionCase, tagged

from odoo.addons.rasentra_core.tools import RasentraError
from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_reconcile.tests.test_reconcile import TestReconcile

from .. import sample, tools


@tagged("post_install", "-at_install", "rasentra")
class TestSapXml(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.msi, cls.msr = sample.build()
        cls.Batch = cls.env["rasentra.xml.batch"]
        cls.Doc = cls.env["rasentra.xml.document"]

    def test_u32_sample_counts_and_total(self):
        """U32: sampel 28 Oktober 2026 = 49 invoice, 182 baris (60 pecahan), total Rp18.811.355."""
        batch = self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        s = batch.summary
        self.assertEqual(batch.status, "staged")
        self.assertEqual((s["invoices"], s["lines"], s["fractional_lines"]), (49, 182, 60))
        self.assertEqual(s["invoice_total"], "18811355.00")
        self.assertEqual(len(batch.attachment_id.raw), len(self.msi))
        self.assertEqual(len(batch.sha256), 64)

    def test_u33_rounding_difference_kept(self):
        """U33: selisih pembulatan sistem lama (Rp0,40) disimpan per dokumen, bukan dibuang."""
        batch = self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        diffs = batch.summary["rounding_differences"]
        self.assertEqual([(d["invoice_no"], d["difference"]) for d in diffs], [("SI-2610-0007", "-0.4000")])
        doc = self.Doc.search([("source_no", "=", "SI-2610-0007")])
        self.assertTrue(doc.has_difference)
        self.assertEqual(doc.document_total_calculated, "244641.4000")

    def test_u34_same_file_other_name_is_duplicate(self):
        """U34: file yang sama dengan nama berbeda tidak membuat dokumen ganda."""
        self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        again = self.Batch.import_xml(self.msi, "salinan-msi.xml", "MSI")
        self.assertEqual((again.document_count, again.duplicate_count), (0, 49))
        self.assertEqual(self.Doc.search_count([("doc_type", "=", "SALESINVOICE")]), 49)

    def test_u35_receipt_before_invoice_waits(self):
        """U35: MSR yang datang lebih dulu menunggu invoice, lalu dilepas setelah MSI diimpor."""
        receipts = self.Batch.import_xml(self.msr, "MSR_20261028.xml", "MSR")
        self.assertEqual(len(receipts.summary["waiting_dependency"]), 49)
        self.assertEqual(receipts.summary["payment_total"], "18811355.00")
        self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        statuses = set(self.Doc.search([("doc_type", "=", "CUSTOMERRECEIPT")]).mapped("status"))
        self.assertEqual(statuses, {"staged"})

    def test_u36_xxe_and_doctype_rejected(self):
        """U36: XML dengan DOCTYPE/ENTITY (XXE, billion laughs) ditolak dan tetap tercatat."""
        xxe = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
               b"<NMEXML><SALESINVOICE><INVOICENO>&x;</INVOICENO></SALESINVOICE></NMEXML>")
        batch = self.Batch.import_xml(xxe, "evil.xml", "MSI")
        self.assertEqual((batch.status, batch.error_code, batch.document_count), ("rejected", "xml_doctype_forbidden", 0))
        self.assertFalse(self.Doc.search_count([]))
        with self.assertRaises(RasentraError) as caught:
            tools.parse(b"<NMEXML><SALESINVOICE>")
        self.assertEqual(caught.exception.code, "xml_invalid")
        with self.assertRaises(RasentraError) as caught:
            tools.parse(b"<OTHER/>")
        self.assertEqual(caught.exception.code, "xml_root_invalid")
        with self.assertRaises(RasentraError) as caught:
            tools.parse(b"<NMEXML>" + b"<X/>" * 20 + b"</NMEXML>", max_elements=10)
        self.assertEqual(caught.exception.code, "xml_too_many_elements")

    def test_u37_missing_empty_zero_and_leading_zero(self):
        """U37: field hilang, kosong dan nol dibedakan; kode barang tetap string."""
        parsed = tools.parse(b"<NMEXML><SALESINVOICE><INVOICENO>1</INVOICENO><CASHDISCOUNT>0</CASHDISCOUNT>"
                             b"<TAXCODES></TAXCODES><ITEMLINE><ITEMNO>000123</ITEMNO></ITEMLINE>"
                             b"</SALESINVOICE></NMEXML>")
        inv = parsed["invoices"][0]
        self.assertEqual((inv["cash_discount"], inv["tax_codes"], inv["ar_account"]), ("0", "", None))
        self.assertEqual(inv["lines"][0]["item_no"], "000123")
        self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        line = self.env["rasentra.xml.line"].search([("legacy_item_code", "=", "00001")])
        self.assertEqual(line.legacy_item_code, "00001")

    def test_batch_file_is_immutable(self):
        batch = self.Batch.import_xml(self.msi, "MSI_20261028.xml", "MSI")
        with self.assertRaises(RasentraError):
            batch.write({"file_name": "lain.xml"})


@tagged("post_install", "-at_install", "rasentra")
class TestXmlPostingChannel(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "central")
        cls.sirloin.default_code = "SIRLOIN-AUS"
        cls.device = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": cls.outlet.id, "app": "lokal"})
        cls.Inbox = cls.env["rasentra.sync.inbox"]

    send = TestReconcile.send
    sale = TestReconcile.sale

    def test_u38_posting_channel_xml_skips_service_layer(self):
        """U38: outlet jalur XML tidak diposting lagi oleh Service Layer (satu kejadian satu jalur)."""
        payload = self.sale("SLO-MS-261028-00009", 270000)
        order = self.env["rasentra.hq.order"].search([("uuid", "=", payload["id"])])
        self.outlet.sap_posting_channel = "xml"
        summary = self.env["rasentra.sap.document"].post_pending()
        self.assertEqual((order.sap_state, summary), ("via_xml", {"via_xml": 1}))
        self.assertFalse(self.env["rasentra.sap.document"].search([("source_uuid", "=", order.uuid)]))
        self.assertFalse(self.env["rasentra.sap.document"].post_pending(), "tidak diambil ulang oleh cron")

