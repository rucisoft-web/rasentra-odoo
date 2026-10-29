{
    "name": "Rasentra Migrasi",
    "summary": "Menu migrasi dari Raptor/SAP B1 dan Rene POS/Accurate: gelombang cut-over, langkah H-45 s/d H+30, "
               "template CSV dan impor data awal dengan pemeriksaan otomatis",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_pos_meatshop", "rasentra_stock_count", "rasentra_sap_xml"],
    "data": [
        "security/ir.model.access.csv",
        "views/migration_views.xml",
    ],
    "installable": True,
}
