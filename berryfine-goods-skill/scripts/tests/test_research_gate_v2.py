import csv
import json
import os
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from research_gate import gate  # noqa: E402


STAMP = "2026-11-07T12:00:00-05:00"


def comp(item_id, number, price, url=None, currency="USD"):
    return {
        "comp_id": f"{item_id}-c{number}",
        "title": f"Fiesta Copco enamel metal teapot sold comp {number}",
        "marketplace": "Example Auctions",
        "source_url": url or f"https://example.com/sold/{item_id}-{number}",
        "transaction_status": "sold",
        "sale_date": f"2026-10-{number:02d}",
        "sold_price": price,
        "shipping": 0,
        "currency": currency,
        "condition": "used",
        "comparability": "near",
        "included": True,
        "include_reason": "Same maker, form, material, and similar condition",
        "captured_at": STAMP,
    }


def comp_set(item_id, prices=(70, 80, 90), shared_url=None):
    return [
        comp(item_id, number, price, url=shared_url if number == 1 else None)
        for number, price in enumerate(prices, 1)
    ]


def attempts(item_id, sold_urls=None):
    sold_urls = sold_urls or [f"https://example.com/rejected/{item_id}-sold-candidate"]
    return [
        {"attempt_id": f"{item_id}-a1", "query": "Fiesta Copco teapot maker mark", "strategy": "marking_exact", "surface": "Google web search", "search_url": "https://www.google.com/search?q=Fiesta+Copco+teapot+mark", "result_count": 1, "result_urls": [f"https://example.com/reference/{item_id}"], "opened_urls": [f"https://example.com/reference/{item_id}"], "outcome": "candidate_found", "captured_at": STAMP},
        {"attempt_id": f"{item_id}-a2", "query": "orange metal teapot ring handle image", "strategy": "image_search", "surface": "Google Images", "search_url": "https://www.google.com/search?tbm=isch&q=orange+metal+teapot", "result_count": 1, "result_urls": [f"https://example.com/image/{item_id}"], "opened_urls": [f"https://example.com/image/{item_id}"], "outcome": "candidate_found", "captured_at": STAMP},
        {"attempt_id": f"{item_id}-a3", "query": "Fiesta Copco teapot construction confirmation", "strategy": "candidate_confirmation", "surface": "Google web search", "search_url": "https://www.google.com/search?q=Fiesta+Copco+construction", "result_count": 1, "result_urls": [f"https://example.com/confirm/{item_id}"], "opened_urls": [f"https://example.com/confirm/{item_id}"], "outcome": "candidate_found", "captured_at": STAMP},
        {"attempt_id": f"{item_id}-a4", "query": "Fiesta Copco teapot sold completed", "strategy": "marketplace_sold", "surface": "Google completed-sale and auction search", "search_url": "https://www.google.com/search?q=Fiesta+Copco+teapot+sold", "result_count": len(sold_urls), "result_urls": sold_urls, "opened_urls": sold_urls, "outcome": "comp_found", "captured_at": STAMP},
    ]


def synthesis(comps, adjusted=None, reason=""):
    median = statistics.median(value["sold_price"] + value["shipping"] for value in comps)
    adjusted = median if adjusted is None else adjusted
    return {
        "method": "median",
        "comp_ids": [value["comp_id"] for value in comps],
        "raw_median": median,
        "adjusted_mid": adjusted,
        "adjustment_reason": reason,
    }


def ledger_row(item_id, comps=(), decision="REVIEW", low=0, mid=0, high=0, confidence="low"):
    return {
        "intake_id": "test-intake", "item_id": item_id,
        "identified_name": "Fiesta Copco teapot", "visible_markings": "Fiesta Copco",
        "comp_count": str(len(comps)), "comp_urls": ";".join(value["source_url"] for value in comps),
        "valuation_basis": "completed_sales" if comps else "insufficient_evidence",
        "valuation_confidence": confidence, "decision": decision,
        "market_value_low": str(low), "market_value_mid": str(mid),
        "market_value_high": str(high), "decision_basis_value": str(mid),
    }


def research_item(item_id, comps=(), exhaustion=None, price_synthesis=None, search_attempts=None):
    value = {
        "item_id": item_id,
        "search_attempts": search_attempts if search_attempts is not None else attempts(item_id, [comp["source_url"] for comp in comps] or None),
        "comparables": list(comps),
    }
    if exhaustion is not None:
        value["exhaustion"] = exhaustion
    if price_synthesis is not None:
        value["price_synthesis"] = price_synthesis
    return value


def exhaustion(item_id):
    return {
        "reason_code": "no_completed_sales",
        "summary": f"Four direct research pages did not establish three comparable completed sales for {item_id}.",
        "next_evidence": f"Obtain a clearer mark or additional sold archive evidence for {item_id}.",
        "closest_candidate_urls": [f"https://example.com/reference/{item_id}"],
        "candidate_identifications_considered": ["Fiesta Copco teapot"],
    }


class ResearchGateV2Tests(unittest.TestCase):
    def run_gate(self, rows, items, challenge_review=None):
        temp_root = Path(os.environ.get("BFG_TEST_TMP", Path.cwd()))
        with tempfile.TemporaryDirectory(dir=temp_root) as temp:
            root = Path(temp)
            ledger = root / "ledger.csv"
            fields = ["intake_id", "item_id", "identified_name", "visible_markings", "comp_count", "comp_urls", "valuation_basis", "valuation_confidence", "decision", "market_value_low", "market_value_mid", "market_value_high", "decision_basis_value"]
            with ledger.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            research = root / "research.json"
            payload = {"version": 2, "client_id": "RON", "intake_id": "test-intake", "items": items}
            if challenge_review is not None:
                payload["challenge_review"] = challenge_review
            research.write_text(json.dumps(payload), encoding="utf-8")
            return gate(research, ledger, "test-intake")

    def test_three_independent_sales_and_median_pass(self):
        comps = comp_set("I1")
        result = self.run_gate(
            [ledger_row("I1", comps, "SELL", 70, 80, 90, "high")],
            [research_item("I1", comps, price_synthesis=synthesis(comps))],
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(80, result["findings"][0]["normalized_total_median"])

    def test_one_comp_cannot_authorize_disposition(self):
        comps = comp_set("I1", (80,))
        result = self.run_gate(
            [ledger_row("I1", comps, "SELL", 70, 80, 90, "medium")],
            [research_item("I1", comps, price_synthesis=synthesis(comps))],
        )
        self.assertIn("INSUFFICIENT_COMPLETED_COMPS", {entry["code"] for entry in result["blockers"]})

    def test_reopening_one_page_does_not_count_as_four_reviews(self):
        comps = comp_set("I1")
        repeated = "https://example.com/sold/repeated"
        shallow = attempts("I1", [repeated])
        for attempt in shallow:
            attempt.update(result_count=1, result_urls=[repeated], opened_urls=[repeated])
        result = self.run_gate(
            [ledger_row("I1", comps, "SELL", 70, 80, 90, "high")],
            [research_item("I1", comps, price_synthesis=synthesis(comps), search_attempts=shallow)],
        )
        self.assertIn("SHALLOW_RESEARCH", {entry["code"] for entry in result["blockers"]})

    def test_donate_range_must_stay_below_forty(self):
        comps = comp_set("I1", (30, 35, 45, 32, 38))
        result = self.run_gate(
            [ledger_row("I1", comps, "DONATE", 30, 35, 45, "high")],
            [research_item("I1", comps, price_synthesis=synthesis(comps))],
        )
        self.assertIn("RANGE_CROSSES_DISPOSITION_BOUNDARY", {entry["code"] for entry in result["blockers"]})

    def test_borderline_value_requires_five_sales(self):
        comps = comp_set("I1", (30, 34, 38))
        result = self.run_gate(
            [ledger_row("I1", comps, "DONATE", 30, 34, 38, "high")],
            [research_item("I1", comps, price_synthesis=synthesis(comps))],
        )
        self.assertIn("BORDERLINE_RESEARCH_TOO_SHALLOW", {entry["code"] for entry in result["blockers"]})

    def test_bad_median_synthesis_fails(self):
        comps = comp_set("I1")
        bad = synthesis(comps)
        bad["raw_median"] = 999
        result = self.run_gate(
            [ledger_row("I1", comps, "SELL", 70, 80, 90, "high")],
            [research_item("I1", comps, price_synthesis=bad)],
        )
        self.assertIn("INVALID_PRICE_SYNTHESIS", {entry["code"] for entry in result["blockers"]})

    def test_foreign_currency_requires_usd_normalization(self):
        comps = comp_set("I1")
        comps[1]["currency"] = "CAD"
        result = self.run_gate(
            [ledger_row("I1", comps, "SELL", 70, 80, 90, "high")],
            [research_item("I1", comps, price_synthesis=synthesis(comps))],
        )
        self.assertIn("UNNORMALIZED_CURRENCY", {entry["code"] for entry in result["blockers"]})

    def test_zero_comp_review_requires_exhaustion(self):
        result = self.run_gate(
            [ledger_row("I1")],
            [research_item("I1", search_attempts=attempts("I1")[:2])],
        )
        codes = {entry["code"] for entry in result["blockers"]}
        self.assertIn("INSUFFICIENT_SEARCH_COVERAGE", codes)
        self.assertIn("MISSING_EXHAUSTION_RECORD", codes)

    def test_exhausted_zero_comp_review_passes(self):
        self.assertEqual(
            "PASS",
            self.run_gate([ledger_row("I1")], [research_item("I1", exhaustion=exhaustion("I1"))])["status"],
        )

    def test_all_zero_search_results_block_catalog(self):
        values = attempts("I1")
        for attempt in values:
            attempt.update(result_count=0, result_urls=[], opened_urls=[], outcome="no_useful_result")
        result = self.run_gate(
            [ledger_row("I1")],
            [research_item("I1", exhaustion=exhaustion("I1"), search_attempts=values)],
        )
        self.assertIn("NO_SEARCH_RESULTS", {entry["code"] for entry in result["blockers"]})

    def test_category_page_is_not_direct_evidence(self):
        values = attempts("I1")
        category = "https://www.ebay.com/b/otagiri-tea-set/bn_7024844841"
        values[-1].update(result_count=1, result_urls=[category], opened_urls=[category])
        result = self.run_gate(
            [ledger_row("I1")],
            [research_item("I1", exhaustion=exhaustion("I1"), search_attempts=values)],
        )
        self.assertIn("SHALLOW_RESEARCH", {entry["code"] for entry in result["blockers"]})

    def test_placeholder_visible_markings_fail(self):
        comps = comp_set("I1")
        row = ledger_row("I1", comps, "SELL", 70, 80, 90, "high")
        row["visible_markings"] = "Visible photographed form, decoration, materials and any legible product wording used; no hidden mark was inferred."
        result = self.run_gate([row], [research_item("I1", comps, price_synthesis=synthesis(comps))])
        self.assertIn("PLACEHOLDER_VISIBLE_MARKINGS", {entry["code"] for entry in result["blockers"]})

    def test_reused_comp_url_across_four_items_fails(self):
        shared = "https://example.com/sold/shared"
        rows, items = [], []
        for number in range(1, 5):
            item_id = f"I{number}"
            comps = comp_set(item_id, shared_url=shared)
            rows.append(ledger_row(item_id, comps, "SELL", 70, 80, 90, "high"))
            items.append(research_item(item_id, comps, price_synthesis=synthesis(comps)))
        result = self.run_gate(rows, items)
        self.assertEqual(4, sum(entry["code"] == "OVERUSED_COMPARABLE" for entry in result["blockers"]))

    def test_ten_zero_comp_items_require_full_challenge(self):
        rows, items = [], []
        for number in range(1, 11):
            item_id = f"I{number}"
            rows.append(ledger_row(item_id))
            items.append(research_item(item_id, exhaustion=exhaustion(item_id)))
        missing = self.run_gate(rows, items)
        self.assertIn("MISSING_CHALLENGE_REVIEW", {entry["code"] for entry in missing["blockers"]})
        challenge = {
            "review_run_id": "challenge-1", "created_at": STAMP,
            "reviewer": "independent test context", "independent_context": True,
            "first_pass_zero_comp_item_ids": [f"I{number}" for number in range(1, 11)],
            "sampled_item_ids": [f"I{number}" for number in range(1, 11)],
            "findings": [
                {"item_id": f"I{number}", "outcome": "confirmed_exhaustion", "opened_urls": [f"https://example.com/challenge/I{number}"], "summary": "Direct challenge evidence did not establish a completed sale."}
                for number in range(1, 11)
            ],
            "corrections_integrated": True,
            "expanded_to_all_first_pass_zero_comp": True,
        }
        self.assertEqual("PASS", self.run_gate(rows, items, challenge)["status"])


if __name__ == "__main__":
    unittest.main()
