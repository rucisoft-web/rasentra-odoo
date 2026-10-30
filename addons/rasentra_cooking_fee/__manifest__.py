{
    "name": "Rasentra Cooking Fee",
    "summary": "Pilih daging retail lalu dimasak: aturan tarif berversi, cooking job dari Pack ID, hak layanan dari struk",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_pos_meatshop", "rasentra_recipe", "rasentra_stock_count"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_data.xml",
        "views/cooking_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "rasentra_cooking_fee/static/src/app/**/*",
        ],
    },
    "installable": True,
}
