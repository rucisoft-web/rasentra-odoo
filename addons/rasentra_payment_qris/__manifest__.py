{
    "name": "Rasentra Payment QRIS",
    "summary": "Lokal: pembayaran QRIS/EDC terintegrasi dengan status sendiri (pending, uncertain), hasil provider idempoten",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_pos_meatshop"],
    "data": [
        "security/ir.model.access.csv",
        "views/payment_intent_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "rasentra_payment_qris/static/src/app/**/*",
        ],
    },
    "installable": True,
}
