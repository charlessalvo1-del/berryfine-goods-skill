import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "berryfine-goods-skill" / "scripts"


class CatalogPayloadTests(unittest.TestCase):
    def test_builds_current_rows_and_empty_headed_exception_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); batch = root / "batch.json"; ledger = root / "ledger.csv"
            item = {"client_id": "client-a", "client_name": "Client A", "intake_id": "intake-a", "item_id": "item-a", "quantity": 1, "category": "Collectible", "identified_name": "Verified item", "identification_confidence": "confirmed", "identification_basis": "Visible model label", "condition_grade": "good", "condition_notes": "Light wear", "photo_refs": "IMG_1.jpg", "comp_count": 1, "comp_summary": "One exact sold comparable", "comp_urls": ["https://example.com/sold"], "currency": "USD", "market_value_low": 65, "market_value_mid": 75, "market_value_high": 85, "decision_basis_value": 75, "valuation_basis": "sold_comparables", "valuation_confidence": "medium", "ebay_price": 79, "local_price": 70, "quick_sale_price": 60, "decision": "SELL", "decision_rationale": "Supported value meets the $50 threshold.", "donation_confirmation_status": "NOT_REQUIRED", "listing_status": "DRAFT", "human_review_status": "PENDING", "safety_status": "CLEAR", "research_date": "2026-08-02"}
            batch.write_text(json.dumps({"items": [item]}), encoding="utf-8")
            revisions = root / "item-revisions.jsonl"
            upsert = subprocess.run([sys.executable, str(SCRIPTS / "inventory_ledger.py"), "upsert", "--ledger", str(ledger), "--input", str(batch), "--audit-log", str(revisions)], text=True, capture_output=True)
            self.assertEqual(upsert.returncode, 0, upsert.stderr)
            self.assertIn('"operation": "CREATE"', revisions.read_text(encoding="utf-8"))
            research = root / "research.json"
            comp = {"comp_id": "c1", "marketplace": "eBay", "source_url": "https://example.com/sold", "transaction_status": "sold", "sale_date": "2026-07-01", "sold_price": 70, "shipping": 5, "currency": "USD", "condition": "used", "comparability": "exact", "included": True, "include_reason": "same model", "captured_at": "2026-08-02T12:00:00-04:00"}
            research.write_text(json.dumps({"client_id": "client-a", "intake_id": "intake-a", "items": [{"item_id": "item-a", "comparables": [comp]}]}), encoding="utf-8")
            verification = root / "research-verification.json"
            gate = subprocess.run([sys.executable, str(SCRIPTS / "research_gate.py"), "--research", str(research), "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(verification)], text=True, capture_output=True)
            self.assertEqual(gate.returncode, 0, gate.stderr)
            grouping = root / "grouping.json"; grouping.write_text(json.dumps({"client_id": "client-a", "intake_id": "intake-a", "groups": [{"item_id": "item-a", "sku": "BB1", "group_id": "BB1 - Verified item"}]}), encoding="utf-8")
            output = root / "catalog-payload.json"
            build = subprocess.run([sys.executable, str(SCRIPTS / "catalog_payload.py"), "--ledger", str(ledger), "--grouping", str(grouping), "--research-verification", str(verification), "--intake-id", "intake-a", "--client-name", "Client A", "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["catalog_rows"][0]["location"], "Storage")
            self.assertEqual(payload["catalog_rows"][0]["recommended_action"], "SELL")
            self.assertEqual(payload["exceptions"], [])


if __name__ == "__main__":
    unittest.main()
