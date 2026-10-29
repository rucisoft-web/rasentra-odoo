"""Pembangun data demo Rasentra. Dipakai rasentra_demo (dasar grup) serta rasentra_demo_solo dan
rasentra_demo_lombok (data per CV). Semua catatan penting diberi xmlid di modul pemanggil, sehingga
uninstall membersihkannya dan panduan/screenshot bisa merujuknya.

Kata sandi semua pengguna demo: DEMO_PASSWORD. Jangan dipakai di produksi.
"""

import logging
import random
from datetime import datetime, timedelta

from odoo import fields

from odoo.addons.rasentra_core.tools import checksum, uuid7

_logger = logging.getLogger(__name__)

DEMO_PASSWORD = "rasentra"

# ---- katalog grup ----------------------------------------------------------------------

MEAT = [
    # kode, nama, harga retail per kg
    ("SIRLOIN-AUS", "Sirloin Australia", 200000),
    ("TENDER-AUS", "Tenderloin Australia", 260000),
    ("RIBEYE-WAGYU", "Ribeye Wagyu MB5", 650000),
    ("SHORTRIB-US", "Short rib US", 310000),
    ("CHICKEN-FILLET", "Dada ayam fillet", 68000),
    ("SALMON-NOR", "Salmon Norwegia fillet", 420000),
]
RETAIL = [
    ("RT-SALT", "Garam laut 250 g", 28000),
    ("RT-PEPPER", "Lada hitam 100 g", 35000),
    ("RT-BBQ", "Saus BBQ botol 300 ml", 45000),
]
INGREDIENTS = [
    # kode, nama, satuan
    ("BH-BEEF-PORTION", "Daging sirloin porsi", "kg"),
    ("BH-TENDER-PORTION", "Daging tenderloin porsi", "kg"),
    ("BH-CHICKEN-PORTION", "Ayam fillet porsi", "kg"),
    ("BH-SALMON-PORTION", "Salmon porsi", "kg"),
    ("BH-BUTTER", "Butter", "kg"),
    ("BH-GARLIC", "Bawang putih", "kg"),
    ("BH-POTATO", "Kentang", "kg"),
    ("BH-TOMATO", "Tomat", "kg"),
    ("BH-MUSHROOM", "Jamur champignon", "kg"),
    ("BH-PEPPER", "Lada hitam butir", "kg"),
    ("BH-MILK", "Susu segar", "litre"),
    ("BH-SUGAR", "Gula pasir", "kg"),
    ("BH-TEA", "Teh hitam", "kg"),
    ("BH-COFFEE", "Kopi bubuk", "kg"),
    ("BH-LETTUCE", "Selada", "kg"),
]
SAUCES = [
    ("SR-BBQ", "Saus BBQ rumahan", [("BH-TOMATO", 0.8), ("BH-GARLIC", 0.05), ("BH-SUGAR", 0.1), ("BH-BUTTER", 0.05)]),
    ("SR-BLACKPEPPER", "Saus lada hitam", [("BH-PEPPER", 0.08), ("BH-BUTTER", 0.1), ("BH-GARLIC", 0.05), ("BH-MILK", 0.5)]),
    ("SR-MUSHROOM", "Saus jamur", [("BH-MUSHROOM", 0.4), ("BH-BUTTER", 0.08), ("BH-MILK", 0.6)]),
]
STEAK_MODS = [("BH-BUTTER", 0.015, "extra_butter"), ("SR-BBQ", 0.05, "sauce_bbq"),
              ("SR-BLACKPEPPER", 0.05, "sauce_blackpepper"), ("SR-MUSHROOM", 0.05, "sauce_mushroom")]
MENU = [
    # kode, nama, station, harga, kategori, resep [(kode, qty, modifier)], steak?
    ("MN-SIRLOIN", "Sirloin steak 200 g", "grill", 185000, "steak",
     [("BH-BEEF-PORTION", 0.2, None), ("BH-BUTTER", 0.01, None), ("BH-GARLIC", 0.005, None)] + STEAK_MODS, True),
    ("MN-TENDER", "Tenderloin steak 180 g", "grill", 225000, "steak",
     [("BH-TENDER-PORTION", 0.18, None), ("BH-BUTTER", 0.01, None), ("BH-GARLIC", 0.005, None)] + STEAK_MODS, True),
    ("MN-CHICKEN", "Chicken steak", "grill", 85000, "steak",
     [("BH-CHICKEN-PORTION", 0.2, None), ("BH-BUTTER", 0.01, None)] + STEAK_MODS, True),
    ("MN-SALMON", "Salmon panggang", "grill", 145000, "steak",
     [("BH-SALMON-PORTION", 0.18, None), ("BH-BUTTER", 0.015, None), ("BH-GARLIC", 0.005, None)], False),
    ("MN-MASHED", "Mashed potato", "hot", 30000, "side",
     [("BH-POTATO", 0.2, None), ("BH-BUTTER", 0.02, None), ("BH-MILK", 0.05, None)], False),
    ("MN-FRIES", "Kentang goreng", "hot", 25000, "side", [("BH-POTATO", 0.25, None)], False),
    ("MN-SALAD", "Garden salad", "cold", 35000, "side", [("BH-LETTUCE", 0.1, None), ("BH-TOMATO", 0.05, None)], False),
    ("MN-TEA", "Es teh", "bar", 15000, "drink", [("BH-TEA", 0.01, None), ("BH-SUGAR", 0.02, None)], False),
    ("MN-LEMONTEA", "Lemon tea", "bar", 22000, "drink", [("BH-TEA", 0.01, None), ("BH-SUGAR", 0.02, None)], False),
    ("MN-KOPI", "Kopi susu", "bar", 28000, "drink", [("BH-COFFEE", 0.018, None), ("BH-MILK", 0.12, None)], False),
]
CATEGORIES = {"steak": "Steak & grill", "side": "Pendamping", "drink": "Minuman", "meat": "Daging ber-Pack ID",
              "retail": "Bumbu & saus"}
QUICK_NOTES = ["Tanpa garam", "Saus dipisah", "Tidak pedas", "Alergi kacang", "Untuk dibawa pulang", "Potong 4"]


def xmlid(env, module, name, record):
    """Daftarkan xmlid noupdate untuk catatan demo (dipakai panduan dan dibersihkan saat uninstall)."""
    env["ir.model.data"].sudo()._update_xmlids([{"xml_id": f"{module}.{name}", "record": record, "noupdate": True}])
    return record


def ref(env, module, name):
    return env.ref(f"{module}.{name}", raise_if_not_found=False)


def _uom(env, key):
    return {"kg": env.ref("uom.product_uom_kgm"), "litre": env.ref("uom.product_uom_litre"),
            "unit": env.ref("uom.product_uom_unit")}[key]


def _product(env, code):
    return env["product.product"].search([("default_code", "=", code)], limit=1)


def _user(env, module, key, name, login, groups, companies, company):
    user = env["res.users"].with_context(no_reset_password=True).create({
        "name": name, "login": login, "password": DEMO_PASSWORD, "email": f"{login}@demo.rasentra.id",
        "company_id": company.id, "company_ids": [(6, 0, companies.ids)],
        "groups_id": [(6, 0, [env.ref(g).id for g in groups + ["base.group_user"]])],
        "tz": "Asia/Jakarta",
        "lang": "id_ID" if env["res.lang"]._lang_get("id_ID") else "en_US",
    })
    return xmlid(env, module, f"user_{key}", user)


# ---- dasar grup ------------------------------------------------------------------------

def build_base(env):
    module = "rasentra_demo"
    params = env["ir.config_parameter"].sudo()
    # Demo laptop = satu database berperan Central (laporan HQ, publikasi master, SAP simulasi).
    params.set_param("rasentra.profile", "central")
    # Antarmuka Bahasa Indonesia untuk semua pengguna demo (terjemahan Odoo standar ikut dimuat).
    try:
        lang = env["res.lang"]._activate_lang("id_ID")
        env["base.language.install"].create({"lang_ids": [(6, 0, lang.ids)], "overwrite": False}).lang_install()
        env.ref("base.user_admin").lang = "id_ID"
    except Exception as error:  # noqa: BLE001 - bahasa opsional, demo tetap jalan
        _logger.info("Bahasa Indonesia tidak bisa dipasang: %s", error)

    holding = env.ref("base.main_company")
    # Grup memakai Rupiah agar harga produk bersama tampil Rp, bukan $ bawaan base.main_company.
    idr = env.ref("base.IDR")
    idr.active = True
    holding.write({"name": "Indoguna Group", "rasentra_legal_name": "Indoguna Group (pusat)",
                   "country_id": env.ref("base.id").id, "city": "Jakarta", "currency_id": idr.id})
    # Saat modul account terpasang di database kosong, Odoo menjadwalkan bagan generik (USD) untuk perusahaan
    # induk di akhir instalasi (registry._auto_install_template). Muat bagan Indonesia sekarang dan batalkan
    # jadwal itu agar induk tetap Rupiah.
    if not holding.chart_template:
        env["account.chart.template"].try_loading("id", holding, install_demo=False)
    if hasattr(env.registry, "_auto_install_template"):
        env.registry._auto_install_template = lambda env: None
    holding.currency_id = idr
    companies = env["res.company"].search([])

    for key, name, login, groups in (
        ("hq_admin", "Admin Pusat", "admin.pusat",
         ["rasentra_core.group_rasentra_admin", "base.group_erp_manager", "point_of_sale.group_pos_manager",
          "stock.group_stock_manager", "hr.group_hr_user"]),
        ("hq_merch", "Tim Merchandising", "merch", ["rasentra_core.group_rasentra_merch"]),
        ("hq_finance", "Tim Finance", "finance", ["rasentra_core.group_rasentra_finance"]),
    ):
        _user(env, module, key, name, login, groups, companies, holding)

    # Kategori POS dan produk.
    Categ = env["pos.category"]
    for key, label in CATEGORIES.items():
        xmlid(env, module, f"pos_categ_{key}", Categ.create({"name": label, "color": 0}))
    kg, unit = _uom(env, "kg"), _uom(env, "unit")
    Product = env["product.product"].with_context(tracking_disable=True)

    def product(code, name, **vals):
        record = Product.create({"name": name, "default_code": code, "type": "consu", "taxes_id": [(5, 0, 0)],
                                 "supplier_taxes_id": [(5, 0, 0)], **vals})
        return xmlid(env, module, "product_" + code.lower().replace("-", "_"), record)

    for code, name, price in MEAT:
        product(code, name, is_storable=True, tracking="lot", uom_id=kg.id, uom_po_id=kg.id, list_price=price,
                rasentra_type="meat_pack", available_in_pos=True, to_weight=True,
                pos_categ_ids=[(6, 0, [ref(env, module, "pos_categ_meat").id])])
    for code, name, price in RETAIL:
        product(code, name, is_storable=True, list_price=price, rasentra_type="retail", available_in_pos=True,
                barcode=f"899{abs(hash(code)) % 10**10:010d}",
                pos_categ_ids=[(6, 0, [ref(env, module, "pos_categ_retail").id])])
    for code, name, uom in INGREDIENTS:
        product(code, name, is_storable=True, uom_id=_uom(env, uom).id, uom_po_id=_uom(env, uom).id,
                rasentra_type="ingredient")
    for code, name, _lines in SAUCES:
        product(code, name, is_storable=True, uom_id=_uom(env, "litre").id, uom_po_id=_uom(env, "litre").id,
                rasentra_type="ingredient")
    for code, name, station, price, categ, _lines, _steak in MENU:
        product(code, name, list_price=price, rasentra_type="menu", kitchen_station=station, available_in_pos=True,
                pos_categ_ids=[(6, 0, [ref(env, module, f"pos_categ_{categ}").id])])

    service = env.ref("rasentra_cooking_fee.product_cooking_service")
    service.write({"available_in_pos": True, "taxes_id": [(5, 0, 0)],
                   "pos_categ_ids": [(6, 0, [ref(env, module, "pos_categ_steak").id])]})

    _modifiers(env, module)
    _recipes(env, module)

    if "pos.note" in env:
        for note in QUICK_NOTES:
            env["pos.note"].create({"name": note})

    # Harga grup: retail per kg untuk daging & barang retail, restoran untuk menu.
    _price(env, module, "price_group_retail", "GRP-RETAIL-2026", None, "retail",
           [(code, price) for code, _n, price in MEAT + RETAIL])
    _price(env, module, "price_group_resto", "GRP-RESTO-2026", None, "restaurant",
           [(m[0], m[3]) for m in MENU] + [("SVC-COOK", 0)])

    # Satu promo draft menunggu persetujuan (contoh layar maker-checker).
    merch = ref(env, module, "user_hq_merch")
    promotion = env["rasentra.promotion"].create({"code": "WAGYU-NOV", "name": "Wagyu November 15%"})
    draft = env["rasentra.promotion.version"].with_user(merch).create({
        "promotion_id": promotion.id, "type": "percent",
        "rules": {"percent": 15, "product_ids": ["RIBEYE-WAGYU"]}, "starts_at": "2026-11-01 00:00:00"})
    xmlid(env, module, "promo_wagyu_draft", draft)


def _price(env, module, name, code, outlet, channel, items):
    version = env["rasentra.price.version"].create({
        "code": code, "outlet_id": outlet.id if outlet else False, "channel": channel,
        "effective_from": "2026-01-01 00:00:00",
        "item_ids": [(0, 0, {"product_id": _product(env, c).id, "unit_price": p}) for c, p in items],
    })
    version.action_publish()
    return xmlid(env, module, name, version)


def _modifiers(env, module):
    Attribute = env["product.attribute"]
    spec = [
        ("doneness", "Kematangan", "radio", [("Rare", "doneness_rare", 0), ("Medium rare", "doneness_medium_rare", 0),
                                              ("Medium", "doneness_medium", 0), ("Medium well", "doneness_medium_well", 0),
                                              ("Well done", "doneness_well_done", 0)]),
        ("sauce", "Saus", "radio", [("Saus BBQ", "sauce_bbq", 0), ("Saus lada hitam", "sauce_blackpepper", 0),
                                    ("Saus jamur", "sauce_mushroom", 0)]),
        ("extra", "Tambahan", "multi", [("Extra butter", "extra_butter", 10000),
                                        ("Tanpa bawang putih", "without:BH-GARLIC", 0)]),
    ]
    attributes = []
    for key, name, display, values in spec:
        attribute = Attribute.create({
            "name": name, "create_variant": "no_variant", "display_type": display,
            "value_ids": [(0, 0, {"name": v, "rasentra_modifier_key": k, "default_extra_price": p})
                          for v, k, p in values],
        })
        attributes.append(xmlid(env, module, f"attribute_{key}", attribute))
    for code, *_rest, steak in MENU:
        if steak:
            template = _product(env, code).product_tmpl_id
            template.write({"attribute_line_ids": [(0, 0, {"attribute_id": a.id, "value_ids": [(6, 0, a.value_ids.ids)]})
                                                   for a in attributes]})


def _recipes(env, module):
    chef = env.ref("base.user_admin")
    approver = ref(env, module, "user_hq_merch")

    def recipe(code, kind, lines, yield_qty=1.0):
        record = env["rasentra.recipe"].with_user(chef).create({"product_id": _product(env, code).id})
        version = env["rasentra.recipe.version"].with_user(chef).create({
            "recipe_id": record.id, "kind": kind, "yield_quantity": yield_qty,
            "line_ids": [(0, 0, {"component_product_id": _product(env, c).id, "quantity": q, "modifier_key": m or False})
                         for c, q, m in lines],
        })
        version.approve(approver)
        xmlid(env, module, "recipe_" + code.lower().replace("-", "_"), record)
        return version

    for code, _name, lines in SAUCES:
        recipe(code, "stocked_prep", [(c, q, None) for c, q in lines])
    for code, _n, _s, _p, _c, lines, _steak in MENU:
        recipe(code, "menu", lines)
    version = recipe("SVC-COOK", "virtual_prep", [("BH-BUTTER", 0.01, None), ("BH-GARLIC", 0.005, None)])
    xmlid(env, module, "recipe_version_cooking_service", version)


# ---- per CV ------------------------------------------------------------------------------

def build_company(env, module, spec):
    """`spec`: kunci, nama CV, database SAP, wilayah, zona waktu, outlet dan pengguna. Lihat SOLO/LOMBOK."""
    base = "rasentra_demo"
    holding = env.ref("base.main_company")
    company = env["res.company"].create({
        "name": spec["company"], "rasentra_legal_name": spec["company"], "sap_company_db": spec["sap_db"],
        "country_id": env.ref("base.id").id, "city": spec["city"],
        "currency_id": env.ref("base.IDR").id,
    })
    xmlid(env, module, "company", company)
    env["account.chart.template"].try_loading("id", company, install_demo=False)
    company.logo = holding.logo
    for user in env["res.users"].search([("id", "in", [ref(env, base, k).id for k in ("user_hq_admin", "user_hq_merch",
                                                                                         "user_hq_finance")])]):
        user.company_ids = [(4, company.id)]
    env.ref("base.user_admin").company_ids = [(4, company.id)]

    cenv = env(context=dict(env.context, allowed_company_ids=[company.id]))
    warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    if not warehouse:
        warehouse = cenv["stock.warehouse"].create({"name": f"Gudang {spec['region'][1]}", "code": spec["region"][0],
                                                    "company_id": company.id})
    xmlid(env, module, "warehouse", warehouse)
    region = xmlid(env, module, "region", cenv["rasentra.region"].create(
        {"code": spec["region"][0], "name": spec["region"][1], "company_id": company.id}))
    outlets = {}
    for o in spec["outlets"]:
        outlet = cenv["rasentra.outlet"].create({
            "code": o["code"], "name": o["name"], "company_id": company.id, "region_id": region.id, "tz": spec["tz"],
            "retail_name": o.get("retail_name"), "restaurant_name": o.get("restaurant_name"),
            "has_retail": o.get("retail", False), "has_restaurant": o.get("restaurant", False),
            "has_cooking_fee": o.get("cooking", False), "sap_warehouse_code": f"WH-{o['code']}",
            "warehouse_id": warehouse.id,
        })
        outlets[o["code"]] = xmlid(env, module, "outlet_" + o["key"], outlet)
        xmlid(env, module, "device_" + o["key"], cenv["rasentra.device"].create(
            {"code": f"{o['code']}-SRV", "name": f"Server Lokal {o['name']}", "outlet_id": outlet.id, "app": "lokal"}))
        # Rasentra Lokal outlet ini memakai jalur posting SAP Service Layer (bukan XML).

    employees = _employees(env, cenv, module, spec, company, outlets)
    payments = _payment_methods(env, cenv, module, company)
    _pos_configs(env, cenv, module, spec, company, outlets, employees, payments)
    _sap_mappings(env, spec["sap_db"], outlets, spec.get("unmapped", ()))
    if spec.get("price_markup"):
        for o in spec["outlets"]:
            if o.get("retail"):
                _price(env, module, f"price_{o['key']}", f"{o['code']}-RETAIL-2026", outlets[o["code"]], "retail",
                       [(c, round(p * (1 + spec["price_markup"]), -3)) for c, _n, p in MEAT])
    _cooking_rule(env, module, spec, outlets)
    _promotions(env, module, spec, outlets)
    _packs(env, cenv, module, spec, outlets, employees)
    _history(env, module, spec, outlets)
    _activity(env, module, spec, outlets)
    return company


def _employees(env, cenv, module, spec, company, outlets):
    roles = {
        "outlet_head": ("Kepala outlet", ["rasentra_core.group_rasentra_outlet_head", "point_of_sale.group_pos_manager",
                                          "stock.group_stock_user"], 1500000),
        "cashier": ("Kasir", ["point_of_sale.group_pos_user"], 0),
        "waiter": ("Pelayan", ["point_of_sale.group_pos_user"], 0),
        "chef": ("Chef", ["rasentra_core.group_rasentra_kitchen", "point_of_sale.group_pos_user"], 0),
        "warehouse": ("Gudang", ["rasentra_core.group_rasentra_inventory", "stock.group_stock_user"], 0),
    }
    employees = {}
    pin = 1000
    for o in spec["outlets"]:
        outlet = outlets[o["code"]]
        for role, person in o["people"].items():
            label, groups, limit = roles[role]
            pin += 111
            user = False
            if o.get("users"):
                login = f"{spec['key']}.{role.replace('outlet_head', 'kepala').replace('cashier', 'kasir').replace('waiter', 'pelayan').replace('chef', 'dapur').replace('warehouse', 'gudang')}"
                user = _user(env, module, f"{o['key']}_{role}", person, login, groups, company, company)
                user.tz = spec["tz"]
            employee = cenv["hr.employee"].create({
                "name": person, "company_id": company.id, "rasentra_role": role, "rasentra_outlet_id": outlet.id,
                "pin": str(pin), "approval_limit": limit, "user_id": user.id if user else False,
                "job_title": f"{label} {outlet.name}",
            })
            employees[(o["code"], role)] = xmlid(env, module, f"employee_{o['key']}_{role}", employee)
    return employees


def _payment_methods(env, cenv, module, company):
    Journal = cenv["account.journal"]
    cash = Journal.search([("company_id", "=", company.id), ("type", "=", "cash")], limit=1)
    bank = Journal.search([("company_id", "=", company.id), ("type", "=", "bank")], limit=1)
    Method = cenv["pos.payment.method"]
    methods = {
        "qris": Method.create({"name": "QRIS", "journal_id": bank.id, "company_id": company.id,
                               "rasentra_method": "qris"}),
        "edc_manual": Method.create({"name": "EDC (manual)", "journal_id": bank.id, "company_id": company.id,
                                     "rasentra_method": "edc_manual"}),
    }
    for key, method in methods.items():
        xmlid(env, module, f"payment_{key}", method)
    # Metode tunai tidak boleh dipakai bersama antar-POS: dibuat per POS di _pos_configs.
    methods["_cash_journal"] = cash
    return methods


def _pos_configs(env, cenv, module, spec, company, outlets, employees, payments):
    base = "rasentra_demo"
    categ = {k: ref(env, base, f"pos_categ_{k}").id for k in CATEGORIES}
    for index, c in enumerate(spec["pos"], 1):
        outlet = outlets[c["outlet"]]
        staff = [e for (code, _role), e in employees.items() if code == c["outlet"]]
        heads = [e for (code, role), e in employees.items() if code == c["outlet"] and role == "outlet_head"]
        resto = c["channel"] == "restaurant"
        journal = payments["_cash_journal"] if index == 1 else cenv["account.journal"].create({
            "name": f"Kas {c['name']}", "type": "cash", "code": f"KS{index}", "company_id": company.id})
        cash = cenv["pos.payment.method"].create({"name": "Tunai", "journal_id": journal.id,
                                                  "company_id": company.id, "rasentra_method": "cash"})
        xmlid(env, module, f"payment_cash_{c['key']}", cash)
        vals = {
            "name": c["name"], "company_id": company.id, "rasentra_outlet_id": outlet.id,
            "warehouse_id": outlet.warehouse_id.id, "picking_type_id": outlet.warehouse_id.pos_type_id.id,
            "rasentra_channel": c["channel"], "module_pos_hr": True, "module_pos_restaurant": resto,
            "payment_method_ids": [(6, 0, [cash.id] + [p.id for k, p in payments.items() if not k.startswith("_")])],
            "limit_categories": True,
            "iface_available_categ_ids": [(6, 0, [categ[k] for k in (("steak", "side", "drink", "meat") if resto
                                                                      else ("meat", "retail"))])],
            "basic_employee_ids": [(6, 0, [e.id for e in staff if e not in heads])],
            "advanced_employee_ids": [(6, 0, [e.id for e in heads])],
        }
        if resto:
            vals["iface_splitbill"] = True
        config = cenv["pos.config"].create(vals)
        xmlid(env, module, f"pos_{c['key']}", config)
        if resto:
            for f_index, (floor_name, tables) in enumerate(c["floors"]):
                floor = cenv["restaurant.floor"].create({"name": floor_name, "pos_config_ids": [(4, config.id)],
                                                          "sequence": f_index})
                xmlid(env, module, f"floor_{c['key']}_{f_index}", floor)
                for t in range(tables):
                    table = cenv["restaurant.table"].create({
                        "floor_id": floor.id, "table_number": f_index * 10 + t + 1, "seats": 4 if t % 3 else 2,
                        "shape": "round" if t % 2 else "square",
                        "position_h": 60 + (t % 4) * 170, "position_v": 60 + (t // 4) * 170,
                        "width": 110, "height": 110,
                    })
                    xmlid(env, module, f"table_{c['key']}_{f_index}_{t + 1}", table)


def _sap_mappings(env, sap_db, outlets, skip=()):
    Mapping = env["rasentra.sap.mapping"]
    rows = [("customer", "walk_in", "C-UMUM"), ("payment_method", "cash", "110101"),
            ("payment_method", "qris", "110202"), ("payment_method", "edc_manual", "110203"),
            ("account", "waste", "610501"), ("account", "count", "610502"), ("account", "production", "510301")]
    rows += [("outlet", code, f"WH-{code}") for code in outlets]
    rows += [("product", c, f"FG-{c}") for c, _n, _p in MEAT + RETAIL]
    rows += [("product", m[0], f"MN-{m[0][3:]}") for m in MENU]
    rows += [("product", "SVC-COOK", "SV-COOKING")]
    # `skip`: mapping yang sengaja dikosongkan agar demo punya contoh pengecualian integrasi untuk Finance.
    Mapping.create([{"company_db": sap_db, "entity_type": t, "entity_key": k, "sap_code": s}
                    for t, k, s in rows if k not in skip])


def _cooking_rule(env, module, spec, outlets):
    for o in spec["outlets"]:
        if not o.get("cooking"):
            continue
        rule = env["rasentra.cooking.fee.rule"].create({
            "code": f"COOK-{o['code']}", "name": f"Jasa masak {o['name']}", "outlet_id": outlets[o["code"]].id,
            "basis": "per_kg", "rate": 40000, "minimum_fee": 25000,
            "tiers": [{"up_to": "1.000", "rate": "45000"}, {"up_to": "3.000", "rate": "40000"}],
            "recipe_version_id": env.ref("rasentra_demo.recipe_version_cooking_service").id,
            "effective_from": "2026-01-01 00:00:00",
        })
        rule.action_publish()
        xmlid(env, module, f"cooking_rule_{o['key']}", rule)


def _promotions(env, module, spec, outlets):
    merch = env.ref("rasentra_demo.user_hq_merch")
    admin = env.ref("rasentra_demo.user_hq_admin")
    retail_outlet = next(outlets[o["code"]] for o in spec["outlets"] if o.get("retail"))
    for key, code, name, rules in spec["promos"]:
        promotion = env["rasentra.promotion"].create({"code": code, "name": name})
        version = env["rasentra.promotion.version"].with_user(merch).create({
            "promotion_id": promotion.id, "type": "percent", "rules": rules,
            "starts_at": "2026-01-01 00:00:00"})
        version.simulate(retail_outlet, "retail", [(_product(env, rules["product_ids"][0]), "1.5")])
        version.with_user(admin).publish({"regions": [spec["region"][0]]})
        xmlid(env, module, f"promo_{key}", version)


def _packs(env, cenv, module, spec, outlets, employees):
    rng = random.Random(spec["key"])
    Lot = env["stock.lot"]
    Inventory = env["rasentra.inventory"]
    seq = 0
    today = fields.Date.context_today(env["res.users"])
    for o in spec["outlets"]:
        if not o.get("retail"):
            continue
        outlet = outlets[o["code"]]
        clerk = employees.get((o["code"], "warehouse")) or employees[(o["code"], "outlet_head")]
        for code, _name, price in MEAT:
            product = _product(env, code)
            for _i in range(6):
                seq += 1
                weight = round(rng.uniform(0.6, 2.4), 3)
                pack = Lot.create({
                    "name": f"PK-{spec['region'][0]}-{seq:06d}", "product_id": product.id, "company_id": outlet.company_id.id,
                    "is_rasentra_pack": True, "net_weight": weight, "label_price": round(weight * price, -2),
                    "packed_at": fields.Datetime.now() - timedelta(days=2), "production_date": today - timedelta(days=2),
                    "pack_expiry_date": today + timedelta(days=12 if code != "SALMON-NOR" else 4),
                    "rasentra_batch_no": f"B{today:%y%m%d}-{code[:3]}", "weigh_source": "timbangan pusat",
                    "rasentra_outlet_id": outlet.id, "rasentra_location_type": "transit", "pack_status": "shipped",
                })
                try:
                    Inventory.receive(outlet, pack.name, clerk)
                except Exception as error:  # noqa: BLE001 - demo tetap jalan, pack tercatat dikirim
                    _logger.warning("Pack demo %s tidak bisa diterima: %s", pack.name, error)
        # Stok bahan dapur awal untuk restoran (konsumsi resep).
        _ingredients_stock(env, outlet)
    for o in spec["outlets"]:
        if o.get("restaurant") and not o.get("retail"):
            _ingredients_stock(env, outlets[o["code"]])


def _ingredients_stock(env, outlet):
    ledger = env["rasentra.stock.ledger"]
    kitchen = env["rasentra.kitchen"]._kitchen_location(outlet)
    inventory = ledger.virtual(outlet.company_id, "inventory")
    for code, _name, _uom in INGREDIENTS:
        ledger.move(_product(env, code), 20, inventory, kitchen, f"Stok awal demo {outlet.code}")
    for code, _name, _lines in SAUCES:
        ledger.move(_product(env, code), 5, inventory, kitchen, f"Stok awal demo {outlet.code}")


def _history(env, module, spec, outlets):
    """Riwayat penjualan 7 hari dikirim lewat inbox sinkron seperti dari Rasentra Lokal, lalu diposting ke SAP
    (mode simulasi) agar dashboard, laporan, rekonsiliasi dan antrean SAP berisi."""
    rng = random.Random(spec["key"] + "-history")
    Inbox = env["rasentra.sync.inbox"].sudo()
    today = fields.Date.context_today(env["res.users"])
    counters = {}
    for back in range(6, -1, -1):
        day = today - timedelta(days=back)
        if back == 0:
            # Hari-hari lalu sudah terposting; struk hari ini masih menunggu antrean SAP (seperti pagi hari).
            try:
                env["rasentra.sap.document"].post_pending(limit=2000)
            except Exception as error:  # noqa: BLE001
                _logger.warning("Posting SAP demo gagal: %s", error)
        for o in spec["outlets"]:
            outlet = outlets[o["code"]]
            device = env.ref(f"{module}.device_{o['key']}")
            for _n in range(rng.randint(6, 12)):
                counters[o["code"]] = counter = counters.get(o["code"], 0) + 1
                channel = "retail" if o.get("retail") and (not o.get("restaurant") or rng.random() < 0.6) else "restaurant"
                payload = _sale_payload(env, rng, outlet, day, counter, channel)
                event = {
                    "event_id": uuid7(), "source_id": device.code, "outlet_id": outlet.code, "entity_type": "order",
                    "entity_id": payload["id"], "entity_version": 1, "event_type": "order.finalized",
                    "business_date": payload["business_date"], "payload": payload, "checksum": checksum(payload),
                }
                Inbox._receive_one(device, event)
            env["rasentra.outlet.sync.state"].sudo().heartbeat(device, {
                "app_version": "18.0.1.0.0", "outbox": {"pending": 0, "failed": 0, "parked": 0},
                "open_business_date": fields.Date.to_string(today), "open_shifts": 1})


def _activity(env, module, spec, outlets):
    """Aktivitas operasional hari ini agar setiap layar peran punya contoh: waste, hold, opname berjalan,
    produksi saus dan (Solo) impor NMEXML."""
    meat_outlet = next(o for o in spec["outlets"] if o.get("retail"))
    outlet = outlets[meat_outlet["code"]]
    emp = lambda role: env.ref(f"{module}.employee_{meat_outlet['key']}_{role}")
    head, clerk, chef = emp("outlet_head"), emp("warehouse"), emp("chef")
    Inventory = env["rasentra.inventory"]
    packs = env["stock.lot"].search([("rasentra_outlet_id", "=", outlet.id),
                                     ("pack_status", "in", ("received", "available"))],
                                    order="name")
    Inventory.waste(outlet, head, packs[-1].name, None, "Kemasan bocor saat display")
    Inventory.hold(outlet, clerk, packs[-2].name, "Cek QC warna daging")
    session = env["rasentra.count.session"].open(clerk, outlet)
    location = env["rasentra.stock.ledger"].location(outlet, "stock")
    for pack in packs[:8]:
        session.record_scan(clerk, pack.name, None, location.barcode or location.name)
    sauce = env["rasentra.recipe"].search([("product_id.default_code", "=", "SR-BLACKPEPPER")], limit=1)
    version = sauce.version_ids.filtered(lambda v: v.state == "approved")[:1]
    env["rasentra.production.batch"].produce_from_recipe(outlet, chef, version, "2.000", "1.985",
                                                         loss_reason=None, notes="Produksi pagi")
    if spec.get("xml_sample"):
        # Contoh jalur NMEXML (cabang lama): satu hari invoice & pembayaran, termasuk selisih pembulatan Rp0,40.
        from odoo.addons.rasentra_sap_xml.sample import build as build_sample

        msi, msr = build_sample()
        finance = env.ref("rasentra_demo.user_hq_finance")
        Batch = env["rasentra.xml.batch"].with_user(finance).with_company(outlet.company_id)
        Batch.import_xml(msi, "SLO_MSI_20261028.xml", "MSI")
        Batch.import_xml(msr, "SLO_MSR_20261028.xml", "MSR")
        Batch.import_xml(msi, "SLO_MSI_20261028_ulang.xml", "MSI")


def _sale_payload(env, rng, outlet, day, counter, channel):
    if channel == "retail":
        picks = rng.sample(MEAT, rng.randint(1, 2))
        lines = []
        for i, (code, _name, price) in enumerate(picks, 1):
            qty = round(rng.uniform(0.6, 2.2), 3)
            gross = round(qty * price)
            lines.append({"id": uuid7(), "line_no": i, "line_type": "meat_pack", "product_id": code,
                          "product_code": code, "pack_code": f"PK-H-{outlet.code}-{counter}-{i}",
                          "quantity": f"{qty:.6f}", "uom": "kg", "unit_price": f"{price}.00",
                          "gross_amount": f"{gross}.00", "discount_amount": "0.00", "net_amount": f"{gross}.00",
                          "discounts": []})
    else:
        picks = rng.sample(MENU, rng.randint(2, 4))
        lines = []
        for i, (code, _name, _st, price, _c, _l, _s) in enumerate(picks, 1):
            qty = rng.randint(1, 3)
            gross = qty * price
            lines.append({"id": uuid7(), "line_no": i, "line_type": "restaurant_menu", "product_id": code,
                          "product_code": code, "pack_code": None, "quantity": f"{qty:.6f}", "uom": "unit",
                          "unit_price": f"{price}.00", "gross_amount": f"{gross}.00", "discount_amount": "0.00",
                          "net_amount": f"{gross}.00", "discounts": []})
    net = sum(int(l["net_amount"][:-3]) for l in lines)
    method = rng.choice(["cash", "qris", "qris", "edc_manual"])
    hour = rng.randint(3, 13)  # 10:00-20:00 WIB dalam UTC
    finalized = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=rng.randint(0, 59))
    return {
        "id": uuid7(), "doc_no": f"{outlet.code}-{day:%y%m%d}-{counter:05d}", "outlet_id": outlet.code,
        "channel": channel, "business_date": fields.Date.to_string(day), "gross_amount": f"{net}.00",
        "discount_amount": "0.00", "net_amount": f"{net}.00", "finalized_at": finalized.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lines": lines, "payments": [{"id": uuid7(), "method": method, "amount": f"{net}.00", "status": "succeeded"}],
    }
