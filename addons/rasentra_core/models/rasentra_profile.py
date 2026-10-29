from odoo import api, models

PROFILE_PARAM = "rasentra.profile"


class RasentraProfile(models.AbstractModel):
    """Profil instalasi, padanan RASENTRA_PROFILE: `central` di kantor pusat, `lokal` di outlet."""

    _name = "rasentra.profile"
    _description = "Profil instalasi Rasentra"

    @api.model
    def get(self):
        return self.env["ir.config_parameter"].sudo().get_param(PROFILE_PARAM, "lokal")

    @api.model
    def is_central(self):
        return self.get() == "central"

    @api.model
    def is_lokal(self):
        return self.get() == "lokal"

    @api.model
    def current_outlet(self):
        """Outlet yang dilayani instalasi Lokal ini (parameter rasentra.outlet_code)."""
        code = self.env["ir.config_parameter"].sudo().get_param("rasentra.outlet_code")
        if not code:
            return self.env["rasentra.outlet"]
        return self.env["rasentra.outlet"].sudo().search([("code", "=", code)], limit=1)
