{
    "name": "Rasentra Pack ID",
    "summary": "Pack ID daging timbang sebagai Lot Odoo: berat aktual, status, kunci jual sekali",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_core", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_lot_views.xml",
    ],
    "installable": True,
}
