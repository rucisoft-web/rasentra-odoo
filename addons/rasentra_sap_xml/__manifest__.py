{
    "name": "Rasentra SAP XML (NMEXML)",
    "summary": "Impor MSI/MSR NMEXML dari sistem lama ke staging, aman (tanpa DTD/entity), dedup per nomor sumber",
    "version": "18.0.1.0.0",
    "category": "Rasentra",
    "license": "LGPL-3",
    "author": "Indoguna Group",
    "depends": ["rasentra_sap_b1"],
    "external_dependencies": {"python": ["lxml"]},
    "data": [
        "security/ir.model.access.csv",
        "views/xml_views.xml",
        "wizard/xml_import_wizard_views.xml",
    ],
    "installable": True,
}
