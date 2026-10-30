from odoo import _, api, models

from ..tools import RasentraError, qty

LOCATION_LABELS = {
    "stock": "Stok jual",
    "chiller": "Chiller",
    "quarantine": "Karantina",
    "kitchen": "Dapur",
    "transit": "Transit",
}


class RasentraStockLedger(models.AbstractModel):
    """Padanan StockLedger Laravel di atas stock.move Odoo.

    Setiap pergerakan Rasentra (konsumsi resep, produksi, waste, terima pack, opname) menjadi satu
    stock.move berstatus done antara lokasi outlet dan lokasi virtual perusahaan. Saldo diambil dari
    stock.quant / stock.move.line, sehingga laporan stok standar Odoo tetap berlaku.
    """

    _name = "rasentra.stock.ledger"
    _description = "Ledger stok Rasentra"

    @api.model
    def location(self, outlet, kind="stock"):
        """Lokasi fisik outlet per jenis. Dibuat otomatis bila belum ada (di bawah stok outlet)."""
        outlet = outlet.sudo()
        found = outlet.location_ids.filtered(lambda loc: loc.rasentra_type == kind and loc.active)[:1]
        if found:
            return found
        if kind == "stock" and outlet.warehouse_id:
            return outlet.warehouse_id.lot_stock_id
        if kind == "stock":
            parent = self.env.ref("stock.stock_location_locations")
        else:
            # Karantina, dapur, dst. adalah saudara lokasi stok (bukan anaknya) agar tidak terhitung stok jual.
            parent = self.location(outlet, "stock").location_id or self.env.ref("stock.stock_location_locations")
        return self.env["stock.location"].sudo().create(
            {
                "name": f"{outlet.code} {LOCATION_LABELS.get(kind, kind)}",
                "usage": "internal",
                "location_id": parent.id,
                "company_id": outlet.company_id.id,
                "rasentra_outlet_id": outlet.id,
                "rasentra_type": kind,
            }
        )

    @api.model
    def virtual(self, company, usage):
        """Lokasi lawan: production (konsumsi/produksi), inventory (opname), scrap (waste), transit (kiriman pusat)."""
        Location = self.env["stock.location"].sudo()
        if usage == "transit":
            location = company.internal_transit_location_id
        elif usage == "scrap":
            location = Location.search([("scrap_location", "=", True), ("company_id", "in", [company.id, False])], limit=1)
        else:
            location = Location.search(
                [("usage", "=", usage), ("scrap_location", "=", False), ("company_id", "in", [company.id, False])],
                order="company_id", limit=1,
            )
        if not location:
            raise RasentraError("location_missing", _("Lokasi virtual %s belum ada untuk %s.", usage, company.name))
        return location

    @api.model
    def move(self, product, quantity, source, destination, reference, lot=None, origin=None, company=None):
        """Bukukan satu pergerakan selesai. `quantity` positif dalam satuan produk."""
        quantity = float(qty(quantity))
        if quantity <= 0:
            return self.env["stock.move"]
        company = company or destination.company_id or source.company_id or self.env.company
        move = self.env["stock.move"].sudo().create(
            {
                "name": reference,
                "origin": origin or reference,
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": quantity,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "company_id": company.id,
                "is_inventory": destination.usage == "inventory" or source.usage == "inventory",
            }
        )
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env["stock.move.line"].sudo().create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": quantity,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "lot_id": lot.id if lot else False,
                "company_id": company.id,
            }
        )
        move.picked = True
        move.with_context(inventory_mode=False)._action_done()
        return move

    @api.model
    def balance(self, product, location, at=None, lot=None):
        """Saldo produk di lokasi (termasuk anak lokasi), opsional per waktu cutoff."""
        domain = [("product_id", "=", product.id), ("state", "=", "done")]
        if at:
            domain.append(("date", "<=", at))
        if lot:
            domain.append(("lot_id", "=", lot.id))
        MoveLine = self.env["stock.move.line"].sudo()
        incoming = sum(MoveLine.search(domain + [("location_dest_id", "child_of", location.id),
                                                 "!", ("location_id", "child_of", location.id)]).mapped("quantity_product_uom"))
        outgoing = sum(MoveLine.search(domain + [("location_id", "child_of", location.id),
                                                 "!", ("location_dest_id", "child_of", location.id)]).mapped("quantity_product_uom"))
        return qty(incoming - outgoing)
