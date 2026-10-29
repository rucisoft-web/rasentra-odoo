{
    "name": "Rasentra Sync Central",
    "summary": "API /api/v1/sync di Rasentra Central: terima event outlet, sajikan publikasi master, snapshot, heartbeat",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_core", "fastapi"],
    "data": [
        "security/ir.model.access.csv",
        "data/fastapi_endpoint.xml",
        "views/rasentra_sync_central_views.xml",
    ],
    "installable": True,
}
