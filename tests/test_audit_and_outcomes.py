import json
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEAL = ROOT / "berryfine-goods-skill" / "scripts" / "audit_seal.py"
OUTCOMES = ROOT / "berryfine-goods-skill" / "scripts" / "outcome_ledger.py"


class AuditAndOutcomeTests(unittest.TestCase):
    def test_seal_detects_changed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); artifact = root / "manifest.json"; artifact.write_text("{}", encoding="utf-8"); seal = root / "seal.json"
            create = subprocess.run([sys.executable, str(SEAL), "create", "--root", str(root), "--client-id", "c", "--intake-id", "i", "--pipeline-version", "2.0.0", "--artifact", "manifest.json", "--output", str(seal)], text=True, capture_output=True)
            self.assertEqual(create.returncode, 0, create.stderr)
            artifact.write_text('{"changed":true}', encoding="utf-8")
            verify = subprocess.run([sys.executable, str(SEAL), "verify", "--seal", str(seal)], text=True, capture_output=True)
            self.assertEqual(verify.returncode, 2)
            self.assertIn("changed", verify.stderr)

    def test_outcome_chain_preserves_realized_sale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "outcomes.jsonl"; event = root / "event.json"
            event.write_text(json.dumps({"event_id": "e1", "client_id": "c", "item_id": "i", "event_type": "SOLD", "occurred_at": "2026-08-02T12:00:00-04:00", "recorded_by": "operator", "channel": "eBay", "sold_price": 75, "currency": "USD"}), encoding="utf-8")
            add = subprocess.run([sys.executable, str(OUTCOMES), "append", "--ledger", str(ledger), "--input", str(event)], text=True, capture_output=True)
            self.assertEqual(add.returncode, 0, add.stderr)
            check = subprocess.run([sys.executable, str(OUTCOMES), "verify", "--ledger", str(ledger)], text=True, capture_output=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_accuracy_report_measures_without_authorizing_small_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); outcomes = root / "outcomes.jsonl"; event = root / "event.json"; inventory = root / "inventory.csv"; output = root / "accuracy.json"
            row = {"intake_id": "i", "item_id": "item-1", "currency": "USD", "market_value_low": "60", "market_value_mid": "75", "market_value_high": "90"}
            with inventory.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            events = [
                {"event_id": "e1", "client_id": "c", "item_id": "item-1", "event_type": "IDENTIFICATION_CONFIRMED", "occurred_at": "2026-08-01T12:00:00-04:00", "recorded_by": "owner", "confirmed_identity": "Verified item", "verification_method": "maker label"},
                {"event_id": "e2", "client_id": "c", "item_id": "item-1", "event_type": "SOLD", "occurred_at": "2026-08-02T12:00:00-04:00", "recorded_by": "operator", "channel": "eBay", "sold_price": 80, "currency": "USD"},
            ]
            for value in events:
                event.write_text(json.dumps(value), encoding="utf-8")
                add = subprocess.run([sys.executable, str(OUTCOMES), "append", "--ledger", str(outcomes), "--input", str(event)], text=True, capture_output=True)
                self.assertEqual(add.returncode, 0, add.stderr)
            report = subprocess.run([sys.executable, str(OUTCOMES), "accuracy-report", "--outcomes", str(outcomes), "--inventory", str(inventory), "--intake-id", "i", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(report.returncode, 0, report.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["identification_accuracy_pct"], 100.0)
            self.assertEqual(value["price_range_coverage_pct"], 100.0)
            self.assertFalse(value["accuracy_claim_authorized"])


if __name__ == "__main__":
    unittest.main()
