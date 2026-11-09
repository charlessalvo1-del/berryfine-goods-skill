import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "berryfine-goods-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from adaptive_market_gate import GateError  # noqa: E402
from price_first_gate import validate_item  # noqa: E402
from pricing_policy import synthesize  # noqa: E402


class PriceFirstGateTests(unittest.TestCase):
    def case(self):
        urls = [
            "https://www.ebay.com/itm/1001",
            "https://www.ebay.com/itm/1002",
            "https://www.etsy.com/listing/1003/example",
        ]
        surfaces = [
            "Integrated Web Search",
            "Image Search",
            "Etsy",
            "eBay",
            "Integrated Web Search",
            "Image Search",
            "Etsy",
            "eBay",
        ]
        attempts = [
            {
                "query": f"verified object strategy {index}",
                "strategy": "image search" if index in {2, 6} else f"strategy {index}",
                "surface": surface,
                "search_url": f"https://www.google.com/search?q=verified+object+{index}",
                "opened_urls": urls if index == 8 else [],
                "captured_at": "2026-11-09T10:00:00-05:00",
            }
            for index, surface in enumerate(surfaces, 1)
        ]
        comps = []
        for index, (url, market, price) in enumerate(
            zip(urls, ("ebay", "ebay", "etsy"), (80, 90, 100)), 1
        ):
            comps.append(
                {
                    "comp_id": f"c{index}",
                    "source_url": url,
                    "marketplace": market,
                    "listing_status": "active",
                    "comparability": "exact",
                    "included": True,
                    "title": "Verified object",
                    "include_reason": "Exact direct match",
                    "captured_at": "2026-11-09T10:00:00-05:00",
                    "evidence_sha256": f"{index:064x}",
                    "direct_page_verified": True,
                    "quantity": 1,
                    "normalized_unit_total_usd": price,
                }
            )
        item = {
            "item_id": "item-1",
            "search_attempts": attempts,
            "pricing_comparables": comps,
            "identification_assessment": {"confidence": "confirmed", "basis": "visible model"},
            "search_completion": {"stop_tier": 8, "stop_reason": "Three direct prices found.", "staff_boundary_decision": False},
        }
        result = synthesize(item)
        item["pricing_confidence"] = result["pricing_confidence"]
        item["price_synthesis"] = {
            "method": "weighted_marketplace_median",
            "price_type": result["price_type"],
            **{field: result[field] for field in ("market_value_low", "market_value_mid", "market_value_high", "decision_basis_value", "etsy_price", "ebay_price")},
        }
        ledger = {
            "safety_status": "CLEAR",
            "price_type": result["price_type"],
            "valuation_basis": result["valuation_basis"],
            "valuation_confidence": result["pricing_confidence"],
            "decision": result["decision"],
            "comp_count": str(result["comp_count"]),
            **{field: str(result[field]) for field in ("market_value_low", "market_value_mid", "market_value_high", "decision_basis_value", "ebay_price")},
        }
        return item, ledger

    def test_validates_reproducible_price_first_result(self):
        item, ledger = self.case()
        finding = validate_item(item, ledger)
        self.assertEqual(finding["decision"], "SELL")
        self.assertEqual(finding["price_type"], "market")

    def test_rejects_tampered_ledger_price(self):
        item, ledger = self.case()
        ledger["ebay_price"] = "999"
        with self.assertRaisesRegex(GateError, "not reproducible"):
            validate_item(item, ledger)


if __name__ == "__main__":
    unittest.main()
