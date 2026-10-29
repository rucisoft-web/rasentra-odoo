"""Promotion Engine, port utuh dari App\\Domain\\Promotion\\PromotionEngine.

Murni (tanpa ORM dan I/O) agar hasil kasir di Lokal, simulasi di Central dan versi
Laravel selama masa transisi sama persis. Masukan dan keluaran memakai string desimal.

Baris:  {"key", "product_id", "category", "line_type", "quantity", "unit_price", "gross"}
Promo:  {"id", "type", "scope", "rules", "priority", "stacking", "funded_by"}

Urutan: promo item lebih dahulu, lalu promo keranjang; masing-masing menurut priority lalu id.
  exclusive    baris yang sudah mendapat promo exclusive tidak menerima promo lain
  stackable    dihitung atas sisa nilai bersih baris
  best_benefit di antara kandidat best_benefit hanya manfaat terbesar per baris yang dipakai

Di Odoo, `product_id` pada baris dan aturan adalah kode produk (default_code), karena id
database Central dan Lokal berbeda. Pembandingan memakai string.
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from odoo.addons.rasentra_core.tools import money, to_decimal

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _round(value, rounding=ROUND_HALF_UP):
    return value.quantize(CENT, rounding=rounding)


def _str(value):
    return str(money(value))


def evaluate(lines, promotions):
    state = {}
    for line in lines:
        state[str(line["key"])] = {
            "line": line,
            "net": to_decimal(line["gross"]),
            "exclusive_taken": False,
            "allocations": [],
        }

    promotions = sorted(promotions, key=lambda p: (int(p.get("priority") or 100), p["id"]))
    item_promos = [p for p in promotions if (p.get("scope") or "item") == "item"]
    basket_promos = [p for p in promotions if (p.get("scope") or "item") == "basket"]
    best = [p for p in item_promos if (p.get("stacking") or "exclusive") == "best_benefit"]
    others = [p for p in item_promos if (p.get("stacking") or "exclusive") != "best_benefit"]

    for promo in others:
        _apply_item_promo(promo, state)

    if best:
        for key, entry in state.items():
            if entry["exclusive_taken"]:
                continue
            winner, winner_amount = None, ZERO
            for promo in best:
                amount = _item_benefits(promo, state).get(key, ZERO)
                if amount > winner_amount:
                    winner, winner_amount = promo, amount
            if winner is not None:
                _allocate(state, key, winner, winner_amount)
                entry["exclusive_taken"] = True

    for promo in basket_promos:
        _apply_basket_promo(promo, state)

    result_lines, total, applied = {}, ZERO, {}
    for key, entry in state.items():
        discount = to_decimal(entry["line"]["gross"]) - entry["net"]
        total += discount
        for allocation in entry["allocations"]:
            applied[allocation["promotion_version_id"]] = True
        result_lines[key] = {
            "discount": _str(discount),
            "net": _str(entry["net"]),
            "allocations": entry["allocations"],
        }
    return {"lines": result_lines, "total_discount": _str(total), "applied": list(applied)}


def _apply_item_promo(promo, state):
    for key, amount in _item_benefits(promo, state).items():
        if amount == 0:
            continue
        _allocate(state, key, promo, amount)
        if (promo.get("stacking") or "exclusive") == "exclusive":
            state[key]["exclusive_taken"] = True


def _item_benefits(promo, state):
    """Manfaat per baris, sudah dibatasi sisa nilai bersih."""
    rules = promo["rules"]
    eligible = {k: s for k, s in state.items() if not s["exclusive_taken"] and _matches(rules, s["line"])}
    if not eligible:
        return {}

    benefits = {}
    kind = promo["type"]
    if kind == "percent":
        for key, s in eligible.items():
            benefits[key] = _round(s["net"] * to_decimal(rules["percent"]) / 100)
    elif kind == "special_price":
        for key, s in eligible.items():
            special = _round(to_decimal(s["line"]["quantity"]) * to_decimal(rules["price"]))
            benefits[key] = max(ZERO, to_decimal(s["line"]["gross"]) - special)
    elif kind == "weight_tier":
        # Syarat berat dihitung gabungan seluruh baris yang memenuhi, dengan presisi berat sebenarnya.
        weight = sum((to_decimal(s["line"]["quantity"]) for s in eligible.values()), ZERO)
        percent = None
        for tier in rules["tiers"]:
            if weight >= to_decimal(tier["min_weight"]):
                percent = tier["percent"]
        if percent is not None:
            for key, s in eligible.items():
                benefits[key] = _round(s["net"] * to_decimal(percent) / 100)
    elif kind == "buy_x_get_y":
        buy_qty = sum(
            (to_decimal(s["line"]["quantity"]) for s in state.values()
             if str(s["line"]["product_id"]) == str(rules["buy_product_id"])),
            ZERO,
        )
        multiple = (buy_qty / to_decimal(rules["buy_qty"])).to_integral_value(rounding=ROUND_DOWN)
        if rules.get("max_multiple") is not None:
            multiple = min(multiple, to_decimal(rules["max_multiple"]))
        free_left = multiple * to_decimal(rules["get_qty"])
        for key, s in eligible.items():
            if str(s["line"]["product_id"]) != str(rules["get_product_id"]) or free_left == 0:
                continue
            quantity = min(free_left, to_decimal(s["line"]["quantity"]))
            free_left -= quantity
            # Barang gratis tetap berupa baris dan tetap memotong stok; hanya nilainya nol.
            benefits[key] = _round(quantity * to_decimal(s["line"]["unit_price"]))

    for key, amount in benefits.items():
        if rules.get("max_discount") is not None:
            amount = min(amount, to_decimal(rules["max_discount"]))
        benefits[key] = min(amount, state[key]["net"])
    return benefits


def _apply_basket_promo(promo, state):
    rules = promo["rules"]
    eligible = {k: s for k, s in state.items() if not s["exclusive_taken"] and _matches(rules, s["line"])}
    base = sum((s["net"] for s in eligible.values()), ZERO)
    if not eligible or base == 0:
        return
    if rules.get("min_spend") is not None and base < to_decimal(rules["min_spend"]):
        return

    if rules.get("percent") is not None:
        benefit = _round(base * to_decimal(rules["percent"]) / 100)
    else:
        benefit = to_decimal(rules["amount"])
    if rules.get("max_discount") is not None:
        benefit = min(benefit, to_decimal(rules["max_discount"]))
    benefit = min(benefit, base)

    # Alokasi proporsional nilai bersih; sisa pembulatan ke baris terbesar agar retur dan pajak tertelusur.
    keys = sorted(eligible, key=lambda k: (-state[k]["net"], k))
    shares, allocated = {}, ZERO
    for key in keys:
        share = _round(benefit * state[key]["net"] / base, ROUND_DOWN)
        shares[key] = share
        allocated += share
    shares[keys[0]] += benefit - allocated

    for key, share in shares.items():
        if share != 0:
            _allocate(state, key, promo, share)
        if (promo.get("stacking") or "exclusive") == "exclusive":
            state[key]["exclusive_taken"] = True


def _allocate(state, key, promo, amount):
    state[key]["net"] -= amount
    state[key]["allocations"].append(
        {"promotion_version_id": promo["id"], "amount": _str(amount), "funded_by": promo.get("funded_by") or "internal"}
    )


def _matches(rules, line):
    if rules.get("product_ids") and str(line["product_id"]) not in {str(p) for p in rules["product_ids"]}:
        return False
    if rules.get("categories") and line.get("category") not in rules["categories"]:
        return False
    if rules.get("line_types") and line.get("line_type") not in rules["line_types"]:
        return False
    if rules.get("exclude_line_types") and line.get("line_type") in rules["exclude_line_types"]:
        return False
    return True
