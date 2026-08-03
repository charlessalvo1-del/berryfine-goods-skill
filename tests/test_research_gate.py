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
        row = {"intake_id": "intake-a", "item_id": "item-a", "comp_count": "1", "comp_urls": "https://example.com/sold", "valuation_basis": "sold_comparables", "valuation_confidence": "medium", "decision": "SELL", "decision_basis_value": "75"}
        row.update(overrides)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)

    def research(self, comps: list[dict]) -> dict:
        return {"version": 1, "client_id": "c", "intake_id": "intake-a", "items": [{"item_id": "item-a", "comparables": comps}]}

    def comp(self) -> dict:
        return {"comp_id": "c1", "marketplace": "eBay", "source_url": "https://example.com/sold", "transaction_status": "sold", "sale_date": "2026-07-01", "sold_price": 70, "shipping": 5, "currency": "USD", "condition": "used", "comparability": "exact", "included": True, "include_reason": "same model", "captured_at": "2026-08-02T12:00:00-04:00"}

    def test_passes_reconciled_structured_comparable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "ledger.csv"; research = root / "research.json"; output = root / "result.json"
            self.write_ledger(ledger); research.write_text(json.dumps(self.research([self.comp()])), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--research", str(research), "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_unsupported_donation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "ledger.csv"; research = root / "research.json"; output = root / "result.json"
            self.write_ledger(ledger, comp_count="0", comp_urls="", valuation_basis="insufficient_evidence", valuation_confidence="low", decision="DONATE", decision_basis_value="25")
            research.write_text(json.dumps(self.research([])), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--research", str(research), "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("UNSUPPORTED_DISPOSITION", result.stderr)


if __name__ == "__main__":
    unittest.main()
