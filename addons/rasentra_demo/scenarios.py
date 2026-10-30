"""Skenario demo per peran: promo lengkap, stok & opname, POS dan dapur yang sedang berjalan, gelombang migrasi.

Setiap blok dijalankan dalam savepoint: bila satu skenario gagal (mis. versi Odoo berbeda), data lain tetap
terpasang dan peringatan dicatat di log.
"""

import logging
import random
import uuid
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)


def safe(env, label, func, *args):
    try:
        with env.cr.savepoint():
            return func(*args)
    except Exception:  # noqa: BLE001 - demo tetap jalan
        _logger.warning("Skenario demo '%s' dilewati", label, exc_info=True)
        return None


def _product(env, code):
    return env["product.product"].search([("default_code", "=", code)], limit=1)


def _xmlid(env, module, name, record):
    env["ir.model.data"].sudo()._update_xmlids([{"xml_id": f"{module}.{name}", "record": record, "noupdate": True}])
    return record


def _now_hour(hours=0):
    return (fields.Datetime.now() + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)


# ---- merchandising ---------------------------------------------------------------------

def promotions(env, module, spec, outlets):
    """Satu contoh untuk tiap tipe promo dan tiap status: terbit, menunggu persetujuan, draft, dihentikan,
    diganti versi baru. Pembuat = Tim Merchandising, penyetuju = Admin Pusat (maker-checker)."""
    merch = env.ref("rasentra_demo.user_hq_merch")
    admin = env.ref("rasentra_demo.user_hq_admin")
    region = spec["region"][0]
    retail = next(outlets[o["code"]] for o in spec["outlets"] if o.get("retail"))
    Version = env["rasentra.promotion.version"].with_user(merch)
    start = "2026-01-01 00:00:00"

    def draft(key, code, name, kind, rules, basket, channel="retail", **vals):
        promotion = env["rasentra.promotion"].create({"code": f"{code}-{region}", "name": name})
        version = Version.create({"promotion_id": promotion.id, "type": kind, "rules": rules,
                                  "starts_at": vals.pop("starts_at", start), **vals})
        _xmlid(env, module, f"promo_{key}", version)
        if basket:
            version.simulate(retail, channel, [(_product(env, c), q) for c, q in basket])
        return version

    def publish(version):
        version.with_user(admin).publish({"regions": [region]})
        return version

    publish(draft("weight_tier", "BBQ-TIER", "BBQ party: makin berat makin hemat", "weight_tier",
                  {"tiers": [{"min_weight": "2", "percent": 5}, {"min_weight": "3", "percent": 10}],
                   "product_ids": ["SIRLOIN-AUS", "SHORTRIB-US", "STRIPLOIN-AUS"]},
                  [("SIRLOIN-AUS", "1.8"), ("SHORTRIB-US", "1.4")], priority=60))
    publish(draft("bxgy", "SAUS-B2G1", "Beli 2 saus BBQ gratis 1", "buy_x_get_y",
                  {"buy_product_id": "RT-BBQ", "buy_qty": 2, "get_product_id": "RT-BBQ", "get_qty": 1,
                   "max_multiple": 2}, [("RT-BBQ", "3")], priority=70))
    publish(draft("special", "TENDER-SP", "Harga spesial Tenderloin Rp235.000/kg", "special_price",
                  {"price": "235000", "product_ids": ["TENDER-AUS"]}, [("TENDER-AUS", "1.2")],
                  ends_at=fields.Datetime.to_string(_now_hour(24 * 14)), priority=50, stacking="best_benefit"))
    publish(draft("bank", "BANK-RESTO", "Promo kartu bank 20% menu restoran", "percent",
                  {"percent": 20, "exclude_line_types": ["cooking_service"]},
                  [("MN-SIRLOIN", "2"), ("MN-TEA", "2")], channel="restaurant", channels=["restaurant"],
                  funded_by="bank", priority=80))
    # Menunggu persetujuan Admin Pusat (sudah disimulasi).
    draft("basket", "BELANJA-1JT", "Belanja Rp1 juta potong Rp50.000", "amount",
          {"amount": "50000", "min_spend": "1000000"}, [("RIBEYE-WAGYU", "1.6"), ("SIRLOIN-AUS", "1.5")],
          scope="basket")
    # Draft yang masih disusun (belum disimulasi).
    draft("supplier", "SALMON-SUP", "Salmon 15% dibiayai pemasok", "percent",
          {"percent": 15, "product_ids": ["SALMON-NOR"]}, None, funded_by="supplier",
          starts_at=fields.Datetime.to_string(_now_hour(24 * 7)))
    # Sudah dihentikan lebih awal.
    stopped = publish(draft("stopped", "MERDEKA", "Promo Agustus 17%", "percent",
                            {"percent": 17, "product_ids": ["CHICKEN-FILLET"]}, [("CHICKEN-FILLET", "2")]))
    stopped.with_user(admin).stop("Stok ayam promo habis lebih cepat")
    # Versi 1 diganti versi 2 (riwayat versi terlihat).
    v1 = publish(draft("sosis_v1", "SOSIS", "Sosis bratwurst hemat", "percent",
                       {"percent": 5, "product_ids": ["RT-SAUSAGE"]}, [("RT-SAUSAGE", "2")]))
    v2 = v1.new_version()
    v2.write({"rules": {"percent": 8, "product_ids": ["RT-SAUSAGE"]}})
    v2.simulate(retail, "retail", [(_product(env, "RT-SAUSAGE"), "2")])
    publish(_xmlid(env, module, "promo_sosis_v2", v2))


def price_drafts(env, module, spec, outlets):
    """Versi harga tahun depan sebagai draft: contoh layar susun & terbitkan harga untuk merchandising."""
    from odoo.addons.rasentra_demo.builder import MEAT, RETAIL

    region = spec["region"][0]
    version = env["rasentra.price.version"].create({
        "code": f"{region}-RETAIL-2027", "channel": "retail",
        "outlet_id": next(outlets[o["code"]] for o in spec["outlets"] if o.get("retail")).id,
        "effective_from": "2027-01-01 00:00:00",
        "item_ids": [(0, 0, {"product_id": _product(env, c).id, "unit_price": round(p * 1.06, -3)})
                     for c, _n, p in MEAT + RETAIL],
    })
    _xmlid(env, module, "price_draft_2027", version)


# ---- inventory -------------------------------------------------------------------------

def inventory(env, module, spec, outlets, employees):
    """Stok lengkap untuk peran gudang: pack dalam perjalanan, ditolak (karantina), dilepas lagi, hampir
    kedaluwarsa, stok barang retail, opname selesai dengan selisih, produksi dan potong porsi."""
    from odoo.addons.rasentra_demo.builder import MEAT, RETAIL

    o = next(o for o in spec["outlets"] if o.get("retail"))
    outlet = outlets[o["code"]]
    head = employees[(o["code"], "outlet_head")]
    clerk = employees[(o["code"], "warehouse")]
    rng = random.Random(spec["key"] + "-inv")
    Lot = env["stock.lot"]
    Inventory = env["rasentra.inventory"]
    ledger = env["rasentra.stock.ledger"]
    today = fields.Date.context_today(env["res.users"])
    region = spec["region"][0]

    def pack(seq, code, price, expiry_days, status="shipped", location="transit"):
        weight = round(rng.uniform(0.7, 2.2), 3)
        return Lot.create({
            "name": f"PK-{region}-{seq:06d}", "product_id": _product(env, code).id, "company_id": outlet.company_id.id,
            "is_rasentra_pack": True, "net_weight": weight, "label_price": round(weight * price, -2),
            "packed_at": fields.Datetime.now() - timedelta(days=1), "production_date": today - timedelta(days=1),
            "pack_expiry_date": today + timedelta(days=expiry_days), "rasentra_batch_no": f"B{today:%y%m%d}-{code[:3]}",
            "weigh_source": "timbangan pusat", "rasentra_outlet_id": outlet.id, "rasentra_location_type": location,
            "pack_status": status,
        })

    seq = 900
    # Kiriman hari ini dari pusat yang belum discan terima (layar "Terima barang").
    for code, _n, price in MEAT[:5]:
        for _i in range(2):
            seq += 1
            pack(seq, code, price, 12)
    # Ditolak saat terima: masuk karantina; satu dilepas lagi dengan PIN kepala outlet.
    rejected = []
    for code, reason in (("SALMON-NOR", "Vakum bocor"), ("RIBEYE-WAGYU", "Suhu kiriman 9°C"),
                         ("CHICKEN-FILLET", "Warna pucat, cek QC")):
        seq += 1
        lot = pack(seq, code, dict((c, p) for c, _n, p in MEAT)[code], 6)
        Inventory.receive(outlet, lot.name, clerk, "reject", reason)
        rejected.append(lot)
    Inventory.release(outlet, clerk, rejected[-1].name, None, "Cek ulang QC: warna normal",
                      {"approver_id": head.id, "pin": head.pin})
    # Hampir kedaluwarsa dan sudah kedaluwarsa (POS minta PIN kepala outlet).
    for code, days in (("SALMON-NOR", 1), ("CHICKEN-FILLET", 0), ("SIRLOIN-AUS", -1)):
        seq += 1
        lot = pack(seq, code, dict((c, p) for c, _n, p in MEAT)[code], days)
        Inventory.receive(outlet, lot.name, clerk)

    # Barang retail (SKU) di rak dan sedikit di karantina.
    stock = ledger.location(outlet, "stock")
    quarantine = ledger.location(outlet, "quarantine")
    source = ledger.virtual(outlet.company_id, "inventory")
    for code, _n, _p in RETAIL:
        ledger.move(_product(env, code), rng.choice([24, 36, 48, 60]), source, stock, f"Stok awal demo {outlet.code}")
    ledger.move(_product(env, "RT-BBQ"), 3, source, quarantine, "Botol penyok dari kiriman")
    Inventory.waste(outlet, head, "RT-SALT", 2, "Kemasan sobek")

    # Opname kemarin: selisih pada saus BBQ, dihitung ulang petugas lain, disetujui kepala outlet.
    counter = env["hr.employee"].with_company(outlet.company_id).create({
        "name": f"Petugas Opname {spec['region'][1]}", "company_id": outlet.company_id.id, "rasentra_role": "counter",
        "rasentra_outlet_id": outlet.id, "pin": str(1600 + len(spec["key"])),
        "job_title": f"Petugas opname {outlet.name}"})
    _xmlid(env, module, f"employee_{o['key']}_counter", counter)
    Count = env["rasentra.count.session"]
    session = Count.open(clerk, outlet)
    where = stock.barcode or stock.name
    balances = {code: float(ledger.balance(_product(env, code), stock)) for code, _n, _p in RETAIL}
    for code, balance in balances.items():
        counted = balance - 2 if code == "RT-PEPPER" else balance
        session.record_scan(clerk, code, counted, where)
    session.review(head)
    if session.state == "recount":
        for code, balance in balances.items():
            if code == "RT-PEPPER":
                session.record_scan(counter, code, balance - 1, where)
        session.review(head)
    session.approve(head)
    _xmlid(env, module, "count_session_done", session)

    # Produksi saus dan potong porsi dari primal.
    chef = employees.get((o["code"], "chef")) or head
    Batch = env["rasentra.production.batch"]
    kitchen = env["rasentra.kitchen"]._kitchen_location(outlet)
    for code in ("SR-BBQ", "SR-MUSHROOM"):
        version = env["rasentra.recipe"].search([("product_id.default_code", "=", code)], limit=1).version_ids.filtered(
            lambda v: v.state == "approved")[:1]
        Batch.produce_from_recipe(outlet, chef, version, "2.000", "1.970", loss_reason=None, notes="Produksi sore")
    primal = _product(env, "BH-STRIPLOIN-PRIMAL")
    ledger.move(primal, 25, source, kitchen, f"Stok awal demo {outlet.code}")
    Batch.produce(outlet, chef, [(primal, "6.000")],
                  [(_product(env, "BH-BEEF-PORTION"), "5.450"), (_product(env, "BH-TRIMMING"), "0.300", "trimming")],
                  "Susut potong", "Potong porsi steak untuk grill")


# ---- POS & dapur hari ini --------------------------------------------------------------

class Till:
    """Membuat order POS seperti dari layar kasir (sync_from_ui) di sesi yang sedang buka."""

    def __init__(self, env, config, employee):
        # Sesi dibuka atas nama Admin Pusat (manajer POS); superuser Odoo tidak boleh membuka sesi POS.
        env = env(user=env.ref("rasentra_demo.user_hq_admin").id, su=True)
        config = config.with_env(env)
        self.env, self.config, self.employee = env, config, employee
        config.open_ui()
        self.session = config.current_session_id
        if self.session.state == "opening_control":
            self.session.set_opening_control(500000, "Modal awal demo")
        self.cash = config.payment_method_ids.filtered(lambda m: m.rasentra_method == "cash")[:1]
        self.seq = 0

    def data(self, order_uuid, lines, paid=True, method=None, **extra):
        ui_lines = []
        for line in lines:
            if isinstance(line, dict):
                product_id, quantity, price = line["product_id"], float(line["quantity"]), float(line["unit_price"])
                lots, extra_vals = [(0, 0, {"lot_name": line["pack_code"]})], {}
            else:
                product, quantity, price = line[:3]
                product_id, lots = product.id, []
                extra_vals = line[3] if len(line) > 3 else {}
            ui_lines.append((0, 0, {
                "uuid": str(uuid.uuid4()), "product_id": product_id, "qty": quantity, "price_unit": price,
                "price_subtotal": quantity * price, "price_subtotal_incl": quantity * price, "discount": 0,
                "tax_ids": [(6, 0, [])], "pack_lot_ids": lots, **extra_vals,
            }))
        total = sum(line[2]["price_subtotal_incl"] for line in ui_lines)
        self.seq += 1
        data = {
            "uuid": order_uuid, "name": f"Order {order_uuid}", "session_id": self.session.id,
            "sequence_number": self.seq, "user_id": self.env.uid, "employee_id": self.employee.id,
            "pricelist_id": self.config.pricelist_id.id, "fiscal_position_id": False, "partner_id": False,
            "date_order": fields.Datetime.to_string(fields.Datetime.now()), "last_order_preparation_change": "{}",
            "amount_total": total, "amount_tax": 0, "amount_paid": total if paid else 0, "amount_return": 0,
            "to_invoice": False, "lines": ui_lines, "state": "paid" if paid else "draft",
            "payment_ids": [(0, 0, {"amount": total, "name": fields.Datetime.now(),
                                    "payment_method_id": (method or self.cash).id})] if paid else [],
        }
        data.update(extra)
        return data

    def sync(self, data):
        result = self.env["pos.order"].sync_from_ui([data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])


def live_pos(env, module, spec, outlets, employees):
    """Sesi POS terbuka hari ini: penjualan meatshop dengan Pack ID dan jasa masak, meja restoran yang sedang
    makan dengan tiket dapur di berbagai status, minta tagihan, QRIS menunggu bayar, kas keluar."""
    rng = random.Random(spec["key"] + "-live")
    o = next(o for o in spec["outlets"] if o.get("retail"))
    outlet = outlets[o["code"]]
    cashier, waiter = employees[(o["code"], "cashier")], employees[(o["code"], "waiter")]
    chef_user = env.ref(f"{module}.user_{o['key']}_chef")
    kitchen = env["rasentra.kitchen"].with_user(chef_user)

    configs = {c["key"]: env.ref(f"{module}.pos_{c['key']}") for c in spec["pos"]}
    retail_key = next(c["key"] for c in spec["pos"] if c["outlet"] == o["code"] and c["channel"] == "retail")
    grill_key = next(c["key"] for c in spec["pos"] if c["outlet"] == o["code"] and c["channel"] == "restaurant")

    # Meatshop: 4 struk lunas dengan Pack ID, satu pack dimasak di grill (jasa masak).
    till = Till(env, configs[retail_key], cashier)
    packs = env["stock.lot"].search([("rasentra_outlet_id", "=", outlet.id), ("pack_status", "=", "received"),
                                     ("pack_expiry_date", ">", fields.Date.context_today(env["res.users"]))],
                                    order="name desc")
    qris = till.config.payment_method_ids.filtered(lambda m: m.rasentra_method == "qris")[:1]
    session = till.session
    service = env.ref("rasentra_cooking_fee.product_cooking_service")
    for n in range(4):
        order_uuid = f"LIVE-{o['code']}-R{n + 1}"
        lines = [session.rasentra_scan(packs[n * 2 + k].name, order_uuid, cashier.id) for k in range(1 + n % 2)]
        lines = [line for line in lines if isinstance(line, dict) and line.get("kind") == "pack"]
        extra = []
        if n == 3 and o.get("cooking"):
            job = session.rasentra_cooking_request(order_uuid, lines[0]["pack_code"],
                                                   {"method": "grill", "doneness": "medium_rare"}, cashier.id)
            extra = [(service, 1, float(job["fee"]), {"rasentra_cooking_job_uuid": job["job_uuid"]})]
        till.sync(till.data(order_uuid, lines + extra, method=qris if n % 2 else None))
    session.try_cash_in_out("out", 35000, "Beli es batu untuk display", {
        "translatedType": "out", "formattedAmount": "Rp 35.000", "employee_id": cashier.id})

    # Grill: meja yang sudah selesai (dibayar) dan meja yang sedang makan.
    grill = Till(env, configs[grill_key], waiter)
    tables = env["restaurant.table"].search([("floor_id.pos_config_ids", "in", grill.config.ids)], order="table_number")
    menu = {code: _product(env, code) for code in ("MN-SIRLOIN", "MN-TENDER", "MN-CHICKEN", "MN-SALMON", "MN-MASHED",
                                                     "MN-FRIES", "MN-SALAD", "MN-TEA", "MN-LEMONTEA", "MN-KOPI")}

    def table_order(order_uuid, table, picks, guests):
        return grill.sync(grill.data(order_uuid, [(menu[c], q, menu[c].list_price) for c, q in picks], paid=False,
                                     table_id=table.id, customer_count=guests))

    def items(order_uuid):
        return env["rasentra.kitchen.item"].search([("ticket_id.order_uuid", "=", order_uuid)], order="id")

    done_orders = [("MN-SIRLOIN", 2), ("MN-FRIES", 1), ("MN-TEA", 2)], [("MN-CHICKEN", 1), ("MN-SALAD", 1),
                                                                        ("MN-KOPI", 1)]
    for n, picks in enumerate(done_orders):
        order_uuid = f"LIVE-{o['code']}-G{n + 1}"
        table_order(order_uuid, tables[-1 - n], picks, 2)
        grill.session.rasentra_kitchen_send(order_uuid)
        for item in items(order_uuid):
            kitchen.bump_item(item.id)
            kitchen.bump_item(item.id)
            kitchen.bump_item(item.id, expeditor=True)
        order = env["pos.order"].search([("uuid", "=", order_uuid)])
        paid = grill.data(order_uuid, [(l.product_id, l.qty, l.price_unit) for l in order.lines],
                          table_id=tables[-1 - n].id, customer_count=2)
        grill.sync(paid)

    # Sedang makan: tiap meja di tahap berbeda.
    scenes = [
        ("queued", [("MN-SIRLOIN", 2), ("MN-MASHED", 2), ("MN-LEMONTEA", 2)], 4),
        ("cooking", [("MN-TENDER", 1), ("MN-SALMON", 1), ("MN-SALAD", 1), ("MN-KOPI", 2)], 2),
        ("ready", [("MN-CHICKEN", 2), ("MN-FRIES", 2), ("MN-TEA", 2)], 3),
        ("billing", [("MN-SIRLOIN", 1), ("MN-TEA", 1)], 1),
        ("unsent", [("MN-TENDER", 2), ("MN-MASHED", 1)], 2),
    ]
    for n, (scene, picks, guests) in enumerate(scenes):
        if n >= len(tables) - len(done_orders):
            break
        order_uuid = f"LIVE-{o['code']}-T{n + 1}"
        table_order(order_uuid, tables[n], picks, guests)
        if scene == "unsent":
            continue
        grill.session.rasentra_kitchen_send(order_uuid)
        for item in items(order_uuid):
            if scene == "cooking" and item.ticket_id.station in ("grill", "hot"):
                kitchen.bump_item(item.id)
            elif scene == "ready":
                kitchen.bump_item(item.id)
                kitchen.bump_item(item.id)
            elif scene == "billing":
                kitchen.bump_item(item.id)
                kitchen.bump_item(item.id)
                kitchen.bump_item(item.id, expeditor=True)
        if scene == "billing":
            grill.session.rasentra_request_bill(order_uuid, waiter.id)
            gqris = grill.config.payment_method_ids.filtered(lambda m: m.rasentra_method == "qris")[:1]
            order = env["pos.order"].search([("uuid", "=", order_uuid)])
            if gqris:
                grill.session.rasentra_payment_start(order_uuid, gqris.id, order.amount_total)

    # Pesanan jasa masak dari meatshop ikut tampil di station grill.
    job_orders = env["pos.order"].search([("uuid", "=like", f"LIVE-{o['code']}-R%")])
    for order in job_orders.filtered(lambda r: r.lines.filtered("rasentra_cooking_job_uuid")):
        till.session.rasentra_kitchen_send(order.uuid)

    # Restoran kedua di CV yang sama: beberapa tiket aktif supaya expeditor punya isi.
    other = next((c for c in spec["pos"] if c["outlet"] != o["code"] and c["channel"] == "restaurant"), None)
    if other:
        oc = other["outlet"]
        resto = Till(env, configs[other["key"]], employees[(oc, "waiter")])
        rtables = env["restaurant.table"].search([("floor_id.pos_config_ids", "in", resto.config.ids)],
                                                 order="table_number")
        for n in range(min(4, len(rtables))):
            order_uuid = f"LIVE-{oc}-T{n + 1}"
            picks = rng.sample(sorted(menu), 3)
            resto.sync(resto.data(order_uuid, [(menu[c], rng.randint(1, 2), menu[c].list_price) for c in picks],
                                  paid=False, table_id=rtables[n].id, customer_count=rng.randint(2, 6)))
            resto.session.rasentra_kitchen_send(order_uuid)
            for item in items(order_uuid)[: n]:
                kitchen.bump_item(item.id)


# ---- migrasi ----------------------------------------------------------------------------

def migration(env, module, spec, outlets):
    """Gelombang migrasi CV ini (Raptor + SAP B1): langkah yang sudah lewat ditandai selesai."""
    today = fields.Date.context_today(env["res.users"])
    company = next(iter(outlets.values())).company_id
    days = spec.get("cutover_in_days", 21)
    wave = env["rasentra.migration.wave"].create({
        "name": f"Gelombang {spec['region'][1]}", "legacy": "raptor_sap", "company_id": company.id,
        "cutover_date": today + timedelta(days=days), "outlet_ids": [(6, 0, [o.id for o in outlets.values()])],
        "note": "Contoh demo: kode produk sudah dipetakan, ekspor saldo SAP B1 dan Raptor sedang dibersihkan.",
    })
    _xmlid(env, module, "migration_wave", wave)
    admin = env.ref("rasentra_demo.user_hq_admin")
    wave.step_ids.filtered(lambda s: s.due_date and s.due_date < today).with_user(admin).action_done()
