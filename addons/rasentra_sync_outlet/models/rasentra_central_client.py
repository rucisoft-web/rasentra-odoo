import requests

from odoo import _, api, models
from odoo.exceptions import UserError


class RasentraCentralClient(models.AbstractModel):
    """Klien HTTP ke /api/v1/sync di Rasentra Central dengan token server outlet (padanan CentralClient)."""

    _name = "rasentra.central.client"
    _description = "Klien Rasentra Central"

    @api.model
    def _request(self, method, path, json=None, params=None, timeout=20):
        config = self.env["ir.config_parameter"].sudo()
        url = (config.get_param("rasentra.central_url") or "").rstrip("/")
        if not url:
            raise UserError(_("Parameter rasentra.central_url belum diisi."))
        response = requests.request(
            method,
            f"{url}/api/v1/sync/{path}",
            json=json,
            params=params,
            timeout=timeout,
            headers={"Authorization": f"Bearer {config.get_param('rasentra.central_token') or ''}",
                     "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
