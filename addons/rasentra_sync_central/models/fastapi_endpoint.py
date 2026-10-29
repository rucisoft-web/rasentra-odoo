from odoo import fields, models

from ..routers import sync_router


class FastapiEndpoint(models.Model):
    _inherit = "fastapi.endpoint"

    app = fields.Selection(selection_add=[("rasentra_sync", "Rasentra Sync")], ondelete={"rasentra_sync": "cascade"})

    def _get_fastapi_routers(self):
        if self.app == "rasentra_sync":
            return [sync_router]
        return super()._get_fastapi_routers()
