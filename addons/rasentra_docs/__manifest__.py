{
    "name": "Rasentra Spesifikasi & Panduan",
    "summary": "Menu Spesifikasi & Panduan untuk semua peran: arsitektur, diagram konsep, alur kerja dan screenshot per peran",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["web"],
    "data": [
        "views/docs_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rasentra_docs/static/src/docs/**/*",
        ],
    },
    "installable": True,
}
