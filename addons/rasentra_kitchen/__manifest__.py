{
    "name": "Rasentra Kitchen",
    "summary": "KDS Rasentra: tiket delta per station, bump, expeditor, antrean pickup, analisis waktu saji, konsumsi resep, produksi batch",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["pos_restaurant", "bus", "rasentra_cooking_fee"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/kitchen_views.xml",
        "views/production_views.xml",
        "views/pos_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rasentra_kitchen/static/src/kds/**/*",
        ],
        "point_of_sale._assets_pos": [
            "rasentra_kitchen/static/src/pos/**/*",
        ],
        "web.assets_tests": [
            "rasentra_kitchen/static/tests/tours/**/*",
        ],
    },
    "installable": True,
}
