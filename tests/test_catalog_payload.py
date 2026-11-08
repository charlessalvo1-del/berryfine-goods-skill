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
            item = {"client_id": "client-a", "client_name": "Client A", "intake_id": "intake-a", "item_id": "item-a", "quantity": 1, "category": "Collectible", "identified_name": "Verified item", "identification_confidence": "confirmed", "identification_basis": "Visible model label", "visible_markings": "Model A", "condition_grade": "good", "condition_notes": "Light wear", "photo_refs": "IMG_1.jpg", "comp_count": 3, "comp_summary": "Three exact sold comparables", "comp_urls": ["https://example.com/sold-1", "https://example.com/sold-2", "https://example.com/sold-3"], "currency": "USD", "market_value_low": 70, "market_value_mid": 75, "market_value_high": 80, "decision_basis_value": 75, "valuation_basis": "sold_comparables", "valuation_confidence": "medium", "ebay_price": 79, "local_price": 70, "quick_sale_price": 60, "decision": "SELL", "decision_rationale": "Supported value meets the $50 threshold.", "donation_confirmation_status": "NOT_REQUIRED", "listing_status": "DRAFT", "human_review_status": "PENDING", "safety_status": "CLEAR", "research_date": "2026-08-02"}
            batch.write_text(json.dumps({"items": [item]}), encoding="utf-8")
            revisions = root / "item-revisions.jsonl"
            upsert = subprocess.run([sys.executable, str(SCRIPTS / "inventory_ledger.py"), "upsert", "--ledger", str(ledger), "--input", str(batch), "--audit-log", str(revisions)], text=True, capture_output=True)
            self.assertEqual(upsert.returncode, 0, upsert.stderr)
            self.assertIn('"operation": "CREATE"', revisions.read_text(encoding="utf-8"))
            research = root / "research.json"
            comps = [{"comp_id": f"c{number}", "title": "Verified item same model", "marketplace": "eBay", "source_url": f"https://example.com/sold-{number}", "transaction_status": "sold", "sale_date": f"2026-07-0{number}", "sold_price": price, "shipping": 0, "currency": "USD", "normalization_note": "USD sale; sold price plus displayed shipping.", "condition": "used", "comparability": "exact", "included": True, "include_reason": "same model", "evidence_method": "direct_transaction_page", "evidence_sha256": f"{number:064x}", "price_verified": True, "sale_date_verified": True, "quantity": 1, "lot_allocation_note": "Single-item transaction; no allocation required.", "captured_at": "2026-08-02T12:00:00-04:00"} for number, price in enumerate((70, 75, 80), 1)]
            attempts = [
                {"attempt_id": "a1", "query": "verified item maker", "strategy": "marking_exact", "surface": "Google", "search_url": "https://www.google.com/search?q=verified+item+maker", "result_count": 5, "result_count_basis": "observed", "result_urls": ["https://example.com/reference"], "opened_urls": ["https://example.com/reference"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:55:00-04:00"},
                {"attempt_id": "a2", "query": "verified item image", "strategy": "image_search", "surface": "Google Images", "search_url": "https://www.google.com/search?tbm=isch&q=verified+item", "result_count": 2, "result_count_basis": "observed", "result_urls": ["https://example.com/image"], "opened_urls": ["https://example.com/image"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:56:00-04:00"},
                {"attempt_id": "a3", "query": "verified item construction", "strategy": "candidate_confirmation", "surface": "Google", "search_url": "https://www.google.com/search?q=verified+item+construction", "result_count": 2, "result_count_basis": "observed", "result_urls": ["https://example.com/confirmation"], "opened_urls": ["https://example.com/confirmation"], "outcome": "candidate_found", "captured_at": "2026-08-02T11:57:00-04:00"},
                {"attempt_id": "a4", "query": "verified item sold", "strategy": "marketplace_sold", "surface": "Google completed sales", "search_url": "https://www.google.com/search?q=verified+item+sold", "result_count": 3, "result_count_basis": "observed", "result_urls": ["https://example.com/sold-1", "https://example.com/sold-2", "https://example.com/sold-3"], "opened_urls": ["https://example.com/sold-1", "https://example.com/sold-2", "https://example.com/sold-3"], "outcome": "comp_found", "captured_at": "2026-08-02T12:00:00-04:00"},
            ]
            research.write_text(json.dumps({"version": 2, "client_id": "client-a", "intake_id": "intake-a", "items": [{"item_id": "item-a", "search_attempts": attempts, "comparables": comps, "price_synthesis": {"method": "median", "comp_ids": ["c1", "c2", "c3"], "raw_median": 75, "adjusted_mid": 75, "adjustment_reason": ""}, "search_completion": {"status": "evidence_sufficient", "stop_reason": "Three exact completed transactions support the disposition."}}]}), encoding="utf-8")
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
            stale_verification = root / "stale-research-verification.json"
            stale_value = json.loads(verification.read_text(encoding="utf-8"))
            stale_value.pop("research_policy_version")
            stale_verification.write_text(json.dumps(stale_value), encoding="utf-8")
            stale = subprocess.run([sys.executable, str(SCRIPTS / "catalog_payload.py"), "--ledger", str(ledger), "--grouping", str(grouping), "--research-verification", str(stale_verification), "--intake-id", "intake-a", "--client-name", "Client A", "--output", str(root / "stale-payload.json")], text=True, capture_output=True)
            self.assertEqual(stale.returncode, 2)
            self.assertIn("policy version 2.6.0", stale.stderr)


if __name__ == "__main__":
    unittest.main()
