{
    "name": "Rasentra Theme",
    "summary": "Tema ringan food specialist untuk backend, halaman login dan POS (warna, logo, ikon; tanpa font/JS tambahan)",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["web", "point_of_sale", "rasentra_core"],
    "data": [
        "views/login_templates.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            ("before", "web/static/src/scss/primary_variables.scss",
             "rasentra_theme/static/src/scss/primary_variables.scss"),
        ],
        "web.assets_backend": [
            "rasentra_theme/static/src/scss/backend.scss",
        ],
        "web.assets_frontend": [
            "rasentra_theme/static/src/scss/login.scss",
        ],
        "point_of_sale._assets_pos": [
            "rasentra_theme/static/src/scss/pos.scss",
            "rasentra_theme/static/src/pos/navbar.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
