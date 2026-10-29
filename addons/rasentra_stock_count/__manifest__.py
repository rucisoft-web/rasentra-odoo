{
    "name": "Rasentra Stock Count",
    "summary": "Rasentra Inventory Lokal: terima Pack ID, opname blind + hitung ulang, karantina, waste, dokumen penyesuaian",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_pack_id", "rasentra_sync_outlet"],
    "data": [
        "security/ir.model.access.csv",
        "views/rasentra_stock_adjustment_views.xml",
        "views/rasentra_count_session_views.xml",
        "wizards/rasentra_inventory_wizard_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
