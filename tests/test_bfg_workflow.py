import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "bfg.py"


class BfgWorkflowTests(unittest.TestCase):
    def test_help_describes_workflow_specific_completion_sequence(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delivery_gate.py --workflow full-intake", result.stdout)
        self.assertIn("bfg.py audit", result.stdout)
        self.assertIn("bfg.py legacy-audit", result.stdout)
        self.assertIn("Audit does not replace delivery", result.stdout)

    def test_legacy_audit_reproduces_regression_failure_classes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"; ledger = root / "ledger.csv"; catalog = root / "client" / "Client New Catalog.xlsx"; exceptions = root / "client" / "Prior Run" / "Client Exceptions.xlsx"
            catalog.parent.mkdir(); exceptions.parent.mkdir(); catalog.write_bytes(b"x"); exceptions.write_bytes(b"x")
            manifest.write_text(json.dumps({"photos": [{"sequence": 1}], "groups": []}), encoding="utf-8")
            row = {"intake_id": "legacy-regression", "item_id": "item-1", "decision_basis_value": "45", "decision": "DONATE", "valuation_basis": "insufficient_evidence", "valuation_confidence": "low"}
            with ledger.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            result = subprocess.run([sys.executable, str(SCRIPT), "legacy-audit", "--manifest", str(manifest), "--preflight", str(root / "missing-lock.json"), "--ledger", str(ledger), "--intake-id", "legacy-regression", "--catalog", str(catalog), "--exceptions", str(exceptions)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            for code in ("PHOTO_HASHES_MISSING", "PREFLIGHT_MISSING", "GROUPING_NOT_BOUND", "BORDERLINE_POLICY_VIOLATION", "UNSUPPORTED_DISPOSITION", "SPLIT_DELIVERY_LOCATION"):
                self.assertIn(code, result.stdout)

    def test_legacy_audit_rejects_existing_but_unconfirmed_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            ledger = root / "ledger.csv"
            preflight = root / "preflight-lock.json"
            client = root / "client"
            client.mkdir()
            catalog = client / "Client New Catalog.xlsx"
            exceptions = client / "Client Exceptions.xlsx"
            catalog.write_bytes(b"x")
            exceptions.write_bytes(b"x")
            manifest.write_text(json.dumps({"photos": [{"sha256": "a" * 64}], "grouping_binding": "bound"}), encoding="utf-8")
            preflight.write_text(json.dumps({"status": "PENDING"}), encoding="utf-8")
            row = {"intake_id": "legacy-refresh", "item_id": "item-1", "decision_basis_value": "60", "decision": "SELL", "valuation_basis": "completed_sales", "valuation_confidence": "high"}
            with ledger.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            result = subprocess.run([sys.executable, str(SCRIPT), "legacy-audit", "--manifest", str(manifest), "--preflight", str(preflight), "--ledger", str(ledger), "--intake-id", "legacy-refresh", "--catalog", str(catalog), "--exceptions", str(exceptions)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("PREFLIGHT_NOT_CONFIRMED", result.stdout)


if __name__ == "__main__":
    unittest.main()
