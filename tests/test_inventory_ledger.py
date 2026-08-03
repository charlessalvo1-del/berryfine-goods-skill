import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "inventory_ledger.py"


def item(item_id: str, *, client_id: str = "client-a", decision: str = "SELL") -> dict:
    row = {
        "client_id": client_id,
        "client_name": "Example",
        "intake_id": "intake-a",
        "item_id": item_id,
        "project_id": "project-a",
        "quantity": 1,
        "category": "Small appliance",
        "identified_name": "Example mixer",
        "identification_confidence": "probable",
        "identification_basis": "Label and housing match",
        "condition_grade": "good",
        "condition_notes": "Used; powers on",
        "photo_refs": ["front.jpg", "label.jpg"],
        "storage_location": "Unit 1 / Rack A",
        "dimensions": "12 x 8 x 6 in",
        "materials": "Metal and glass",
        "comp_count": 3,
        "comp_summary": "Three comparable completed sales",
        "currency": "USD",
        "market_value_low": 60,
        "market_value_mid": 75,
        "market_value_high": 90,
        "decision_basis_value": 75,
        "valuation_basis": "sold_comparables",
        "valuation_confidence": "medium",
        "comp_urls": ["https://example.com/sold-item"],
        "decision": decision,
        "decision_rationale": "Supported value is above the default threshold",
        "donation_confirmation_status": "NOT_REQUIRED",
        "listing_status": "READY",
        "listing_title": "Example Mixer Tested",
        "listing_description": "Used mixer; see condition notes.",
        "ebay_price": 84.99,
        "human_review_status": "APPROVED",
        "approved_by": "test-reviewer",
        "approved_at": "2026-07-26T12:00:00-04:00",
        "safety_status": "CLEAR",
        "research_date": "2026-07-26",
    }
    if decision == "DONATE":
        row.update(
            market_value_low=10,
            market_value_mid=20,
            market_value_high=30,
            decision_basis_value=20,
            listing_status="DO_NOT_LIST",
            listing_title="",
            listing_description="",
            ebay_price="",
        )
    return row


class InventoryLedgerTests(unittest.TestCase):
    def run_script(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_upsert_update_and_listing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            ledger = temp / "inventory.csv"
            batch = temp / "batch.json"
            queue = temp / "queue.csv"

            batch.write_text(
                json.dumps({"client_id": "client-a", "items": [item("a-001")]}),
                encoding="utf-8",
            )
            created = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(created.returncode, 0, created.stderr)

            updated_item = item("a-001")
            updated_item["market_value_mid"] = 80
            draft_item = item("a-003")
            draft_item.update(
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(
                json.dumps(
                    [updated_item, item("a-002", decision="DONATE"), draft_item]
                )
            )
            updated = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(updated.returncode, 0, updated.stderr)

            with ledger.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["market_value_mid"], "80")
            self.assertEqual(rows[0]["photo_refs"], "front.jpg;label.jpg")

            exported = self.run_script(
                "listing-queue", "--ledger", ledger, "--output", queue
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            with queue.open(encoding="utf-8-sig", newline="") as handle:
                queue_rows = list(csv.DictReader(handle))
            self.assertEqual([row["item_id"] for row in queue_rows], ["a-001"])

    def test_rejects_cross_client_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            ledger = temp / "inventory.csv"
            batch = temp / "batch.json"
            batch.write_text(json.dumps([item("a-001")]), encoding="utf-8")
            self.assertEqual(
                self.run_script("upsert", "--ledger", ledger, "--input", batch).returncode,
                0,
            )
            batch.write_text(
                json.dumps([item("b-001", client_id="client-b")]), encoding="utf-8"
            )
            result = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cross-client merge rejected", result.stderr)

    def test_ready_requires_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            unsafe = item("a-001")
            unsafe["human_review_status"] = "PENDING"
            unsafe["approved_by"] = ""
            unsafe["approved_at"] = ""
            batch.write_text(json.dumps([unsafe]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("human_review_status APPROVED", result.stderr)

    def test_sell_below_threshold_requires_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            low_value = item("a-001")
            low_value.update(
                market_value_low=20,
                market_value_mid=30,
                market_value_high=40,
                decision_basis_value=30,
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(json.dumps([low_value]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires decision_override_reason", result.stderr)

    def test_donate_at_forty_dollars_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            borderline = item("a-001", decision="DONATE")
            borderline.update(
                market_value_low=35,
                market_value_mid=45,
                market_value_high=49,
                decision_basis_value=45,
            )
            batch.write_text(json.dumps([borderline]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("donation_confirmation_status CONFIRMED", result.stderr)

    def test_forty_dollar_band_requires_confirm_donation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            borderline = item("a-001")
            borderline.update(
                market_value_low=35,
                market_value_mid=45,
                market_value_high=49,
                decision_basis_value=45,
                decision="CONFIRM DONATION",
                decision_rationale="Borderline value requires review.",
                donation_confirmation_status="PENDING",
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(json.dumps([borderline]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Confirm this item will not be sold", result.stderr)

            borderline["decision_rationale"] = (
                "Confirm this item will not be sold before donation or rehoming."
            )
            batch.write_text(json.dumps([borderline]), encoding="utf-8")
            accepted = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_sell_in_forty_dollar_band_requires_declined_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            borderline = item("a-001")
            borderline.update(
                market_value_low=35,
                market_value_mid=45,
                market_value_high=49,
                decision_basis_value=45,
                decision_override_reason="Potential collector interest",
                donation_confirmation_status="NOT_REQUIRED",
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(json.dumps([borderline]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("donation_confirmation_status DECLINED", result.stderr)

            borderline.update(
                donation_confirmation_status="DECLINED",
                donation_confirmed_by="BFG reviewer",
                donation_confirmed_at="2026-08-02T10:00:00-04:00",
            )
            batch.write_text(json.dumps([borderline]), encoding="utf-8")
            accepted = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_confirmed_forty_dollar_item_can_transition_to_donate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            confirmed = item("a-001", decision="DONATE")
            confirmed.update(
                market_value_low=40,
                market_value_mid=45,
                market_value_high=49,
                decision_basis_value=45,
                donation_confirmation_status="CONFIRMED",
                donation_confirmed_by="BFG reviewer",
                donation_confirmed_at="2026-08-02T10:00:00-04:00",
                listing_status="DO_NOT_LIST",
            )
            batch.write_text(json.dumps([confirmed]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_in_band_requires_independent_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            uncertain = item("a-001")
            uncertain.update(
                market_value_low=35,
                market_value_mid=45,
                market_value_high=49,
                decision_basis_value=45,
                decision="REVIEW",
                donation_confirmation_status="NOT_REQUIRED",
                valuation_confidence="low",
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(json.dumps([uncertain]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_forty_dollar_donate_row_is_grandfathered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            ledger = temp / "inventory.csv"
            batch = temp / "batch.json"
            batch.write_text(
                json.dumps([item("a-001", decision="DONATE")]), encoding="utf-8"
            )
            created = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(created.returncode, 0, created.stderr)

            with ledger.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            rows[0].update(
                market_value_low="35",
                market_value_mid="45",
                market_value_high="49",
                decision_basis_value="45",
            )
            with ledger.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            batch.write_text(json.dumps([item("a-002")]), encoding="utf-8")
            updated = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(updated.returncode, 0, updated.stderr)

    def test_rejects_spreadsheet_formula_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            unsafe = item("a-001")
            unsafe["notes"] = "=HYPERLINK(\"https://example.com\")"
            batch.write_text(json.dumps([unsafe]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("spreadsheet formula prefix", result.stderr)

    def test_planned_testing_uses_working_value_without_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            planned = item("a-001")
            planned.update(
                testing_status="PLANNED",
                value_if_tested_working=75,
                value_if_untested=40,
                testing_notes="Tested-working value $75; untested value $40; difference $35.",
                listing_status="DRAFT",
                human_review_status="PENDING",
                approved_by="",
                approved_at="",
            )
            batch.write_text(json.dumps([planned]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_planned_testing_rejects_ready_listing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            planned = item("a-001")
            planned.update(
                testing_status="PLANNED",
                value_if_tested_working=75,
                value_if_untested=40,
                testing_notes="Tested-working value $75; untested value $40; difference $35.",
            )
            batch.write_text(json.dumps([planned]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires listing_status DRAFT", result.stderr)

    def test_rejects_non_finite_numeric_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            batch = temp / "batch.json"
            invalid = item("a-001")
            invalid["decision_basis_value"] = "NaN"
            batch.write_text(json.dumps([invalid]), encoding="utf-8")
            result = self.run_script(
                "upsert", "--ledger", temp / "inventory.csv", "--input", batch
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("non-finite decision_basis_value", result.stderr)

    def test_accepts_legacy_ledger_missing_new_optional_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            ledger = temp / "inventory.csv"
            batch = temp / "batch.json"
            batch.write_text(json.dumps([item("a-001")]), encoding="utf-8")
            created = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(created.returncode, 0, created.stderr)

            with ledger.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
                legacy_fields = [
                    field
                    for field in rows[0]
                    if field
                    not in {
                        "testing_status",
                        "value_if_tested_working",
                        "value_if_untested",
                        "testing_notes",
                        "donation_confirmation_status",
                        "donation_confirmed_by",
                        "donation_confirmed_at",
                        "donation_confirmation_notes",
                    }
                ]
            with ledger.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=legacy_fields)
                writer.writeheader()
                writer.writerow({field: rows[0][field] for field in legacy_fields})

            batch.write_text(json.dumps([item("a-002")]), encoding="utf-8")
            migrated = self.run_script("upsert", "--ledger", ledger, "--input", batch)
            self.assertEqual(migrated.returncode, 0, migrated.stderr)


if __name__ == "__main__":
    unittest.main()
