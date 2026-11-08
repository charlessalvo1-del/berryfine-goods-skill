import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "adaptive_market_gate.py"


class AdaptiveMarketGateTests(unittest.TestCase):
    def run_gate(self, research: dict, ledger_row: dict[str, str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research_path = root / "research.json"
            ledger_path = root / "ledger.csv"
            output_path = root / "verification.json"
            research_path.write_text(json.dumps(research), encoding="utf-8")
            with ledger_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(ledger_row))
                writer.writeheader()
                writer.writerow(ledger_row)
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--research",
                    str(research_path),
                    "--ledger",
                    str(ledger_path),
                    "--client-id",
                    "client-a",
                    "--intake-id",
                    "intake-a",
                    "--output",
                    str(output_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def stable_case(self) -> tuple[dict, dict[str, str]]:
        captured = "2026-11-08T12:00:00-05:00"
        attempts = [
            {
                "query": f"verified item strategy {number}",
                "strategy": strategy,
                "surface": surface,
                "search_url": f"https://www.google.com/search?q=verified+item+{number}",
                "opened_urls": [f"https://example.com/reference-{number}"],
                "captured_at": captured,
            }
            for number, (strategy, surface) in enumerate(
                [
                    ("marking exact", "Google"),
                    ("image search", "Google Images"),
                    ("etsy marketplace", "Etsy"),
                    ("ebay marketplace", "eBay"),
                    ("construction confirmation", "Google"),
                    ("variant exclusion", "Google"),
                ],
                1,
            )
        ]
        prices = [80, 85, 90, 95]
        comps = []
        for number, price in enumerate(prices, 1):
            marketplace = "etsy" if number <= 2 else "ebay"
            url = (
                f"https://www.etsy.com/listing/{number}/verified-item"
                if marketplace == "etsy"
                else f"https://www.ebay.com/itm/{number}"
            )
            comps.append(
                {
                    "comp_id": f"c{number}",
                    "source_url": url,
                    "marketplace": marketplace,
                    "listing_status": "active",
                    "comparability": "exact",
                    "included": True,
                    "title": "Verified item exact match",
                    "include_reason": "Same maker, model, and quantity.",
                    "captured_at": captured,
                    "evidence_sha256": hashlib.sha256(url.encode()).hexdigest(),
                    "direct_page_verified": True,
                    "quantity": 1,
                    "normalized_unit_total_usd": price,
                }
            )
        for attempt, comp in zip(attempts[2:], comps, strict=False):
            attempt["opened_urls"].append(comp["source_url"])
        average = sum(prices) / len(prices)
        highest = max(prices)
        anchor = min(max((average + highest * 0.8) / 2, min(prices)), highest)
        item = {
            "item_id": "item-a",
            "search_attempts": attempts,
            "pricing_comparables": comps,
            "identification_assessment": {
                "confidence": "confirmed",
                "basis": "Visible maker and model match direct references.",
            },
            "search_completion": {
                "stop_tier": 6,
                "stop_reason": "Four exact prices are stable and away from a boundary.",
            },
            "price_synthesis": {
                "cleaned_average": average,
                "highest_cleaned_price": highest,
                "high_80": highest * 0.8,
                "anchor": anchor,
                "etsy_price": anchor * 0.95,
                "ebay_price": anchor * 1.05,
            },
            "pricing_confidence": "high",
        }
        research = {
            "research_policy_version": "2.7.0-pilot",
            "client_id": "client-a",
            "intake_id": "intake-a",
            "items": [item],
        }
        ledger = {
            "intake_id": "intake-a",
            "item_id": "item-a",
            "market_value_low": "70",
            "market_value_high": "100",
            "decision": "SELL",
            "decision_rationale": "Entire supported range is at least $50.",
        }
        return research, ledger

    def test_passes_stable_six_search_case(self) -> None:
        research, ledger = self.stable_case()
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"research_policy_version": "2.7.0-pilot"', result.stdout)

    def test_rejects_midpoint_sell_when_range_crosses_threshold(self) -> None:
        research, ledger = self.stable_case()
        ledger["market_value_low"] = "45"
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match supported range (REVIEW)", result.stderr)

    def test_rejects_included_auction_price(self) -> None:
        research, ledger = self.stable_case()
        comp = research["items"][0]["pricing_comparables"][0]
        comp["marketplace"] = "auction"
        comp["listing_status"] = "auction_result"
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot price the item", result.stderr)

    def test_allows_approved_integrated_web_discovery(self) -> None:
        research, ledger = self.stable_case()
        for attempt in research["items"][0]["search_attempts"]:
            if "Google" in attempt["surface"]:
                attempt["surface"] = "Integrated Web Search"
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_included_price_not_opened_in_attempts(self) -> None:
        research, ledger = self.stable_case()
        source_url = research["items"][0]["pricing_comparables"][0]["source_url"]
        for attempt in research["items"][0]["search_attempts"]:
            attempt["opened_urls"] = [url for url in attempt["opened_urls"] if url != source_url]
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("included price was not opened", result.stderr)

    def test_rejects_ebay_before_etsy(self) -> None:
        research, ledger = self.stable_case()
        attempts = research["items"][0]["search_attempts"]
        attempts[2]["surface"], attempts[3]["surface"] = attempts[3]["surface"], attempts[2]["surface"]
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("search Etsy before eBay", result.stderr)

    def test_zero_price_staff_boundary_requires_forty_to_fifty_range(self) -> None:
        research, ledger = self.stable_case()
        item = research["items"][0]
        item["search_attempts"].extend([
            {
                "query": "verified item low value boundary challenge one",
                "strategy": "boundary challenge",
                "surface": "Integrated Web Search",
                "search_url": "https://www.google.com/search?q=boundary+challenge+one",
                "opened_urls": [],
                "captured_at": "2026-11-08T12:00:00-05:00",
            },
            {
                "query": "verified item low value boundary challenge two",
                "strategy": "boundary synonym",
                "surface": "Integrated Web Search",
                "search_url": "https://www.google.com/search?q=boundary+challenge+two",
                "opened_urls": [],
                "captured_at": "2026-11-08T12:00:00-05:00",
            },
        ])
        item["pricing_comparables"] = []
        item["search_completion"] = {
            "stop_tier": 8,
            "stop_reason": "Eight attempts did not support pricing.",
            "staff_boundary_decision": True,
        }
        item["price_synthesis"] = {}
        item["pricing_confidence"] = "low"
        ledger["market_value_low"] = ""
        ledger["market_value_high"] = ""
        ledger["decision"] = "REVIEW"
        ledger["decision_rationale"] = "$40-$50 STAFF DECISION — insufficient direct prices."
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("must record the $40-$50 range", result.stderr)

    def test_included_prices_require_supported_range(self) -> None:
        research, ledger = self.stable_case()
        ledger["market_value_low"] = ""
        ledger["market_value_high"] = ""
        ledger["decision"] = "REVIEW"
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 2)
        self.assertIn("require a supported low and high range", result.stderr)

    def test_allows_three_consistent_prices_at_search_eight_with_boundary_buffer(self) -> None:
        research, ledger = self.stable_case()
        item = research["items"][0]
        item["search_attempts"].extend([
            {
                "query": "verified item price challenge seven",
                "strategy": "price challenge",
                "surface": "Integrated Web Search",
                "search_url": "https://www.google.com/search?q=price+challenge+seven",
                "opened_urls": [],
                "captured_at": "2026-11-08T12:00:00-05:00",
            },
            {
                "query": "verified item price challenge eight",
                "strategy": "price synonym",
                "surface": "Integrated Web Search",
                "search_url": "https://www.google.com/search?q=price+challenge+eight",
                "opened_urls": [],
                "captured_at": "2026-11-08T12:00:00-05:00",
            },
        ])
        item["search_completion"] = {"stop_tier": 8, "stop_reason": "Three consistent prices remain safely in the SELL band."}
        item["pricing_comparables"] = item["pricing_comparables"][:3]
        prices = [80, 85, 90]
        average = sum(prices) / len(prices)
        highest = max(prices)
        anchor = min(max((average + highest * 0.8) / 2, min(prices)), highest)
        item["price_synthesis"] = {
            "cleaned_average": average,
            "highest_cleaned_price": highest,
            "high_80": highest * 0.8,
            "anchor": anchor,
            "etsy_price": anchor * 0.95,
            "ebay_price": anchor * 1.05,
        }
        item["pricing_confidence"] = "medium"
        result = self.run_gate(research, ledger)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
