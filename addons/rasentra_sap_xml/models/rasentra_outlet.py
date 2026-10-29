from odoo import api, fields, models


class RasentraOutlet(models.Model):
    _inherit = "rasentra.outlet"

    sap_posting_channel = fields.Selection(
        [("service_layer", "Service Layer"), ("xml", "File XML (sistem lama)")], string="Jalur posting SAP",
        default="service_layer", required=True,
        help="Satu kejadian hanya diposting lewat satu jalur. Outlet jalur XML tidak diposting oleh Service Layer.")


class RasentraHqOrder(models.Model):
    _inherit = "rasentra.hq.order"

    sap_state = fields.Selection(selection_add=[("via_xml", "Jalur XML")], ondelete={"via_xml": "set default"})


class RasentraSapDocument(models.Model):
    _inherit = "rasentra.sap.document"

    @api.model
    def post_order(self, order):
        if order.sudo().outlet_id.sap_posting_channel == "xml":
            order.sudo()._set_sap_state("via_xml")
            return "via_xml"
        return super().post_order(order)
