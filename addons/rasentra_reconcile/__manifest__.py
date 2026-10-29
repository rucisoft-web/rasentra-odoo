{
    "name": "Rasentra Reconcile",
    "summary": "Central: proyeksi penjualan outlet ke rasentra.hq.order, rekonsiliasi tutup hari, laporan penjualan dan promo",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_sync_central", "rasentra_promo"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/hq_order_views.xml",
        "views/day_reconciliation_views.xml",
        "views/hq_stock_adjustment_views.xml",
    ],
    "installable": True,
}
