import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "delivery_gate.py"
CATEGORIZED_SCRIPT = (
    ROOT
    / "berryfine-goods-skill"
    / "scripts"
    / "categorized_inventory_gate.py"
)


def write_xlsx(path: Path, marker: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", f"<Types>{marker}</Types>")
        archive.writestr("xl/workbook.xml", f"<workbook>{marker}</workbook>")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class DeliveryGateTests(unittest.TestCase):
    def prepare(self, root: Path, include_exceptions: bool = True) -> list[str]:
        client = root / "Example Client"
        client.mkdir()
        template = client / "template.xlsx"
        catalog = client / "Example Client New Catalog.xlsx"
        exceptions = client / "Example Client Exceptions.xlsx"
        write_xlsx(template, "template")
        write_xlsx(catalog, "catalog")
        if include_exceptions:
            write_xlsx(exceptions, "exceptions")

        categorized = client / "Categorized Inventory 2026-08-02"
        group = categorized / "EX40 - Example item"
        group.mkdir(parents=True)
        (group / "IMG_0001.jpg").write_bytes(b"photo")

        photo_hash = hashlib.sha256(b"photo").hexdigest()
        photo_record = {
            "sequence": 1,
            "relative_path": "IMG_0001.jpg",
            "bytes": 5,
            "sha256": photo_hash,
            "status": "assigned",
            "group_id": "EX40 - Example item",
        }
        photo_digest = json_hash([
            {key: photo_record[key] for key in ("sequence", "relative_path", "bytes", "sha256")}
        ])

        preflight = root / "preflight-lock.json"
        preflight.write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "CONFIRMED",
                    "client_id": "example-client",
                    "intake_id": "intake-4",
                    "source_folder": str((root / "source").resolve()),
                    "catalog_template": str(template),
                    "catalog_template_sha256": file_hash(template),
                    "photo_set_digest": photo_digest,
                    "catalog_rules_digest": "rules-digest",
                    "deliverable_paths": {
                        "catalog": str(catalog.resolve()),
                        "exceptions": str(exceptions.resolve()),
                        "categorized": str(categorized.resolve()),
                        "records": str(root.resolve()),
                    },
                }
            ),
            encoding="utf-8",
        )

        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "client_id": "example-client",
                    "intake_id": "intake-4",
                    "source_folder": str((root / "source").resolve()),
                    "catalog_template": str(template),
                    "catalog_template_sha256": file_hash(template),
                    "preflight_lock": str(preflight),
                    "preflight_lock_sha256": file_hash(preflight),
                    "catalog_rules_digest": "rules-digest",
                    "photo_set_digest": photo_digest,
                    "photos": [photo_record],
                }
            ),
            encoding="utf-8",
        )
        ledger = root / "client-inventory.csv"
        with ledger.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "intake_id",
                    "item_id",
                    "decision",
                    "listing_status",
                    "human_review_status",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "intake_id": "intake-4",
                    "item_id": "item-1",
                    "decision": "SELL",
                    "listing_status": "DRAFT",
                    "human_review_status": "PENDING",
                }
            )
        verification = root / "catalog-verification.json"
        verification.write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "PASS",
                    "intake_id": "intake-4",
                    "template": str(template.resolve()),
                    "catalog": str(catalog.resolve()),
                    "exceptions": str(exceptions.resolve()),
                    "ledger": str(ledger.resolve()),
                    "template_sha256": file_hash(template),
                    "catalog_sha256": file_hash(catalog),
                    "exceptions_sha256": file_hash(exceptions) if exceptions.exists() else "",
                    "ledger_sha256": file_hash(ledger),
                }
            ),
            encoding="utf-8",
        )
        return [
            sys.executable,
            str(SCRIPT),
            "--client-folder",
            str(client),
            "--manifest",
            str(manifest),
            "--ledger",
            str(ledger),
            "--categorized",
            str(categorized),
            "--preflight-lock",
            str(preflight),
            "--catalog-verification",
            str(verification),
        ]

    def test_passes_only_when_all_required_deliverables_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = self.prepare(Path(directory))
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"status": "PASS"', result.stdout)
            self.assertIn('"assigned_photos": 1', result.stdout)

    def test_missing_exceptions_workbook_blocks_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = self.prepare(Path(directory), include_exceptions=False)
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing Exceptions workbook", result.stderr)

    def test_changed_categorized_photo_blocks_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            photo = root / "Example Client" / "Categorized Inventory 2026-08-02" / "EX40 - Example item" / "IMG_0001.jpg"
            photo.write_bytes(b"changed")
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not match manifest", result.stderr)

    def test_stale_catalog_verification_blocks_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            catalog = root / "Example Client" / "Example Client New Catalog.xlsx"
            write_xlsx(catalog, "changed")
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("catalog_sha256 is stale", result.stderr)

    def test_legacy_catalog_refresh_requires_verified_categorized_photos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "Example Client"
            client.mkdir()
            records = root / "records" / "refresh-intake"
            records.mkdir(parents=True)
            template = client / "template.xlsx"
            catalog = client / "Example Client New Catalog.xlsx"
            exceptions = client / "Example Client Exceptions.xlsx"
            write_xlsx(template, "template")
            write_xlsx(catalog, "catalog")
            write_xlsx(exceptions, "exceptions")
            source = root / "source"
            source.mkdir()
            source_photo = source / "IMG_0001.jpg"
            source_photo.write_bytes(b"photo")
            categorized = client / "Categorized Inventory 2026-08-03"
            categorized_group = categorized / "EX40 - Example item"
            categorized_group.mkdir(parents=True)
            (categorized_group / source_photo.name).write_bytes(b"photo")
            manifest = records / "source-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "intake_id": "legacy-intake",
                        "source_folder": str(source),
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
            categorized_result = subprocess.run(
                [
                    sys.executable,
                    str(CATEGORIZED_SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--categorized",
                    str(categorized),
                    "--output",
                    str(categorized_verification),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                categorized_result.returncode, 0, categorized_result.stderr
            )
            ledger = root / "client-inventory.csv"
            with ledger.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "intake_id",
                        "item_id",
                        "decision",
                        "listing_status",
                        "human_review_status",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "intake_id": "refresh-intake",
                        "item_id": "item-1",
                        "decision": "SELL",
                        "listing_status": "DRAFT",
                        "human_review_status": "PENDING",
                    }
                )
            preflight = records / "preflight-lock.json"
            preflight.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "status": "CONFIRMED",
                        "workflow": "legacy-catalog-refresh",
                        "intake_id": "refresh-intake",
                        "source_intake_id": "legacy-intake",
                        "source_ledger_sha256": "source-hash",
                        "catalog_template": str(template.resolve()),
                        "catalog_template_sha256": file_hash(template),
                        "catalog_rules": {"legacy_refresh_listing_authorized": False},
                        "deliverable_paths": {
                            "catalog": str(catalog.resolve()),
                            "exceptions": str(exceptions.resolve()),
                            "categorized": "",
                            "records": str(records.resolve()),
                        },
                    }
                ),
                encoding="utf-8",
            )
            verification = records / "catalog-verification.json"
            verification.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "status": "PASS",
                        "intake_id": "refresh-intake",
                        "template": str(template.resolve()),
                        "catalog": str(catalog.resolve()),
                        "exceptions": str(exceptions.resolve()),
                        "ledger": str(ledger.resolve()),
                        "template_sha256": file_hash(template),
                        "catalog_sha256": file_hash(catalog),
                        "exceptions_sha256": file_hash(exceptions),
                        "ledger_sha256": file_hash(ledger),
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(SCRIPT),
                "--workflow",
                "legacy-catalog-refresh",
                "--client-folder",
                str(client),
                "--ledger",
                str(ledger),
                "--manifest",
                str(manifest),
                "--categorized",
                str(categorized),
                "--categorized-verification",
                str(categorized_verification),
                "--intake-id",
                "refresh-intake",
                "--preflight-lock",
                str(preflight),
                "--catalog-verification",
                str(verification),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"workflow": "legacy-catalog-refresh"', result.stdout)
            self.assertIn('"listing_authorized": false', result.stdout)
            self.assertIn('"assigned_photos": 1', result.stdout)

            categorized_group.rename(categorized / "EX40 - Wrong item")
            changed = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            self.assertEqual(changed.returncode, 2)
            self.assertIn("categorized", changed.stderr.casefold())


if __name__ == "__main__":
    unittest.main()
