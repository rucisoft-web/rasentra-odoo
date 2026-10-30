{
    "name": "Rasentra Sync Outlet",
    "summary": "Rasentra Lokal: outbox event ke Central, tarik publikasi master, bootstrap snapshot, heartbeat",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_core", "queue_job"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/rasentra_sync_outlet_views.xml",
    ],
    "installable": True,
}
