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

    # ---- titik temu addon dengan sinkron --------------------------------------
    # Addon lain (promo, resep, cooking fee) mendaftarkan jenis publikasinya dengan atribut
    # `_rasentra_sync_entity` di model, tanpa harus bergantung pada addon sinkron:
    #   _rasentra_sync_payload()            payload untuk Lokal (Central)
    #   _rasentra_sync_snapshot(outlet)     daftar (entity_key, payload) untuk snapshot (Central)
    #   _rasentra_sync_ack(device, ack)     status penerimaan dari Lokal (Central)
    #   _rasentra_sync_apply(payload)       terapkan publikasi (Lokal)

    @api.model
    def sync_models(self):
        return [
            self.env[name]
            for name, cls in self.env.registry.items()
            if getattr(cls, "_rasentra_sync_entity", None) and not cls._abstract
        ]

    @api.model
    def sync_model(self, entity_type):
        return next((m for m in self.sync_models() if m._rasentra_sync_entity == entity_type), None)

    @api.model
    def publish(self, entity_type, entity_key, payload, outlets=None):
        """Terbitkan publikasi master bila instalasi ini Central dan addon sinkron Central terpasang."""
        if not self.is_central() or "rasentra.sync.publication" not in self.env:
            return None
        return self.env["rasentra.sync.publication"].publish(entity_type, entity_key, payload, outlets)
