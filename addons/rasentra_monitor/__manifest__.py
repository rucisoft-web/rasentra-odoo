{
    "name": "Rasentra Monitor",
    "summary": "Status Central: heartbeat per outlet, arus sinkron, antrean dan koneksi SAP, pengecualian integrasi",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_sap_b1"],
    "data": [
        "views/monitor_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rasentra_monitor/static/src/monitor/**/*",
        ],
    },
    "installable": True,
}
