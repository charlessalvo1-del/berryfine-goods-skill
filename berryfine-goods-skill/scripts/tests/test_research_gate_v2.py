import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from research_gate import gate  # noqa: E402


URL = "https://example.com/sold/fiesta-teapot"
STAMP = "2026-11-07T12:00:00-05:00"


def attempts(item_id, exhaustive=False):
    values = [
        {"attempt_id": f"{item_id}-a1", "query": "Fiesta Copco teapot", "strategy": "marking_exact", "surface": "Google", "search_url": "https://www.google.com/search?q=Fiesta+Copco+teapot", "result_count": 8, "result_urls": ["https://example.com/reference/fiesta"], "opened_urls": ["https://example.com/reference/fiesta"], "outcome": "candidate_found", "captured_at": STAMP},
        {"attempt_id": f"{item_id}-a2", "query": "Fiesta orange metal kettle", "strategy": "visual_attributes", "surface": "Google Images", "search_url": "https://www.google.com/search?tbm=isch&q=Fiesta+orange+metal+kettle", "result_count": 9, "result_urls": ["https://example.com/image/fiesta"], "opened_urls": ["https://example.com/image/fiesta"], "outcome": "candidate_found", "captured_at": STAMP},
    ]
    if exhaustive:
        values.extend([
            {"attempt_id": f"{item_id}-a3", "query": "Fiesta Copco teapot reverse image", "strategy": "image_search", "surface": "Google Images", "search_url": "https://www.google.com/search?tbm=isch&q=Fiesta+Copco+teapot", "result_count": 3, "result_urls": ["https://example.com/rejected/teapot"], "opened_urls": ["https://example.com/rejected/teapot"], "outcome": "rejected_mismatch", "captured_at": STAMP},
            {"attempt_id": f"{item_id}-a4", "query": "Fiesta Copco teapot sold", "strategy": "marketplace_sold", "surface": "eBay sold", "search_url": "https://www.ebay.com/sch/i.html?_nkw=Fiesta+Copco+teapot&LH_Sold=1", "result_count": 0, "result_urls": [], "opened_urls": [], "outcome": "no_useful_result", "captured_at": STAMP},
        ])
    return values


def comp(item_id, url=URL):
    return {
        "comp_id": f"{item_id}-c1", "title": "Fiesta Copco enamel metal teapot",
        "marketplace": "Example Auctions", "source_url": url,
        "transaction_status": "sold", "sale_date": "2026-10-01",
        "sold_price": 35, "shipping": 10, "currency": "USD",
        "condition": "used", "comparability": "near", "included": True,
        "include_reason": "Same maker, form, and material", "captured_at": STAMP,
    }


class ResearchGateV2Tests(unittest.TestCase):
    def run_gate(self, rows, items, challenge_review=None):
        temp_root = Path(os.environ.get("BFG_TEST_TMP", Path.cwd()))
        with tempfile.TemporaryDirectory(dir=temp_root) as temp:
            root = Path(temp)
            ledger = root / "ledger.csv"
            fields = ["intake_id", "item_id", "identified_name", "comp_count", "comp_urls", "valuation_basis", "valuation_confidence", "decision"]
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

    def test_supported_item_passes(self):
        row = {"intake_id": "test-intake", "item_id": "I1", "identified_name": "Fiesta Copco teapot", "comp_count": 1, "comp_urls": URL, "valuation_basis": "completed_sales", "valuation_confidence": "high", "decision": "SELL"}
        result = self.run_gate([row], [{"item_id": "I1", "search_attempts": attempts("I1"), "comparables": [comp("I1")]}])
        self.assertEqual("PASS", result["status"])

    def test_unsearched_zero_comp_review_fails(self):
        row = {"intake_id": "test-intake", "item_id": "I1", "identified_name": "Fiesta Copco teapot", "comp_count": 0, "comp_urls": "", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low", "decision": "REVIEW"}
        result = self.run_gate([row], [{"item_id": "I1", "search_attempts": attempts("I1"), "comparables": []}])
        codes = {entry["code"] for entry in result["blockers"]}
        self.assertIn("SEARCH_NOT_EXHAUSTED", codes)
        self.assertIn("MISSING_EXHAUSTION_RECORD", codes)

    def test_exhausted_zero_comp_review_passes(self):
        row = {"intake_id": "test-intake", "item_id": "I1", "identified_name": "Fiesta Copco teapot", "comp_count": 0, "comp_urls": "", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low", "decision": "REVIEW"}
        exhaustion = {"reason_code": "no_completed_sales", "summary": "Identity confirmed but no verifiable completed sale found.", "next_evidence": "Check subscription auction archive.", "closest_candidate_urls": ["https://example.com/active/fiesta"], "candidate_identifications_considered": ["Fiesta Copco teapot"]}
        item = {"item_id": "I1", "search_attempts": attempts("I1", exhaustive=True), "comparables": [], "exhaustion": exhaustion}
        self.assertEqual("PASS", self.run_gate([row], [item])["status"])

    def test_all_zero_search_results_block_catalog(self):
        row = {"intake_id": "test-intake", "item_id": "I1", "identified_name": "Fiesta Copco teapot", "comp_count": 0, "comp_urls": "", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low", "decision": "REVIEW"}
        zero_attempts = attempts("I1", exhaustive=True)
        for attempt in zero_attempts:
            attempt.update(result_count=0, result_urls=[], opened_urls=[], outcome="no_useful_result")
        exhaustion = {"reason_code": "no_candidates", "summary": "No result was returned by any attempted query.", "next_evidence": "Diagnose search access and revise the search vocabulary.", "closest_candidate_urls": [], "candidate_identifications_considered": []}
        item = {"item_id": "I1", "search_attempts": zero_attempts, "comparables": [], "exhaustion": exhaustion}
        result = self.run_gate([row], [item])
        self.assertIn("NO_SEARCH_RESULTS", {entry["code"] for entry in result["blockers"]})

    def test_all_documented_exhaustion_reasons_pass(self):
        reasons = ["no_candidates", "no_completed_sales", "conflicting_identity", "inaccessible_sold_data", "insufficient_photo_detail"]
        for reason in reasons:
            with self.subTest(reason=reason):
                row = {"intake_id": "test-intake", "item_id": "I1", "identified_name": "Fiesta Copco teapot", "comp_count": 0, "comp_urls": "", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low", "decision": "REVIEW"}
                exhaustion = {"reason_code": reason, "summary": "Required research was completed without usable valuation evidence.", "next_evidence": "Obtain a clearer mark or an accessible sold archive.", "closest_candidate_urls": [], "candidate_identifications_considered": []}
                item = {"item_id": "I1", "search_attempts": attempts("I1", exhaustive=True), "comparables": [], "exhaustion": exhaustion}
                self.assertEqual("PASS", self.run_gate([row], [item])["status"])

    def test_reused_comp_url_across_four_items_fails(self):
        rows = []
        items = []
        for number in range(1, 5):
            item_id = f"I{number}"
            rows.append({"intake_id": "test-intake", "item_id": item_id, "identified_name": "Fiesta Copco teapot", "comp_count": 1, "comp_urls": URL, "valuation_basis": "completed_sales", "valuation_confidence": "medium", "decision": "SELL"})
            items.append({"item_id": item_id, "search_attempts": attempts(item_id), "comparables": [comp(item_id)]})
        result = self.run_gate(rows, items)
        self.assertEqual(4, sum(entry["code"] == "OVERUSED_COMPARABLE" for entry in result["blockers"]))

    def test_ten_zero_comp_items_require_integrated_challenge(self):
        rows = []
        items = []
        for number in range(1, 11):
            item_id = f"I{number}"
            rows.append({"intake_id": "test-intake", "item_id": item_id, "identified_name": "Fiesta Copco teapot", "comp_count": 0, "comp_urls": "", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low", "decision": "REVIEW"})
            exhaustion = {"reason_code": "no_completed_sales", "summary": "No verifiable completed sale found.", "next_evidence": "Obtain an accessible sold archive.", "closest_candidate_urls": ["https://example.com/active/fiesta"], "candidate_identifications_considered": ["Fiesta Copco teapot"]}
            items.append({"item_id": item_id, "search_attempts": attempts(item_id, exhaustive=True), "comparables": [], "exhaustion": exhaustion})
        missing = self.run_gate(rows, items)
        self.assertIn("MISSING_CHALLENGE_REVIEW", {entry["code"] for entry in missing["blockers"]})
        challenge = {
            "review_run_id": "challenge-1", "created_at": STAMP,
            "reviewer": "independent test context", "independent_context": True,
            "sampled_item_ids": [f"I{number}" for number in range(1, 11)],
            "findings": [
                {"item_id": f"I{number}", "outcome": "confirmed_exhaustion", "opened_urls": ["https://example.com/challenge"], "summary": "Opened challenge evidence did not establish a completed sale."}
                for number in range(1, 11)
            ],
            "corrections_integrated": True,
        }
        self.assertEqual("PASS", self.run_gate(rows, items, challenge)["status"])


if __name__ == "__main__":
    unittest.main()
