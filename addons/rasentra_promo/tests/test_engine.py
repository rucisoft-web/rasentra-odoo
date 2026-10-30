from odoo.tests import BaseCase, tagged

from ..tools import evaluate


def line(key, product, qty, price, gross=None, category="Daging", line_type="retail_product"):
    return {"key": key, "product_id": product, "category": category, "line_type": line_type,
            "quantity": qty, "unit_price": price, "gross": gross or price}


def promo(pid, kind, rules, scope="item", stacking="exclusive", priority=100, funded_by="internal"):
    return {"id": pid, "type": kind, "scope": scope, "rules": rules, "priority": priority,
            "stacking": stacking, "funded_by": funded_by}


@tagged("rasentra")
class TestPromotionEngine(BaseCase):
    """Kasus PromotionEngine Laravel, dihitung manual dengan Decimal."""

    def test_percent_on_matching_product_only(self):
        lines = [line("1", "SIRLOIN", "1.250000", "200000.00", "250000.00"),
                 line("2", "SOSIS", "1.000000", "40000.00")]
        result = evaluate(lines, [promo("P1", "percent", {"percent": 10, "product_ids": ["SIRLOIN"]})])
        self.assertEqual(result["lines"]["1"]["discount"], "25000.00")
        self.assertEqual(result["lines"]["2"]["discount"], "0.00")
        self.assertEqual(result["total_discount"], "25000.00")
        self.assertEqual(result["applied"], ["P1"])

    def test_weight_tier_uses_combined_weight(self):
        lines = [line("1", "SIRLOIN", "1.250000", "200000.00", "250000.00"),
                 line("2", "SIRLOIN", "2.000000", "200000.00", "400000.00")]
        tiers = {"tiers": [{"min_weight": "2", "percent": 5}, {"min_weight": "3", "percent": 10}]}
        result = evaluate(lines, [promo("P1", "weight_tier", tiers)])
        self.assertEqual(result["total_discount"], "65000.00")  # 3,25 kg -> 10% dari Rp650.000

    def test_special_price(self):
        lines = [line("1", "WAGYU", "1.500000", "300000.00", "450000.00")]
        result = evaluate(lines, [promo("P1", "special_price", {"price": "250000"})])
        self.assertEqual(result["lines"]["1"]["net"], "375000.00")

    def test_buy_x_get_y_respects_max_multiple(self):
        lines = [line("1", "SOSIS", "5.000000", "20000.00", "100000.00")]
        rules = {"buy_product_id": "SOSIS", "buy_qty": 2, "get_product_id": "SOSIS", "get_qty": 1}
        self.assertEqual(evaluate(lines, [promo("P1", "buy_x_get_y", rules)])["total_discount"], "40000.00")
        rules["max_multiple"] = 1
        self.assertEqual(evaluate(lines, [promo("P1", "buy_x_get_y", rules)])["total_discount"], "20000.00")

    def test_basket_allocation_remainder_goes_to_largest_line(self):
        lines = [line("a", "X", "1", "100.00"), line("b", "Y", "1", "100.00"), line("c", "Z", "1", "100.00")]
        result = evaluate(lines, [promo("B1", "amount", {"amount": "100"}, scope="basket")])
        shares = [result["lines"][k]["discount"] for k in "abc"]
        self.assertEqual(shares, ["33.34", "33.33", "33.33"])
        self.assertEqual(result["total_discount"], "100.00")

    def test_basket_min_spend_and_max_discount(self):
        lines = [line("1", "X", "1", "300000.00"), line("2", "Y", "1", "100000.00")]
        rules = {"percent": 10, "min_spend": "500000"}
        self.assertEqual(evaluate(lines, [promo("B1", "percent", rules, scope="basket")])["total_discount"], "0.00")
        rules = {"percent": 10, "max_discount": "25000"}
        result = evaluate(lines, [promo("B1", "percent", rules, scope="basket")])
        self.assertEqual(result["lines"]["1"]["discount"], "18750.00")
        self.assertEqual(result["lines"]["2"]["discount"], "6250.00")

    def test_exclusive_blocks_and_stackable_stacks(self):
        lines = [line("1", "SIRLOIN", "1", "100000.00")]
        first = promo("P1", "percent", {"percent": 10}, priority=10)
        stack = promo("P2", "percent", {"percent": 10}, stacking="stackable", priority=20)
        self.assertEqual(evaluate([*lines], [first, stack])["total_discount"], "10000.00")
        first["stacking"] = "stackable"
        # 10% lalu 10% dari sisa 90.000 = 19.000
        self.assertEqual(evaluate(lines, [first, stack])["total_discount"], "19000.00")

    def test_best_benefit_picks_largest_per_line(self):
        lines = [line("1", "SIRLOIN", "1", "100000.00"), line("2", "SOSIS", "1", "40000.00")]
        promos = [
            promo("P1", "percent", {"percent": 10}, stacking="best_benefit"),
            promo("P2", "special_price", {"price": "85000", "product_ids": ["SIRLOIN"]}, stacking="best_benefit"),
        ]
        result = evaluate(lines, promos)
        self.assertEqual(result["lines"]["1"]["allocations"][0]["promotion_version_id"], "P2")
        self.assertEqual(result["lines"]["1"]["discount"], "15000.00")
        self.assertEqual(result["lines"]["2"]["discount"], "4000.00")

    def test_line_type_filter_and_funded_by(self):
        lines = [line("1", "STEAK", "1", "150000.00", line_type="restaurant_menu"),
                 line("2", "FEE", "1", "25000.00", line_type="cooking_service")]
        p = promo("P1", "percent", {"percent": 20, "exclude_line_types": ["cooking_service"]}, funded_by="bank")
        result = evaluate(lines, [p])
        self.assertEqual(result["lines"]["2"]["discount"], "0.00")
        self.assertEqual(result["lines"]["1"]["allocations"],
                         [{"promotion_version_id": "P1", "amount": "30000.00", "funded_by": "bank"}])
