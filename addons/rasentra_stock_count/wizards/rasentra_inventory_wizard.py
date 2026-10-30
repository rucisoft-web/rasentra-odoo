import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.rasentra_core.tools import RasentraError

MODES = [
    ("receive", "Terima kiriman"),
    ("check", "Cek stok"),
    ("count", "Opname"),
    ("waste", "Waste"),
    ("release", "Lepas karantina"),
    ("hold", "Tahan pack"),
]


class RasentraInventoryWizard(models.TransientModel):
    """Layar handheld Rasentra Inventory: satu kolom scan, hasil tampil di bawahnya, layar tetap terbuka."""

    _name = "rasentra.inventory.wizard"
    _description = "Rasentra Inventory (handheld)"

    mode = fields.Selection(MODES, required=True, default="receive")
    outlet_id = fields.Many2one(
        "rasentra.outlet", required=True,
        default=lambda self: self.env["rasentra.profile"].current_outlet() or self.env["rasentra.outlet"].search([], limit=1),
    )
    employee_id = fields.Many2one(
        "hr.employee", string="Petugas", required=True,
        default=lambda self: self.env.user.employee_id,
    )
    code = fields.Char(string="Scan Pack ID / SKU")
    quantity = fields.Float(string="Jumlah", digits=(18, 3))
    reason = fields.Char(string="Alasan")
    reject = fields.Boolean(string="Tolak ke karantina")
    source = fields.Selection([("available", "Stok jual"), ("quarantine", "Karantina")], default="available", string="Dari")
    session_id = fields.Many2one("rasentra.count.session", string="Sesi opname",
                                 domain="[('outlet_id', '=', outlet_id), ('state', 'in', ('counting', 'recount'))]")
    location_code = fields.Char(string="Lokasi (QR)")
    approver_id = fields.Many2one("hr.employee", string="Penyetuju", domain="[('rasentra_role', 'in', ('outlet_head', 'admin'))]")
    pin = fields.Char(string="PIN penyetuju")
    message = fields.Text(readonly=True)
    message_level = fields.Selection([("ok", "OK"), ("error", "Error")], readonly=True)
    expected_html = fields.Html(compute="_compute_expected_html", sanitize=False)

    @api.depends("mode", "outlet_id", "message")
    def _compute_expected_html(self):
        for wizard in self:
            if wizard.mode == "receive" and wizard.outlet_id:
                packs = self.env["rasentra.inventory"].expected(wizard.outlet_id)
                rows = "".join(f"<li>{p.name} · {p.product_id.name} · {p.net_weight:.3f} kg</li>" for p in packs)
                wizard.expected_html = (
                    f"<p><b>{len(packs)} pack dalam perjalanan</b></p><ul>{rows}</ul>" if packs else
                    "<p>Tidak ada pack yang menunggu diterima.</p>"
                )
            elif wizard.mode in ("waste", "release") and wizard.outlet_id:
                data = self.env["rasentra.inventory"].quarantine(wizard.outlet_id)
                rows = "".join(f"<li>{p['pack_code']} · {p['product']} · {p['status']} · {p['reason'] or ''}</li>" for p in data["packs"])
                rows += "".join(f"<li>{i['code']} · {i['product']} · {i['quantity']} {i['uom']}</li>" for i in data["items"])
                wizard.expected_html = f"<p><b>Isi karantina</b></p><ul>{rows}</ul>" if rows else "<p>Karantina kosong.</p>"
            else:
                wizard.expected_html = False

    def _approval(self):
        return {"approver_id": self.approver_id.id, "pin": self.pin} if self.approver_id and self.pin else None

    def action_process(self):
        self.ensure_one()
        Inventory = self.env["rasentra.inventory"]
        try:
            with self.env.cr.savepoint():
                if not self.code:
                    raise RasentraError("code_required", _("Scan kode dulu."))
                if self.mode == "receive":
                    pack = Inventory.receive(self.outlet_id, self.code, self.employee_id,
                                             "reject" if self.reject else "accept", self.reason)
                    text = _("%(code)s %(status)s", code=pack.name,
                             status=_("ditolak ke karantina") if self.reject else _("diterima"))
                elif self.mode == "check":
                    text = json.dumps(Inventory.check(self.outlet_id, self.code), indent=1, ensure_ascii=False)
                elif self.mode == "count":
                    if not self.session_id:
                        raise RasentraError("session_required", _("Pilih sesi opname."))
                    line = self.session_id.record_scan(self.employee_id, self.code, self.quantity, self.location_code or "")
                    text = _("Tercatat %(product)s %(qty)s di %(loc)s", product=line.product_id.name,
                             qty=line.quantity, loc=line.location_id.name)
                elif self.mode == "hold":
                    pack = Inventory.hold(self.outlet_id, self.employee_id, self.code, self.reason)
                    text = _("%s ditahan.", pack.name)
                else:
                    method = Inventory.waste if self.mode == "waste" else Inventory.release
                    kwargs = {"source": self.source} if self.mode == "waste" else {}
                    doc = method(self.outlet_id, self.employee_id, self.code, self.quantity, self.reason, self._approval(), **kwargs)
                    text = _("Dokumen %s dibuat.", doc.doc_no)
                self.write({"message": text, "message_level": "ok", "code": False, "quantity": 0, "pin": False})
        except UserError as error:
            self.write({"message": str(error.args[0] if error.args else error), "message_level": "error", "pin": False})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }
