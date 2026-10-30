from odoo.tests import tagged

from odoo.addons.rasentra_reconcile.tests.test_reconcile import TestReconcile

from odoo.addons.rasentra_core.tools import uuid7

from ..tools import FAKE_CONTROL


@tagged("post_install", "-at_install", "rasentra")
class TestSapPosting(TestReconcile):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Mapping = cls.env["rasentra.sap.mapping"]
        for entity_type, key, code in (
            ("product", "SIRLOIN-AUS", "FG-SIRLOIN"), ("outlet", "SLO-MS", "WH-SLO-MS"),
            ("customer", "walk_in", "C-UMUM"), ("payment_method", "cash", "110101"),
            ("payment_method", "qris", "110202"),
        ):
            Mapping.create({"company_db": "sap_solo", "entity_type": entity_type, "entity_key": key, "sap_code": code})
        cls.Doc = cls.env["rasentra.sap.document"]
        cls.Fake = cls.env["rasentra.sap.fake.document"]

    def setUp(self):
        super().setUp()
        FAKE_CONTROL.update(fail_next={}, timeout_after_commit_once=False, unreachable=False)

    def hq(self, payload):
        return self.env["rasentra.hq.order"].search([("uuid", "=", payload["id"])])

    def test_sale_posts_invoice_and_payment_once(self):
        order = self.hq(self.sale("SLO-MS-261028-00001", 270000, promo=30000))
        self.assertEqual(order.sap_state, "pending")
        self.Doc.post_pending()
        self.assertEqual(order.sap_state, "posted")
        self.assertEqual(sorted(order.sap_document_ids.mapped("sap_object")), ["IncomingPayments", "Invoices"])
        invoice = order.sap_document_ids.filtered(lambda d: d.sap_object == "Invoices")
        self.assertEqual(invoice.request_payload["DocumentLines"][0]["ItemCode"], "FG-SIRLOIN")
        self.assertEqual(invoice.request_payload["DocumentLines"][0]["LineTotal"], "270000.00")
        self.assertEqual(invoice.request_payload["DocumentLines"][0]["WarehouseCode"], "WH-SLO-MS")
        self.Doc.post_order(order)
        self.assertEqual(self.Fake.search_count([]), 2, "posting ulang tidak membuat dokumen baru")

    def test_u16_partial_then_retry_posts_only_payment(self):
        """U16: invoice terposting, pembayaran gagal; retry hanya memposting pembayaran."""
        FAKE_CONTROL["fail_next"] = {"IncomingPayments": 1}
        order = self.hq(self.sale("SLO-MS-261028-00001", 300000))
        self.Doc.post_order(order)
        self.assertEqual(order.sap_state, "partially_posted")
        payment = order.sap_document_ids.filtered(lambda d: d.sap_object == "IncomingPayments")
        self.assertEqual((payment.status, payment.last_error), ("failed", "SAP menolak IncomingPayments"))
        self.Doc.post_pending()
        self.assertEqual(order.sap_state, "posted")
        self.assertEqual(self.Fake.search_count([("sap_object", "=", "Invoices")]), 1)
        self.assertEqual(payment.attempts, 2)

    def test_u15_timeout_after_commit_is_recovered_without_duplicate(self):
        FAKE_CONTROL["timeout_after_commit_once"] = True
        order = self.hq(self.sale("SLO-MS-261028-00001", 300000))
        self.Doc.post_order(order)
        invoice = order.sap_document_ids.filtered(lambda d: d.sap_object == "Invoices")
        self.assertEqual(invoice.status, "needs_review")
        self.Doc.recover()
        self.assertEqual(invoice.status, "posted")
        self.Doc.post_pending()
        self.assertEqual(order.sap_state, "posted")
        self.assertEqual(self.Fake.search_count([("sap_object", "=", "Invoices")]), 1)

    def test_missing_mapping_raises_one_exception(self):
        payload = self.sale("SLO-MS-261028-00001", 300000)
        payload_order = self.hq(payload)
        payload_order.line_ids.product_code = "WAGYU-MB9"
        self.Doc.post_order(payload_order)
        self.Doc.post_order(payload_order)
        exceptions = self.env["rasentra.integration.exception"].search([("source_uuid", "=", payload["id"])])
        self.assertEqual(len(exceptions), 1)
        self.assertIn("product:WAGYU-MB9", exceptions.message)
        self.assertEqual(payload_order.sap_state, "failed")
        self.assertFalse(payload_order.sap_document_ids)

    def test_return_waits_for_invoice_then_posts_credit_memo(self):
        sale = self.sale("SLO-MS-261028-00001", 300000)
        ret = self.hq(self.ret("SLO-MS-R261028-0001", sale, 300000))
        self.Doc.post_order(ret)
        self.assertEqual(ret.sap_state, "waiting_dependency")
        self.Doc.post_pending()
        self.assertEqual((self.hq(sale).sap_state, ret.sap_state), ("posted", "posted"))
        memo = ret.sap_document_ids.filtered(lambda d: d.sap_object == "CreditNotes")
        invoice = self.hq(sale).sap_document_ids.filtered(lambda d: d.sap_object == "Invoices")
        line = memo.request_payload["DocumentLines"][0]
        self.assertEqual((line["BaseType"], line["BaseEntry"], line["BaseLine"]), (13, invoice.doc_entry, 0))
        self.assertEqual(line["Quantity"], "1.5")
        refund = ret.sap_document_ids.filtered(lambda d: d.sap_object == "VendorPayments")
        self.assertEqual(refund.request_payload["CashSum"], "300000.00")

    def test_health(self):
        self.assertTrue(self.Doc.check_health()["sap_solo"]["ok"])
        FAKE_CONTROL["unreachable"] = True
        self.assertFalse(self.Doc.check_health()["sap_solo"]["ok"])

    def _adjustment(self, kind, lines):
        payload = {"id": uuid7(), "doc_no": f"SLO-MS-{kind[:2].upper()}261028-0001", "outlet_id": "SLO-MS", "kind": kind,
                   "reason": "uji", "source": None, "business_date": "2026-10-28", "lines": lines}
        self.send("stock.adjusted", payload, entity_type="stock_adjustment")
        return self.env["rasentra.hq.stock.adjustment"].search([("uuid", "=", payload["id"])])

    def test_stock_adjustments_become_goods_issue_and_receipt(self):
        line = {"line_no": 1, "product_id": "SIRLOIN-AUS", "product_code": "SIRLOIN-AUS", "pack_id": "PK-9",
                "quantity": "1.200000", "uom": "kg"}
        waste = self._adjustment("waste", [dict(line, from_state="available", to_state=None)])
        self.assertEqual(waste.line_ids.signed_quantity, -1.2)
        production = self._adjustment("production", [
            dict(line, from_state="available", to_state=None),
            dict(line, line_no=2, pack_id=None, quantity="1.100000", from_state=None, to_state="available"),
        ])
        release = self._adjustment("release", [dict(line, from_state="quarantine", to_state="available")])
        self.Doc.post_pending()
        self.assertEqual(waste.sap_state, "posted")
        self.assertEqual(waste.sap_document_ids.sap_object, "InventoryGenExits")
        self.assertEqual(waste.sap_document_ids.request_payload["DocumentLines"][0]["WarehouseCode"], "WH-SLO-MS")
        self.assertEqual(sorted(production.sap_document_ids.mapped("sap_object")), ["InventoryGenEntries", "InventoryGenExits"])
        self.assertEqual(release.sap_state, "not_required")
        # Event berulang tidak membuat proyeksi baru.
        self.assertEqual(self.env["rasentra.hq.stock.adjustment"].search_count([]), 3)
