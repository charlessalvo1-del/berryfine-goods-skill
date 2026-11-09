import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "bfg.py"
sys.path.insert(0, str(SCRIPT.parent))

from bfg import summarize_dispositions


class BfgWorkflowTests(unittest.TestCase):
    def test_disposition_summary_reconciles_all_states(self) -> None:
        rows = [
            {"item_id": "1", "decision": "SELL", "human_review_status": "PENDING"},
            {"item_id": "2", "decision": "DONATE", "human_review_status": "PENDING"},
            {"item_id": "3", "decision": "DONATE", "human_review_status": "PENDING"},
            {"item_id": "4", "decision": "CONFIRM DONATION", "human_review_status": "PENDING"},
            {"item_id": "5", "decision": "REVIEW", "human_review_status": "PENDING"},
        ]
        self.assertEqual(
            summarize_dispositions(rows),
            {
                "total_items": 5,
                "sell": 1,
                "donate": 2,
                "confirm_donation": 1,
                "review": 1,
                "needs_owner_attention": 2,
                "human_review_pending": 5,
                "invalid_decision_count": 0,
                "duplicate_item_id_count": 0,
                "reconciled": True,
            },
        )

    def test_disposition_summary_fails_reconciliation_for_bad_rows(self) -> None:
        result = summarize_dispositions([
            {"item_id": "same", "decision": "SELL", "human_review_status": "PENDING"},
            {"item_id": "same", "decision": "WAIT", "human_review_status": "PENDING"},
        ])
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["invalid_decision_count"], 1)
        self.assertEqual(result["duplicate_item_id_count"], 1)

    def test_current_audit_contract_requires_research_policy_version(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn('REQUIRED_RESEARCH_POLICY_VERSION = "2.9.1-pilot"', text)
        self.assertIn('"STALE_RESEARCH_POLICY"', text)

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


if __name__ == "__main__":
    unittest.main()
