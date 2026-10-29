from odoo.tests.common import TransactionCase


class RasentraDataMixin:
    """Data dasar Indoguna: CV Solo dengan outlet Meatshop Solo, satu produk daging."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_rasentra_data()

    @classmethod
    def _setup_rasentra_data(cls):
        """Dipisah agar kelas uji lain (mis. turunan TestPoSCommon) bisa memakai data yang sama."""
        cls.company = cls.env.company
        cls.company.write({"rasentra_legal_name": "CV Solo Kulina Utama", "sap_company_db": "sap_solo"})
        cls.region = cls.env["rasentra.region"].create({"code": "SLO", "name": "Solo"})
        cls.outlet = cls.env["rasentra.outlet"].create(
            {"code": "SLO-MS", "name": "Meatshop Solo", "region_id": cls.region.id, "has_restaurant": True}
        )
        cls.other_outlet = cls.env["rasentra.outlet"].create(
            {"code": "SLO-RB", "name": "Restoran R&B Solo", "region_id": cls.region.id}
        )
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.sirloin = cls.env["product.product"].create(
            {
                "name": "Sirloin AUS",
                "type": "consu",
                "is_storable": True,
                "uom_id": cls.kg.id,
                "uom_po_id": cls.kg.id,
                "rasentra_type": "meat_pack",
                "tracking": "lot",
            }
        )
        cls.head = cls.env["hr.employee"].create(
            {
                "name": "Kepala Solo",
                "rasentra_role": "outlet_head",
                "rasentra_outlet_id": cls.outlet.id,
                "pin": "4321",
                "approval_limit": 500000,
            }
        )
        cls.cashier = cls.env["hr.employee"].create(
            {"name": "Kasir Solo", "rasentra_role": "cashier", "rasentra_outlet_id": cls.outlet.id, "pin": "1111"}
        )

    @classmethod
    def _publish_price(cls, code, price, outlet=None, channel=None, product=None):
        version = cls.env["rasentra.price.version"].create(
            {
                "code": code,
                "outlet_id": outlet.id if outlet else False,
                "channel": channel,
                "effective_from": "2026-01-01 00:00:00",
                "item_ids": [(0, 0, {"product_id": (product or cls.sirloin).id, "unit_price": price})],
            }
        )
        version.action_publish()
        return version


class RasentraCase(RasentraDataMixin, TransactionCase):
    pass
