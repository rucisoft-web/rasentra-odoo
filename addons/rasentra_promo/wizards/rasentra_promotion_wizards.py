import json

from odoo import fields, models

from odoo.addons.rasentra_core.models.rasentra_price_version import CHANNELS


class RasentraPromotionSimulate(models.TransientModel):
    _name = "rasentra.promotion.simulate"
    _description = "Simulasi promo"

    version_id = fields.Many2one("rasentra.promotion.version", required=True)
    outlet_id = fields.Many2one("rasentra.outlet", required=True)
    channel = fields.Selection(CHANNELS, required=True, default="retail")
    line_ids = fields.One2many("rasentra.promotion.simulate.line", "wizard_id", string="Keranjang contoh")
    result = fields.Text(readonly=True)
    this_discount = fields.Char(readonly=True)

    def action_simulate(self):
        self.ensure_one()
        result = self.version_id.simulate(
            self.outlet_id, self.channel, [(line.product_id, line.quantity) for line in self.line_ids]
        )
        self.write({"result": json.dumps(result["after"], indent=2, ensure_ascii=False),
                    "this_discount": result["this_discount"]})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}


class RasentraPromotionSimulateLine(models.TransientModel):
    _name = "rasentra.promotion.simulate.line"
    _description = "Baris keranjang simulasi"

    wizard_id = fields.Many2one("rasentra.promotion.simulate", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, domain=[("rasentra_type", "!=", False)])
    quantity = fields.Float(digits=(18, 6), required=True, default=1.0)


class RasentraPromotionPublish(models.TransientModel):
    _name = "rasentra.promotion.publish"
    _description = "Terbitkan promo"

    version_id = fields.Many2one("rasentra.promotion.version", required=True)
    target_all = fields.Boolean(string="Semua outlet")
    region_ids = fields.Many2many("rasentra.region", string="Wilayah")
    outlet_ids = fields.Many2many("rasentra.outlet", string="Outlet")

    def action_publish(self):
        self.ensure_one()
        self.version_id.publish({"all": self.target_all, "regions": self.region_ids.mapped("code"),
                                 "outlets": self.outlet_ids.mapped("code")})


class RasentraPromotionStop(models.TransientModel):
    _name = "rasentra.promotion.stop"
    _description = "Hentikan promo"

    version_id = fields.Many2one("rasentra.promotion.version", required=True)
    reason = fields.Char(required=True)

    def action_stop(self):
        self.ensure_one()
        self.version_id.stop(self.reason)
