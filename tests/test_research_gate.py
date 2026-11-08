import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "research_gate.py"


class ResearchGateTests(unittest.TestCase):
    def write_ledger(self, path: Path, **overrides: str) -> None:
        row = {"intake_id": "intake-a", "item_id": "item-a", "identified_name": "Verified item", "visible_markings": "Model A", "comp_count": "3", "comp_urls": "https://example.com/sold-1;https://example.com/sold-2;https://example.com/sold-3", "valuation_basis": "sold_comparables", "valuation_confidence": "medium", "decision": "SELL", "market_value_low": "70", "market_value_mid": "75", "market_value_high": "80", "decision_basis_value": "75"}
        row.update(overrides)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)

    def research(self, comps: list[dict]) -> dict:
        attempts = [
            {"attempt_id": "a1", "query": "verified item maker", "strategy": "marking_exact", "surface": "Google", "search_url": "https://www.google.com/search?q=verified+item+maker", "result_count": 5, "result_urls": ["https://example.com/reference"], "opened_urls": ["https://example.com/reference"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:55:00-04:00"},
            {"attempt_id": "a2", "query": "verified item image", "strategy": "image_search", "surface": "Google Images", "search_url": "https://www.google.com/search?tbm=isch&q=verified+item", "result_count": 2, "result_urls": ["https://example.com/image"], "opened_urls": ["https://example.com/image"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:56:00-04:00"},
            {"attempt_id": "a3", "query": "verified item construction", "strategy": "candidate_confirmation", "surface": "Google", "search_url": "https://www.google.com/search?q=verified+item+construction", "result_count": 2, "result_urls": ["https://example.com/confirmation"], "opened_urls": ["https://example.com/confirmation"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:57:00-04:00"},
            {"attempt_id": "a4", "query": "verified item sold", "strategy": "marketplace_sold", "surface": "Google completed sales", "search_url": "https://www.google.com/search?q=verified+item+sold", "result_count": 3, "result_urls": ["https://example.com/sold-1", "https://example.com/sold-2", "https://example.com/sold-3"], "opened_urls": ["https://example.com/sold-1", "https://example.com/sold-2", "https://example.com/sold-3"], "outcome": "comp_found", "captured_at": "2026-08-02T12:00:00-04:00"},
        ]
        synthesis = {"method": "median", "comp_ids": [comp["comp_id"] for comp in comps], "raw_median": 75, "adjusted_mid": 75, "adjustment_reason": ""}
        return {"version": 2, "client_id": "c", "intake_id": "intake-a", "items": [{"item_id": "item-a", "search_attempts": attempts, "comparables": comps, "price_synthesis": synthesis}]}

    def comps(self) -> list[dict]:
        return [
            {"comp_id": f"c{number}", "title": "Verified item same model", "marketplace": "eBay", "source_url": f"https://example.com/sold-{number}", "transaction_status": "sold", "sale_date": f"2026-07-0{number}", "sold_price": price, "shipping": 0, "currency": "USD", "condition": "used", "comparability": "exact", "included": True, "include_reason": "same model", "captured_at": "2026-08-02T12:00:00-04:00"}
            for number, price in enumerate((70, 75, 80), 1)
        ]

    def test_passes_reconciled_structured_comparable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "ledger.csv"; research = root / "research.json"; output = root / "result.json"
            self.write_ledger(ledger); research.write_text(json.dumps(self.research(self.comps())), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--research", str(research), "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_unsupported_donation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "ledger.csv"; research = root / "research.json"; output = root / "result.json"
            self.write_ledger(ledger, comp_count="0", comp_urls="", valuation_basis="insufficient_evidence", valuation_confidence="low", decision="DONATE", market_value_low="15", market_value_mid="25", market_value_high="35", decision_basis_value="25")
            research.write_text(json.dumps(self.research([])), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--research", str(research), "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("UNSUPPORTED_DISPOSITION", result.stderr)


if __name__ == "__main__":
    unittest.main()
