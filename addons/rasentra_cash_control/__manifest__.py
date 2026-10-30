{
    "name": "Rasentra Cash Control",
    "summary": "Shift kasir = sesi POS: kas masuk/keluar beralasan, tutup shift dengan hitungan, selisih, dan persetujuan",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_pos_meatshop"],
    "data": [
        "data/config_data.xml",
        "data/cron.xml",
        "views/pos_session_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "rasentra_cash_control/static/src/app/**/*",
        ],
    },
    "installable": True,
}
