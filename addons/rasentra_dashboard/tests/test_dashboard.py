from odoo.tests import HttpCase, tagged

from odoo.addons.rasentra_core.tests.common import RasentraCase
from odoo.addons.rasentra_reconcile.tests.test_reconcile import TestReconcile


@tagged("post_install", "-at_install", "rasentra")
class TestDashboard(RasentraCase):
    send = TestReconcile.send
    sale = TestReconcile.sale
    ret = TestReconcile.ret

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("rasentra.profile", "central")
        cls.sirloin.default_code = "SIRLOIN-AUS"
        cls.device = cls.env["rasentra.device"].create(
            {"code": "SLO-MS-SRV", "name": "Server Solo", "outlet_id": cls.outlet.id, "app": "lokal"})
        cls.Inbox = cls.env["rasentra.sync.inbox"]

    def test_summary_nets_sales_and_returns(self):
        first = self.sale("SLO-MS-261028-00001", 270000)
        self.sale("SLO-MS-261028-00002", 130000)
        self.ret("SLO-MS-261028-R0001", first, 50000)
        data = self.env["rasentra.dashboard"].summary("2026-10-28")
        self.assertEqual(data["totals"], {"net": "350000.00", "orders": 2, "returns": "50000.00", "avg": "175000.00"})
        self.assertEqual(data["days"][-1], {"date": "2026-10-28", "net": "350000.00", "orders": 2})
        self.assertEqual(len(data["days"]), 7)
        company = next(c for c in data["companies"] if c["id"] == self.outlet.company_id.id)
        row = next(o for o in company["outlets"] if o["id"] == self.outlet.id)
        self.assertEqual((row["net"], row["orders"], row["health"]), ("350000.00", 2, "none"))
        self.assertEqual(data["channels"], [{"channel": "retail", "net": "350000.00", "orders": 2}])


@tagged("post_install", "-at_install", "rasentra")
class TestDashboardUi(HttpCase):
    def test_pages_render(self):
        for xmlid, css in (("rasentra_dashboard.action_dashboard", ".o_rasentra_dashboard .o_rasentra_tile"),
                           ("rasentra_monitor.action_monitor_status", ".o_rasentra_monitor .o_rasentra_tile")):
            code = (
                "const started = Date.now(); (function wait() {"
                f" if (document.querySelector('{css}')) {{ console.log('test successful'); }}"
                " else if (Date.now() - started > 60000) { console.error('halaman tidak tampil'); }"
                " else { setTimeout(wait, 500); } })();"
            )
            self.browser_js(f"/odoo/action-{xmlid}", code, login="admin", timeout=120)
