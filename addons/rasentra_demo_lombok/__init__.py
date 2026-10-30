from odoo.addons.rasentra_demo.builder import build_company

LOMBOK = {
    "key": "lombok",
    "company": "CV Lombok Kulina Utama",
    "sap_db": "sap_lombok",
    "city": "Mataram",
    "region": ("LOP", "Lombok"),
    "tz": "Asia/Makassar",
    "price_markup": 0.05,
    "unmapped": ("SHORTRIB-US",),
    "cutover_in_days": 50,
    "outlets": [
        {"key": "lop_ms", "code": "LOP-MS", "name": "Meatshop Lombok", "retail": True, "cooking": True,
         "restaurant": True, "users": True, "retail_name": "Meatshop Lombok", "restaurant_name": "Grill Lombok",
         "people": {"outlet_head": "Putu Kepala Lombok", "cashier": "Baiq Kasir", "waiter": "Lalu Pelayan",
                    "chef": "Made Chef", "warehouse": "Ketut Gudang"}},
        {"key": "lop_ep", "code": "LOP-EP", "name": "El Primo Lombok", "restaurant": True,
         "restaurant_name": "El Primo",
         "people": {"outlet_head": "Gede Kepala El Primo", "cashier": "Nia Kasir El Primo",
                    "waiter": "Rudi Pelayan El Primo", "chef": "Komang Chef El Primo"}},
    ],
    "pos": [
        {"key": "lop_ms_retail", "name": "Meatshop Lombok · Kasir", "outlet": "LOP-MS", "channel": "retail"},
        {"key": "lop_ms_grill", "name": "Grill Lombok", "outlet": "LOP-MS", "channel": "restaurant",
         "floors": [("Grill", 4)]},
        {"key": "lop_ep_resto", "name": "El Primo", "outlet": "LOP-EP", "channel": "restaurant",
         "floors": [("Dining", 8), ("Rooftop", 6)]},
    ],
    "promos": [("ayam_lombok", "AYAM-LOP-12", "Ayam fillet Lombok 12%", {"percent": 12, "product_ids": ["CHICKEN-FILLET"]})],
}


def post_init_hook(env):
    build_company(env, "rasentra_demo_lombok", LOMBOK)
