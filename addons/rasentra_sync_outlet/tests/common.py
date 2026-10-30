from contextlib import contextmanager
from unittest.mock import patch

from odoo.addons.rasentra_core.tests.common import RasentraCase


class SyncOutletCase(RasentraCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("rasentra.profile", "lokal")
        params.set_param("rasentra.central_url", "https://central.test")
        params.set_param("rasentra.central_token", "rahasia")
        params.set_param("rasentra.device_code", "SLO-MS-SRV")
        params.set_param("rasentra.outlet_code", "SLO-MS")

    @contextmanager
    def _central(self, handler):
        """Ganti HTTP ke Central dengan `handler(method, path, json, params)`; catat setiap panggilan."""
        calls = []

        def request(model, method, path, json=None, params=None, timeout=20):
            calls.append((method, path, json, params))
            return handler(method, path, json, params)

        with patch.object(type(self.env["rasentra.central.client"]), "_request", request):
            yield calls
