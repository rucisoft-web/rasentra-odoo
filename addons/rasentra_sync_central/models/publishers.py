"""Payload publikasi master dan penerbitan otomatis di profil Central.

Payload memakai kunci lintas-instalasi (uuid outlet/versi harga, default_code produk,
rasentra_uuid petugas) karena id database Central dan Lokal berbeda.
"""

from odoo import api, fields, models

from odoo.addons.rasentra_core.tools import money

OUTLET_FIELDS = {
    "code", "name", "company_id", "region_id", "tz", "retail_name", "restaurant_name", "has_retail",
    "has_restaurant", "has_cooking_fee", "sap_warehouse_code", "active",
}
PRODUCT_FIELDS = {
    "default_code", "name", "barcode", "uom_id", "rasentra_type", "kitchen_station", "tracking", "is_storable", "active",
}
EMPLOYEE_FIELDS = {"name", "rasentra_role", "rasentra_outlet_id", "pin", "approval_limit", "active"}


def _central(env):
    return env["rasentra.profile"].is_central() and not env.context.get("rasentra_sync_applying")


class RasentraOutlet(models.Model):
    _inherit = "rasentra.outlet"

    def _rasentra_sync_payload(self):
        self.ensure_one()
        company, region = self.company_id, self.region_id
        return {
            "uuid": self.uuid,
            "code": self.code,
            "name": self.name,
            "company": {"name": company.name, "legal_name": company.rasentra_legal_name or company.name,
                        "sap_company_db": company.sap_company_db or None},
            "region": {"code": region.code, "name": region.name},
            "tz": self.tz,
            "retail_name": self.retail_name or None,
            "restaurant_name": self.restaurant_name or None,
            "has_retail": self.has_retail,
            "has_restaurant": self.has_restaurant,
            "has_cooking_fee": self.has_cooking_fee,
            "sap_warehouse_code": self.sap_warehouse_code or None,
            "active": self.active,
        }

    def _rasentra_publish(self):
        for outlet in self:
            self.env["rasentra.sync.publication"].publish("outlet", outlet.uuid, outlet._rasentra_sync_payload(), outlet)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if _central(self.env):
            records._rasentra_publish()
        return records

    def write(self, vals):
        res = super().write(vals)
        if OUTLET_FIELDS & set(vals) and _central(self.env):
            self._rasentra_publish()
        return res


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "default_code": self.default_code,
            "name": self.name,
            "barcode": self.barcode or None,
            "uom": self.uom_id.name,
            "rasentra_type": self.rasentra_type,
            "kitchen_station": self.kitchen_station or None,
            "tracking": self.tracking,
            "is_storable": self.is_storable,
            "active": self.active,
        }

    def _rasentra_publish(self):
        for product in self.with_context(active_test=False):
            if product.rasentra_type and product.default_code:
                self.env["rasentra.sync.publication"].publish(
                    "product", product.default_code, product._rasentra_sync_payload()
                )

    def write(self, vals):
        res = super().write(vals)
        if PRODUCT_FIELDS & set(vals) and _central(self.env):
            self._rasentra_publish()
        return res


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if _central(self.env):
            records.with_context(active_test=False).product_variant_ids._rasentra_publish()
        return records

    def write(self, vals):
        res = super().write(vals)
        if PRODUCT_FIELDS & set(vals) and _central(self.env):
            self.with_context(active_test=False).product_variant_ids._rasentra_publish()
        return res


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "uuid": self.rasentra_uuid,
            "name": self.name,
            "role": self.rasentra_role,
            "outlet_uuid": self.rasentra_outlet_id.uuid or None,
            "pin": self.pin or None,
            "approval_limit": str(money(self.approval_limit)),
            "active": self.active,
        }

    def _rasentra_publish(self):
        for employee in self.sudo():
            if employee.rasentra_role and employee.rasentra_uuid and employee.rasentra_outlet_id:
                self.env["rasentra.sync.publication"].publish(
                    "employee", employee.rasentra_uuid, employee._rasentra_sync_payload(), employee.rasentra_outlet_id
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if _central(self.env):
            records._rasentra_publish()
        return records

    def write(self, vals):
        res = super().write(vals)
        if EMPLOYEE_FIELDS & set(vals) and _central(self.env):
            self._rasentra_publish()
        return res


class RasentraPriceVersion(models.Model):
    _inherit = "rasentra.price.version"

    def _rasentra_sync_payload(self):
        self.ensure_one()
        return {
            "uuid": self.uuid,
            "code": self.code,
            "outlet_uuid": self.outlet_id.uuid or None,
            "channel": self.channel or None,
            "effective_from": fields.Datetime.to_string(self.effective_from),
            "effective_to": fields.Datetime.to_string(self.effective_to) if self.effective_to else None,
            "note": self.note or None,
            "items": [
                {"product_code": item.product_id.default_code, "unit_price": str(money(item.unit_price))}
                for item in self.item_ids
            ],
        }

    def _after_publish(self):
        super()._after_publish()
        if _central(self.env):
            for version in self:
                self.env["rasentra.sync.publication"].publish(
                    "price_version", version.uuid, version._rasentra_sync_payload(), version.outlet_id or None
                )
