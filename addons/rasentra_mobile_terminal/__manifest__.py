{
    "name": "Rasentra Mobile Terminal",
    "summary": "POS restoran di tablet pelayan: kunjungan meja bertoken, status meja dan dapur, minta tagihan, pindah meja",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_kitchen"],
    "data": [
        "security/ir.model.access.csv",
        "views/visit_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "rasentra_mobile_terminal/static/src/app/**/*",
        ],
        "web.assets_tests": [
            "rasentra_mobile_terminal/static/tests/tours/**/*",
        ],
    },
    "installable": True,
}
