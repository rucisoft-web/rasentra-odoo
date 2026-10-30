{
    "name": "Rasentra SAP B1",
    "summary": "Central: posting penjualan, pembayaran, retur, dan penyesuaian stok ke SAP Business One per CV",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_reconcile"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/sap_views.xml",
    ],
    "installable": True,
}
