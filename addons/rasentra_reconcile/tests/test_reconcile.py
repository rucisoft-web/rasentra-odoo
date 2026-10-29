from odoo.tests import tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_core.tools import checksum, uuid7


@tagged("post_install", "-at_install", "rasentra")
class TestReconcile(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "central")
        cls.sirloin.default_code = "SIRLOIN-AUS"
        cls.device = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": cls.outlet.id, "app": "lokal"}
        )
        cls.Inbox = cls.env["rasentra.sync.inbox"]
        cls.Rec = cls.env["rasentra.day.reconciliation"]

    def send(self, event_type, payload, entity_type="order", version=1):
        event = {
            "event_id": uuid7(), "source_id": "SLO-MS-SRV", "outlet_id": "SLO-MS", "entity_type": entity_type,
            "entity_id": payload.get("id") or uuid7(), "entity_version": version, "event_type": event_type,
            "business_date": payload["business_date"], "payload": payload, "checksum": checksum(payload),
        }
        return self.Inbox._receive_one(self.device, event)

    def sale(self, doc_no, net, promo=None):
        gross = net + (promo or 0)
        line = {"id": uuid7(), "line_no": 1, "line_type": "meat_pack", "product_id": "SIRLOIN-AUS",
                "product_code": "SIRLOIN-AUS", "pack_code": "PK-1", "quantity": "1.500000", "uom": "kg",
                "unit_price": "200000.00", "gross_amount": f"{gross}.00", "discount_amount": f"{promo or 0}.00",
                "net_amount": f"{net}.00",
                "discounts": [{"promotion_version_id": "PROMO-UUID", "amount": f"{promo}.00", "funded_by": "supplier"}]
                if promo else []}
        payload = {"id": uuid7(), "doc_no": doc_no, "outlet_id": "SLO-MS", "channel": "retail",
                   "business_date": "2026-10-28", "gross_amount": f"{gross}.00", "discount_amount": f"{promo or 0}.00",
                   "net_amount": f"{net}.00", "finalized_at": "2026-10-28T05:00:00Z", "lines": [line],
                   "payments": [{"id": uuid7(), "method": "cash", "amount": f"{net}.00", "status": "succeeded"}]}
        self.send("order.finalized", payload)
        return payload

    def ret(self, doc_no, original, net):
        payload = {"id": uuid7(), "doc_no": doc_no, "original_order_id": original["id"],
                   "original_doc_no": original["doc_no"], "outlet_id": "SLO-MS", "channel": "retail",
                   "business_date": "2026-10-28", "reason": "bau", "gross_amount": f"{net}.00",
                   "discount_amount": "0.00", "net_amount": f"{net}.00",
                   "refund": {"method": "cash", "amount": f"{net}.00", "ref": None},
                   "finalized_at": "2026-10-28T06:00:00Z",
                   "lines": [{"line_no": 1, "order_line_no": 1, "line_type": "meat_pack", "product_id": "SIRLOIN-AUS",
                              "pack_id": "PK-1", "quantity": "1.500000", "uom": "kg", "unit_price": "200000.00",
                              "gross_amount": f"{net}.00", "discount_amount": "0.00", "net_amount": f"{net}.00",
                              "disposition": "quarantine"}]}
        self.send("order.returned", payload, entity_type="sales_return")
        return payload

    def close(self, docs, net, returns=(), returns_net=0, version=1):
        payload = {"outlet_code": "SLO-MS", "business_date": "2026-10-28", "closed_at": "2026-10-28T21:00:00Z",
                   "orders": len(docs), "net_amount": f"{net}.00", "doc_nos": list(docs),
                   "returns": len(returns), "returns_net_amount": f"{returns_net}.00",
                   "return_doc_nos": list(returns), "shifts": [{"id": "S1", "cash_difference": "-5000.00"}],
                   "cash_difference": "-5000.00", "open_shifts": 0}
        self.send("business_day.closed", payload, entity_type="business_day", version=version)
        return self.Rec.search([("outlet_id", "=", self.outlet.id), ("business_date", "=", "2026-10-28")])

    def test_projection_with_promo_and_return(self):
        sale = self.sale("SLO-MS-261028-00001", 270000, promo=30000)
        self.ret("SLO-MS-R261028-0001", sale, 270000)
        Order = self.env["rasentra.hq.order"]
        docs = Order.search([("outlet_id", "=", self.outlet.id)])
        self.assertEqual(sorted(docs.mapped("kind")), ["return", "sale"])
        self.assertEqual(sum(docs.mapped("net_amount")), 0)
        hq_sale = docs.filtered(lambda d: d.kind == "sale")
        self.assertEqual(hq_sale.line_ids.product_id, self.sirloin)
        self.assertEqual(hq_sale.discount_ids.funded_by, "supplier")
        hq_return = docs - hq_sale
        self.assertEqual(hq_return.original_order_id, hq_sale)
        self.assertEqual(hq_return.line_ids.quantity, -1.5)
        self.assertEqual(hq_return.payment_ids.amount, -270000)

    def test_duplicate_event_projects_once(self):
        payload = self.sale("SLO-MS-261028-00001", 300000)
        event = self.Inbox.search([("entity_uuid", "=", payload["id"])])
        self.env["rasentra.hq.order"].project(event)
        self.assertEqual(self.env["rasentra.hq.order"].search_count([("uuid", "=", payload["id"])]), 1)

    def test_waiting_then_matched_when_late_receipt_arrives(self):
        self.sale("SLO-MS-261028-00001", 300000)
        rec = self.close(["SLO-MS-261028-00001", "SLO-MS-261028-00002"], 650000)
        self.assertEqual(rec.status, "waiting")
        self.assertEqual(rec.missing_doc_nos, ["SLO-MS-261028-00002"])
        self.sale("SLO-MS-261028-00002", 350000)
        self.assertEqual(rec.status, "matched")
        self.assertEqual(rec.cash_difference, -5000)

    def test_mismatch_amount_and_old_version_ignored(self):
        self.sale("SLO-MS-261028-00001", 300000)
        rec = self.close(["SLO-MS-261028-00001"], 310000, version=2)
        self.assertEqual(rec.status, "mismatch")
        self.close(["SLO-MS-261028-00001"], 300000, version=1)
        self.assertEqual(rec.closing_version, 2, "versi lama yang datang terlambat diabaikan")
        rec = self.close(["SLO-MS-261028-00001"], 300000, version=3)
        self.assertEqual(rec.status, "matched")

    def test_returns_are_part_of_reconciliation(self):
        sale = self.sale("SLO-MS-261028-00001", 300000)
        rec = self.close(["SLO-MS-261028-00001"], 300000, returns=["SLO-MS-R261028-0001"], returns_net=300000)
        self.assertEqual(rec.status, "waiting")
        self.ret("SLO-MS-R261028-0001", sale, 300000)
        self.assertEqual(rec.status, "matched")
