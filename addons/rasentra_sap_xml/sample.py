"""Sampel NMEXML deterministik setara sampel 28 Oktober 2026: 49 invoice, 182 baris (60 pecahan),
49 pembayaran, total Rp18.811.355, satu invoice selisih pembulatan Rp0,40."""

from decimal import ROUND_HALF_UP, Decimal

TARGET = Decimal("18811355")


def _invoices():
    invoices, line_no = [], 0
    for i in range(49):
        count = 4 if i < 35 else 3
        lines = []
        for _j in range(count):
            line_no += 1
            fractional = line_no <= 60
            quantity = Decimal("1.25") if fractional else Decimal(1 + line_no % 3)
            price = Decimal(20000 + (line_no % 7) * 4000)
            discount = Decimal(10) if line_no % 9 == 0 else Decimal(0)
            lines.append({"item": f"{line_no:05d}", "qty": quantity, "price": price, "disc": discount})
        invoices.append(lines)
    # Invoice ke-7: 1,4 x 101 = 141,40 tetapi sistem lama mencetak 141 (selisih Rp0,40).
    invoices[6][-1].update(qty=Decimal("2"), price=Decimal("50000"), disc=Decimal(0))
    invoices[6].append({"item": "00999", "qty": Decimal("1.4"), "price": Decimal("101"), "disc": Decimal(0)})
    invoices[48].pop()  # tetap 182 baris
    return invoices


def _calc(line):
    return line["qty"] * line["price"] * (100 - line["disc"]) / 100


def build():
    invoices = _invoices()
    invoices[48][-1].update(qty=Decimal(1), disc=Decimal(0))
    amounts = [sum(_calc(l) for l in lines) for lines in invoices]
    amounts[6] = amounts[6].quantize(Decimal(1), rounding="ROUND_DOWN")
    # Baris terakhir invoice terakhir menutup total sampai Rp18.811.355.
    remainder = TARGET - sum(amounts)
    last = invoices[48][-1]
    last["price"] += remainder
    amounts[48] += remainder
    assert last["price"] > 0
    msi, msr = ['<?xml version="1.0"?>\n<NMEXML BranchCode="SLO" EximID="1">'], ['<NMEXML BranchCode="SLO">']
    for i, (lines, amount) in enumerate(zip(invoices, amounts), 1):
        msi.append(f"<SALESINVOICE><INVOICENO>SI-2610-{i:04d}</INVOICENO><INVOICEDATE>2026-10-28</INVOICEDATE>"
                   f"<CUSTOMERID>C{i:03d}</CUSTOMERID><WAREHOUSEID>01</WAREHOUSEID><CASHDISCOUNT>0</CASHDISCOUNT>"
                   f"<INVOICEAMOUNT>{amount}</INVOICEAMOUNT><TAXCODES></TAXCODES>")
        for k, line in enumerate(lines, 1):
            msi.append(f'<ITEMLINE KeyID="{k}"><ITEMNO>{line["item"]}</ITEMNO><QUANTITY>{line["qty"]}</QUANTITY>'
                       f'<ITEMUNIT>KG</ITEMUNIT><UNITRATIO>1</UNITRATIO><UNITPRICE>{line["price"]}</UNITPRICE>'
                       f'<ITEMDISCPC>{line["disc"] if line["disc"] else ""}</ITEMDISCPC><DEPTID>0</DEPTID></ITEMLINE>')
        msi.append("</SALESINVOICE>")
        msr.append(f"<CUSTOMERRECEIPT><SEQUENCENO>CR-2610-{i:04d}</SEQUENCENO><PAYMENTDATE>28/10/2026</PAYMENTDATE>"
                   f"<BILLTOID>C{i:03d}</BILLTOID><CHEQUEAMOUNT>{amount}</CHEQUEAMOUNT><CURRENCYNAME>IDR</CURRENCYNAME>"
                   f"<InvoiceLine><ARINVOICEID>SI-2610-{i:04d}</ARINVOICEID><PAYMENTAMOUNT>{amount}</PAYMENTAMOUNT>"
                   f"</InvoiceLine></CUSTOMERRECEIPT>")
    msi.append("</NMEXML>")
    msr.append("</NMEXML>")
    return "".join(msi).encode(), "".join(msr).encode()


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
