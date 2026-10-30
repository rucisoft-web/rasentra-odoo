from odoo import http
from odoo.http import request


class RasentraKitchenController(http.Controller):
    @http.route("/rasentra/kitchen", type="http", auth="user")
    def kitchen(self, **kw):
        """Alamat tetap layar dapur (padanan /kitchen Laravel): membuka aplikasi KDS di backend."""
        action = request.env.ref("rasentra_kitchen.action_kitchen_board")
        return request.redirect(f"/odoo/action-{action.id}")
