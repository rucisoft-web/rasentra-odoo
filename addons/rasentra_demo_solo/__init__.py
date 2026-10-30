from odoo.addons.rasentra_demo.builder import build_company

SOLO = {
    "key": "solo",
    "company": "CV Solo Kulina Utama",
    "sap_db": "sap_solo",
    "city": "Surakarta",
    "region": ("SLO", "Solo"),
    "tz": "Asia/Jakarta",
    "xml_sample": True,
    "unmapped": ("MINCE-BEEF",),
    "cutover_in_days": 21,
    "outlets": [
        {"key": "slo_ms", "code": "SLO-MS", "name": "Meatshop & Grill Solo", "retail": True, "restaurant": True,
         "cooking": True, "users": True, "retail_name": "Meatshop Solo", "restaurant_name": "Grill Corner Solo",
         "people": {"outlet_head": "Rina Kepala Solo", "cashier": "Budi Kasir", "waiter": "Sari Pelayan",
                    "chef": "Agus Chef", "warehouse": "Dedi Gudang"}},
        {"key": "slo_rb", "code": "SLO-RB", "name": "Restoran R&B Solo", "restaurant": True,
         "restaurant_name": "R&B Steakhouse",
         "people": {"outlet_head": "Wahyu Kepala R&B", "cashier": "Lina Kasir R&B", "waiter": "Tono Pelayan R&B",
                    "chef": "Joko Chef R&B"}},
    ],
    "pos": [
        {"key": "slo_ms_retail", "name": "Meatshop Solo · Kasir", "outlet": "SLO-MS", "channel": "retail"},
        {"key": "slo_ms_grill", "name": "Grill Corner Solo", "outlet": "SLO-MS", "channel": "restaurant",
         "floors": [("Grill corner", 6)]},
        {"key": "slo_rb_resto", "name": "R&B Steakhouse", "outlet": "SLO-RB", "channel": "restaurant",
         "floors": [("Lantai 1", 8), ("Teras", 4)]},
    ],
    "promos": [("sirloin_weekend", "SIRLOIN-10", "Sirloin hemat 10%", {"percent": 10, "product_ids": ["SIRLOIN-AUS"]})],
}


def post_init_hook(env):
    build_company(env, "rasentra_demo_solo", SOLO)
