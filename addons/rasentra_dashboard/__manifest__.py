{
    "name": "Rasentra Dashboard",
    "summary": "Ringkasan grup per CV dan outlet: penjualan hari ini dan 7 hari, kanal, kesehatan outlet, SAP, pekerjaan tertunda",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_monitor"],
    "data": [
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rasentra_dashboard/static/src/dashboard/**/*",
        ],
    },
    "installable": True,
}
