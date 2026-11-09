import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "berryfine-goods-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pricing_policy import synthesize  # noqa: E402


def comp(number, price, *, marketplace="ebay", status="active", match="exact"):
    return {
        "comp_id": f"c{number}",
        "marketplace": marketplace,
        "listing_status": status,
        "comparability": match,
        "included": True,
        "normalized_unit_total_usd": price,
    }


def item(comps=(), *, identity="confirmed", staff=False):
    return {
        "pricing_comparables": list(comps),
        "identification_assessment": {"confidence": identity, "basis": "visible evidence"},
        "search_completion": {"stop_tier": 8, "staff_boundary_decision": staff},
    }


class PricingPolicyTests(unittest.TestCase):
    def test_three_direct_prices_issue_medium_sell_price(self):
        result = synthesize(item([comp(1, 80), comp(2, 90), comp(3, 100)]))
        self.assertEqual(result["price_type"], "market")
        self.assertEqual(result["pricing_confidence"], "medium")
        self.assertEqual(result["decision"], "SELL")
        self.assertGreaterEqual(result["ebay_price"], 55)

    def test_two_close_exact_prices_can_authorize_donation(self):
        result = synthesize(item([comp(1, 20), comp(2, 22)]))
        self.assertEqual(result["pricing_confidence"], "medium")
        self.assertEqual(result["decision"], "DONATE")

    def test_one_price_is_provisional_but_retained(self):
        result = synthesize(item([comp(1, 75)]))
        self.assertEqual(result["price_type"], "provisional")
        self.assertEqual(result["decision"], "REVIEW")
        self.assertEqual(result["ebay_price"], 75)

    def test_zero_comp_staff_boundary_is_operational_not_market(self):
        result = synthesize(item(staff=True))
        self.assertEqual(result["price_type"], "operational")
        self.assertEqual(result["decision_basis_value"], 45)
        self.assertEqual(result["decision"], "CONFIRM DONATION")
        self.assertIn("not a market-value claim", result["rationale"])

    def test_tentative_zero_comp_item_remains_unpriced(self):
        result = synthesize(item(identity="tentative", staff=True))
        self.assertEqual(result["price_type"], "unpriced")
        self.assertEqual(result["decision"], "REVIEW")
        self.assertIsNone(result["ebay_price"])

    def test_high_confidence_requires_two_sold_ebay_prices(self):
        comps = [
            comp(1, 80, status="sold"),
            comp(2, 85, status="completed"),
            comp(3, 90, marketplace="etsy"),
            comp(4, 95),
        ]
        result = synthesize(item(comps))
        self.assertEqual(result["pricing_confidence"], "high")


if __name__ == "__main__":
    unittest.main()
