from odoo import api, fields, models
from odoo.exceptions import UserError

PAGE = 200
SERVER_ONLY_TYPES = ("employee",)  # berisi PIN, hanya untuk server Rasentra Lokal


class RasentraSyncPublication(models.Model):
    """Versi master yang turun ke outlet (padanan publication_versions). `id` adalah cursor monoton."""

    _name = "rasentra.sync.publication"
    _description = "Publikasi master Rasentra"
    _order = "id"

    # Char, bukan Selection: addon lain (promo, resep) menambah jenis tanpa bergantung pada addon ini.
    entity_type = fields.Char(required=True, index=True, readonly=True,
                              help="outlet, product, employee, price_version, promotion_version, ...")
    entity_key = fields.Char(required=True, index=True, readonly=True)
    payload = fields.Json(required=True, readonly=True)
    outlet_ids = fields.Many2many("rasentra.outlet", string="Outlet tujuan", readonly=True,
                                  help="Kosong = semua outlet.")
    create_date = fields.Datetime(readonly=True)

    def write(self, vals):
        raise UserError("Publikasi tidak bisa diubah; terbitkan versi baru.")

    @api.model
    def publish(self, entity_type, entity_key, payload, outlets=None):
        return self.sudo().create(
            {
                "entity_type": entity_type,
                "entity_key": entity_key,
                "payload": payload,
                "outlet_ids": [(6, 0, outlets.ids)] if outlets else [],
            }
        )

    @api.model
    def _visible_to(self, device, publication):
        if publication.outlet_ids and device.outlet_id not in publication.outlet_ids:
            return False
        return not (publication.entity_type in SERVER_ONLY_TYPES and device.app != "lokal")

    @api.model
    def changes_for(self, device, cursor=0):
        """Port SyncController::changes. next_cursor maju melewati seluruh halaman,
        termasuk publikasi untuk outlet lain."""
        page = self.sudo().search([("id", ">", int(cursor or 0))], order="id", limit=PAGE)
        return {
            "outlet_code": device.outlet_id.code,
            "changes": [
                {"id": p.id, "entity_type": p.entity_type, "entity_key": p.entity_key, "payload": p.payload}
                for p in page
                if self._visible_to(device, p)
            ],
            "next_cursor": max(page.ids) if page else int(cursor or 0),
            "has_more": len(page) == PAGE,
        }

    @api.model
    def snapshot_for(self, device):
        """Bootstrap Rasentra Lokal baru, berurutan sesuai ketergantungan (outlet, produk, petugas, harga)."""
        outlet = device.outlet_id
        last = self.sudo().search([], order="id desc", limit=1)
        changes = [{"id": None, "entity_type": "outlet", "entity_key": outlet.uuid, "payload": outlet._rasentra_sync_payload()}]
        products = self.env["product.product"].sudo().search(
            [("product_tmpl_id.rasentra_type", "!=", False), ("default_code", "!=", False)], order="id"
        )
        changes += [
            {"id": None, "entity_type": "product", "entity_key": p.default_code, "payload": p._rasentra_sync_payload()}
            for p in products
        ]
        employees = self.env["hr.employee"].sudo().search(
            [("rasentra_outlet_id", "=", outlet.id), ("rasentra_role", "!=", False), ("rasentra_uuid", "!=", False)], order="id"
        )
        changes += [
            {"id": None, "entity_type": "employee", "entity_key": e.rasentra_uuid, "payload": e._rasentra_sync_payload()}
            for e in employees
        ]
        versions = self.env["rasentra.price.version"].sudo().search(
            [("state", "=", "published"), "|", ("outlet_id", "=", False), ("outlet_id", "=", outlet.id)], order="id"
        )
        changes += [
            {"id": None, "entity_type": "price_version", "entity_key": v.uuid, "payload": v._rasentra_sync_payload()}
            for v in versions
        ]
        for model in self.env["rasentra.profile"].sync_models():
            if hasattr(model, "_rasentra_sync_snapshot"):
                changes += [
                    {"id": None, "entity_type": model._rasentra_sync_entity, "entity_key": key, "payload": payload}
                    for key, payload in model.sudo()._rasentra_sync_snapshot(outlet)
                ]
        return {"outlet_code": outlet.code, "cursor": last.id or 0, "changes": changes}
