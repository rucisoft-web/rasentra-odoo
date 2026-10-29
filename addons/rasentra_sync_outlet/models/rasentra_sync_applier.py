"""Menerapkan publikasi Central ke database Rasentra Lokal (padanan PublicationApplier).

Setiap applier idempoten: dicari lewat kunci lintas-instalasi lalu dibuat atau diperbarui,
sehingga snapshot dan delta yang sama boleh diterapkan berkali-kali.
"""

from odoo import _, api, models

from odoo.addons.rasentra_core.tools import RasentraError


class RasentraSyncApplier(models.AbstractModel):
    _name = "rasentra.sync.applier"
    _description = "Penerap publikasi Rasentra"

    @api.model
    def apply(self, change):
        applier = self.sudo().with_context(rasentra_sync_applying=True, active_test=False, tracking_disable=True)
        handler = getattr(applier, "_apply_" + change["entity_type"], None)
        if handler is None:
            raise RasentraError("sync_unknown_type", _("Jenis publikasi %s belum dikenal.", change["entity_type"]))
        with self.env.cr.savepoint():
            handler(change["payload"])

    def _outlet_by_uuid(self, uuid):
        outlet = self.env["rasentra.outlet"].search([("uuid", "=", uuid)], limit=1)
        if not outlet:
            raise RasentraError("sync_missing_parent", _("Outlet %s belum ada di Rasentra Lokal.", uuid))
        return outlet

    def _apply_outlet(self, data):
        company = self.env.company
        company.write({"rasentra_legal_name": data["company"]["legal_name"],
                       "sap_company_db": data["company"]["sap_company_db"] or False})
        Region = self.env["rasentra.region"]
        region = Region.search([("code", "=", data["region"]["code"])], limit=1)
        if region:
            region.name = data["region"]["name"]
        else:
            region = Region.create({**data["region"], "company_id": company.id})
        vals = {
            "code": data["code"],
            "name": data["name"],
            "company_id": company.id,
            "region_id": region.id,
            "tz": data["tz"],
            "retail_name": data["retail_name"] or False,
            "restaurant_name": data["restaurant_name"] or False,
            "has_retail": data["has_retail"],
            "has_restaurant": data["has_restaurant"],
            "has_cooking_fee": data["has_cooking_fee"],
            "sap_warehouse_code": data["sap_warehouse_code"] or False,
            "active": data["active"],
        }
        outlet = self.env["rasentra.outlet"].search([("uuid", "=", data["uuid"])], limit=1)
        if outlet:
            outlet.write(vals)
        else:
            self.env["rasentra.outlet"].create({**vals, "uuid": data["uuid"]})

    def _apply_product(self, data):
        uom = self.env["uom.uom"].search([("name", "=", data["uom"])], limit=1)
        if not uom:
            raise RasentraError("sync_unknown_uom", _("Satuan %s tidak dikenal.", data["uom"]))
        vals = {
            "name": data["name"],
            "barcode": data["barcode"] or False,
            "rasentra_type": data["rasentra_type"],
            "kitchen_station": data["kitchen_station"] or False,
            "tracking": data["tracking"],
            "is_storable": data["is_storable"],
            "active": data["active"],
        }
        product = self.env["product.product"].search([("default_code", "=", data["default_code"])], limit=1)
        if product:
            if product.uom_id != uom:
                vals.update(uom_id=uom.id, uom_po_id=uom.id)
            product.write(vals)
        else:
            self.env["product.product"].create(
                {**vals, "default_code": data["default_code"], "type": "consu", "uom_id": uom.id, "uom_po_id": uom.id}
            )

    def _apply_employee(self, data):
        vals = {
            "name": data["name"],
            "rasentra_role": data["role"],
            "rasentra_outlet_id": self._outlet_by_uuid(data["outlet_uuid"]).id if data["outlet_uuid"] else False,
            "pin": data["pin"] or False,
            "approval_limit": float(data["approval_limit"]),
            "active": data["active"],
        }
        employee = self.env["hr.employee"].search([("rasentra_uuid", "=", data["uuid"])], limit=1)
        if employee:
            employee.write(vals)
        else:
            self.env["hr.employee"].create({**vals, "rasentra_uuid": data["uuid"]})

    def _apply_price_version(self, data):
        Version = self.env["rasentra.price.version"]
        if Version.search_count([("uuid", "=", data["uuid"])]):
            return  # versi published tidak pernah berubah; publikasi ulang cukup diabaikan
        codes = [item["product_code"] for item in data["items"]]
        products = {p.default_code: p for p in self.env["product.product"].search([("default_code", "in", codes)])}
        missing = [code for code in codes if code not in products]
        if missing:
            raise RasentraError("sync_missing_parent", _("Produk %s belum ada di Rasentra Lokal.", ", ".join(missing)))
        version = Version.create(
            {
                "uuid": data["uuid"],
                "code": data["code"],
                "outlet_id": self._outlet_by_uuid(data["outlet_uuid"]).id if data["outlet_uuid"] else False,
                "channel": data["channel"] or False,
                "effective_from": data["effective_from"],
                "effective_to": data["effective_to"] or False,
                "note": data["note"] or False,
                "item_ids": [
                    (0, 0, {"product_id": products[item["product_code"]].id, "unit_price": float(item["unit_price"])})
                    for item in data["items"]
                ],
            }
        )
        version.action_publish()
