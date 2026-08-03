import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "berryfine-goods-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from inventory_ledger import FIELDS  # noqa: E402


CONFIRMATION = "I confirm the selected inputs, exclusions, and catalog rules."


def item(item_id: str, decision: str, value: float, confidence: str = "medium") -> dict[str, str]:
    row = {field: "" for field in FIELDS}
    row.update(
        client_id="client-a",
        client_name="Example Client",
        intake_id="legacy-intake",
        item_id=item_id,
        quantity="1",
        category="Household",
        identified_name=f"Item {item_id}",
        identification_confidence="confirmed",
        identification_basis="Completed legacy appraisal",
        condition_grade="good",
        condition_notes="Light wear",
        photo_refs=f"{item_id}.jpg",
        comp_count="0",
        comp_summary="Completed legacy valuation retained for catalog refresh.",
        currency="USD",
        market_value_low=str(max(0, value - 10)),
        market_value_mid=str(value),
        market_value_high=str(value + 10),
        decision_basis_value=str(value),
        valuation_basis="insufficient_evidence" if confidence == "low" else "price_guide",
        valuation_confidence=confidence,
        ebay_price=str(value + 10),
        local_price=str(value),
        quick_sale_price=str(max(0, value - 10)),
        decision=decision,
        decision_rationale=(
            "Independent valuation uncertainty remains."
            if decision == "REVIEW"
            else "Completed legacy disposition."
        ),
        listing_status="DRAFT",
        human_review_status="PENDING",
        safety_status="CLEAR",
        research_date="2026-08-02",
    )
    return row


class LegacyCatalogRefreshTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args], text=True, capture_output=True, check=False
        )

    def test_policy_only_refresh_preserves_completed_actions_without_mass_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "Example Client"
            client.mkdir()
            records = root / "records" / "refresh-intake"
            records.mkdir(parents=True)
            template = client / "template.xlsx"
            template.write_bytes(b"original-template")
            source_photos = root / "source-photos"
            source_photos.mkdir()
            source_photo = source_photos / "item.jpg"
            source_photo.write_bytes(b"photo")
            categorized = client / "Categorized Inventory 2026-08-03"
            categorized_group = categorized / "SKU-1 - Item sell"
            categorized_group.mkdir(parents=True)
            (categorized_group / source_photo.name).write_bytes(b"photo")
            source_manifest = records / "source-manifest.json"
            source_manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "intake_id": "legacy-intake",
                        "source_folder": str(source_photos),
                        "photos": [
                            {
                                "sequence": 1,
                                "relative_path": source_photo.name,
                                "filename": source_photo.name,
                                "bytes": source_photo.stat().st_size,
                                "sha256": hashlib.sha256(b"photo").hexdigest(),
                                "status": "assigned",
                                "group_id": categorized_group.name,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            categorized_verification = records / "categorized-verification.json"
            categorized_result = self.run_cli(
                str(SCRIPTS / "categorized_inventory_gate.py"),
                "--manifest",
                str(source_manifest),
                "--categorized",
                str(categorized),
                "--output",
                str(categorized_verification),
            )
            self.assertEqual(
                categorized_result.returncode, 0, categorized_result.stderr
            )
            ledger = root / "client-inventory.csv"
            source_rows = [
                item("sell", "SELL", 75),
                item("band", "DONATE", 45, confidence="low"),
                item("donate", "DONATE", 25, confidence="low"),
                item("review", "REVIEW", 45, confidence="low"),
            ]
            with ledger.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(source_rows)

            source_grouping = records / "source-grouping.json"
            source_grouping.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "client_id": "client-a",
                        "intake_id": "legacy-intake",
                        "groups": [
                            {
                                "item_id": row["item_id"],
                                "sku": f"SKU-{index}",
                                "group_id": f"SKU-{index} - {row['identified_name']}",
                            }
                            for index, row in enumerate(source_rows, 1)
                        ],
                    }
                ),
                encoding="utf-8",
            )

            preflight = records / "preflight-lock.json"
            created = self.run_cli(
                str(SCRIPTS / "preflight_lock.py"),
                "create",
                "--workflow",
                "legacy-catalog-refresh",
                "--output",
                str(preflight),
                "--source-ledger",
                str(ledger),
                "--source-intake-id",
                "legacy-intake",
                "--categorized-verification",
                str(categorized_verification),
                "--catalog-template",
                str(template),
                "--client-id",
                "client-a",
                "--client-name",
                "Example Client",
                "--intake-id",
                "refresh-intake",
                "--catalog-output",
                str(client / "Example Client New Catalog.xlsx"),
                "--exceptions-output",
                str(client / "Example Client Exceptions.xlsx"),
                "--categorized-output",
                str(categorized),
                "--records-folder",
                str(records),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            confirmed = self.run_cli(
                str(SCRIPTS / "preflight_lock.py"),
                "confirm",
                "--lock",
                str(preflight),
                "--confirmed-by",
                "Test Reviewer",
                "--confirmation-text",
                CONFIRMATION,
                "--user-confirmation",
                "Proceed with the corrected legacy-refresh plan.",
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)

            batch = records / "refresh-batch.json"
            grouping = records / "refresh-grouping.json"
            plan = records / "legacy-refresh-plan.json"
            prepared = self.run_cli(
                str(SCRIPTS / "legacy_catalog_refresh.py"),
                "prepare",
                "--ledger",
                str(ledger),
                "--source-intake-id",
                "legacy-intake",
                "--target-intake-id",
                "refresh-intake",
                "--source-grouping",
                str(source_grouping),
                "--preflight-lock",
                str(preflight),
                "--batch-output",
                str(batch),
                "--grouping-output",
                str(grouping),
                "--plan-output",
                str(plan),
            )
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            plan_data = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(
                plan_data["action_counts"],
                {"CONFIRM DONATION": 1, "DONATE": 1, "REVIEW": 1, "SELL": 1},
            )
            self.assertEqual(plan_data["policy_migration_count"], 1)
            self.assertFalse(plan_data["listing_authorized"])

            revisions = records / "item-revisions.jsonl"
            upserted = self.run_cli(
                str(SCRIPTS / "inventory_ledger.py"),
                "upsert",
                "--ledger",
                str(ledger),
                "--input",
                str(batch),
                "--audit-log",
                str(revisions),
            )
            self.assertEqual(upserted.returncode, 0, upserted.stderr)

            verification = records / "research-verification.json"
            verified = self.run_cli(
                str(SCRIPTS / "legacy_catalog_refresh.py"),
                "verify",
                "--ledger",
                str(ledger),
                "--batch",
                str(batch),
                "--preflight-lock",
                str(preflight),
                "--plan",
                str(plan),
                "--output",
                str(verification),
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            verification_data = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(
                verification_data["verification_mode"], "legacy-catalog-refresh"
            )
            self.assertFalse(verification_data["listing_authorized"])

            payload = records / "catalog-payload.json"
            built = self.run_cli(
                str(SCRIPTS / "catalog_payload.py"),
                "--ledger",
                str(ledger),
                "--grouping",
                str(grouping),
                "--research-verification",
                str(verification),
                "--preflight-lock",
                str(preflight),
                "--intake-id",
                "refresh-intake",
                "--client-name",
                "Example Client",
                "--output",
                str(payload),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            payload_data = json.loads(payload.read_text(encoding="utf-8"))
            self.assertEqual(payload_data["summary"]["review"], 1)
            self.assertEqual(payload_data["summary"]["confirm_donation"], 1)
            self.assertEqual(payload_data["summary"]["exception_count"], 2)
            self.assertFalse(payload_data["listing_authorized"])


if __name__ == "__main__":
    unittest.main()
