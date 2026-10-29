"""Aritmetika uang dan berat tanpa float, padanan App\\Support\\Decimal di Laravel.

Uang 2 desimal dan berat/kuantitas 6 desimal, pembulatan HALF_UP. Pembulatan
selalu diterapkan pada rupiah, tidak pada berat.
"""

from decimal import ROUND_HALF_UP, Decimal

MONEY_STEP = Decimal("0.01")
QTY_STEP = Decimal("0.000001")


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    if value is None or value is False:
        return Decimal(0)
    if isinstance(value, float):
        # float dari ORM dibaca lewat repr agar 1.75 tidak menjadi 1.7499999...
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value):
    return to_decimal(value).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def qty(value):
    return to_decimal(value).quantize(QTY_STEP, rounding=ROUND_HALF_UP)
