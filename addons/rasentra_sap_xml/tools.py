"""Parser NMEXML aman (port NmexmlParser). Nilai dibiarkan string: field hilang (None), kosong ('') dan nol ('0')
dibedakan; kode barang dengan nol di depan tidak diubah menjadi angka."""

import re

from lxml import etree

from odoo.addons.rasentra_core.tools import RasentraError

MAX_BYTES = 20 * 1024 * 1024
MAX_ELEMENTS = 500_000
_FORBIDDEN = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)

def _parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                           huge_tree=False, remove_comments=True, remove_pis=True)

def _child(node, name):
    for child in node:
        if isinstance(child.tag, str) and child.tag == name:
            return (child.text or "").strip() if len(child) == 0 else "".join(child.itertext()).strip()
    return None

def _attr_or_child(node, name):
    return node.get(name) if name in node.attrib else _child(node, name)

def _flatten(node, skip=()):
    out = {f"@{k}": v for k, v in node.attrib.items()}
    for child in node:
        if isinstance(child.tag, str) and child.tag not in skip and len(child) == 0:
            out[child.tag] = child.text or ""
    return out

def parse(xml, max_bytes=MAX_BYTES, max_elements=MAX_ELEMENTS):
    """`xml` bytes. Hasil: {branch_code, invoices[], receipts[], element_count}."""
    if isinstance(xml, str):
        xml = xml.encode()
    if len(xml) > max_bytes:
        raise RasentraError("xml_too_large", "Ukuran file XML melebihi batas.")
    if _FORBIDDEN.search(xml):
        raise RasentraError("xml_doctype_forbidden", "XML dengan DOCTYPE/ENTITY ditolak.")
    try:
        root = etree.fromstring(xml, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise RasentraError("xml_invalid", "Struktur XML tidak sah.") from exc
    count = sum(1 for _el in root.iter(tag=etree.Element))
    if count > max_elements:
        raise RasentraError("xml_too_many_elements", "Jumlah elemen XML melebihi batas.")
    if root.tag != "NMEXML":
        raise RasentraError("xml_root_invalid", "Akar dokumen harus NMEXML.")

    branch = _attr_or_child(root, "BranchCode")
    if branch is None:
        branch = _attr_or_child(root, "BRANCHCODE")
    invoices = []
    for node in root.iter("SALESINVOICE"):
        lines = [{
            "source_line_key": _attr_or_child(line, "KeyID"),
            "item_no": _child(line, "ITEMNO"),
            "quantity": _child(line, "QUANTITY"),
            "unit": _child(line, "ITEMUNIT"),
            "unit_ratio": _child(line, "UNITRATIO"),
            "unit_price": _child(line, "UNITPRICE"),
            "discount_pct": _child(line, "ITEMDISCPC"),
            "bruto_unit_price": _child(line, "BRUTOUNITPRICE"),
            "dept_id": _child(line, "DEPTID"),
            "raw": _flatten(line),
        } for line in node.findall("ITEMLINE")]
        own = _attr_or_child(node, "BranchCode")
        invoices.append({
            "branch_code": own if own is not None else branch,
            "invoice_no": _child(node, "INVOICENO"),
            "invoice_date": _child(node, "INVOICEDATE"),
            "customer_id": _child(node, "CUSTOMERID"),
            "warehouse_id": _child(node, "WAREHOUSEID"),
            "cash_discount": _child(node, "CASHDISCOUNT"),
            "cash_discount_pct": _child(node, "CASHDISCPC"),
            "invoice_amount": _child(node, "INVOICEAMOUNT"),
            "tax_codes": _child(node, "TAXCODES"),
            "ar_account": _child(node, "ARACCOUNT"),
            "lines": lines,
            "raw": _flatten(node, ("ITEMLINE",)),
        })
    receipts = []
    for node in root.iter("CUSTOMERRECEIPT"):
        allocations = [{
            "invoice_no": _child(line, "ARINVOICEID"),
            "amount": _child(line, "PAYMENTAMOUNT"),
            "raw": _flatten(line),
        } for line in node.findall("InvoiceLine")]
        own = _attr_or_child(node, "BranchCode")
        receipts.append({
            "branch_code": own if own is not None else branch,
            "sequence_no": _child(node, "SEQUENCENO"),
            "payment_date": _child(node, "PAYMENTDATE"),
            "bill_to_id": _child(node, "BILLTOID"),
            "bank_account": _child(node, "BANKACCOUNT"),
            "cheque_amount": _child(node, "CHEQUEAMOUNT"),
            "currency": _child(node, "CURRENCYNAME"),
            "rate": _child(node, "RATE"),
            "void": _child(node, "VOID"),
            "allocations": allocations,
            "raw": _flatten(node, ("InvoiceLine",)),
        })
    return {"branch_code": branch, "invoices": invoices, "receipts": receipts, "element_count": count}
