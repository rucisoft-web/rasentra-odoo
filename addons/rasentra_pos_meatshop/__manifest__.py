{
    "name": "Rasentra POS Meatshop",
    "summary": "POS Rasentra Lokal: scan Pack ID dengan kunci server, harga berversi, promo engine, finalisasi ke outbox",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["point_of_sale", "pos_hr", "rasentra_pack_id", "rasentra_promo", "rasentra_sync_outlet"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_data.xml",
        "views/pos_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "rasentra_pos_meatshop/static/src/app/**/*",
        ],
        "web.assets_tests": [
            "rasentra_pos_meatshop/static/tests/tours/**/*",
        ],
    },
    "installable": True,
}
