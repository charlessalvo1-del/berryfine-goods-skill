import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "preflight_lock.py"
CONFIRMATION = "I confirm the selected inputs, exclusions, and catalog rules."


class PreflightLockTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path]:
        photos = root / "photos"
        photos.mkdir()
        (photos / "IMG_0001.jpg").write_bytes(b"photo")
        template = root / "template.xlsx"
        template.write_bytes(b"template")
        lock = root / "preflight-lock.json"
        return photos, template, lock

    def create(self, root: Path, photos: Path, template: Path, lock: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT), "create",
                "--output", str(lock),
                "--photos", str(photos),
                "--catalog-template", str(template),
                "--client-id", "client-a",
                "--client-name", "Example Client",
                "--intake-id", "intake-a",
                "--catalog-output", str(root / "Example Client New Catalog.xlsx"),
                "--exceptions-output", str(root / "Example Client Exceptions.xlsx"),
                "--categorized-output", str(root / "Categorized Inventory 2026-08-02"),
                "--records-folder", str(root / "records"),
            ],
            text=True, capture_output=True, check=False,
        )

    def test_create_and_confirm_records_human_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos, template, lock = self.prepare(root)
            created = self.create(root, photos, template, lock)
            self.assertEqual(created.returncode, 0, created.stderr)
            pending = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(pending["status"], "PENDING")
            self.assertEqual(len(pending["photo_set_digest"]), 64)
            self.assertEqual(len(pending["catalog_template_sha256"]), 64)
            self.assertIn("CONFIRM DONATION", pending["catalog_rules"]["actions"])

            confirmed = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "confirm",
                    "--lock", str(lock),
                    "--confirmed-by", "Test Reviewer",
                    "--confirmation-text", CONFIRMATION,
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            record = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "CONFIRMED")
            self.assertEqual(record["confirmed_by"], "Test Reviewer")
            self.assertTrue(record["confirmed_at"])

    def test_preflight_hash_binds_automatic_duplicate_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos, template, lock = self.prepare(root)
            (photos / "IMG_0001 - Copy.jpg").write_bytes(b"photo")

            created = self.create(root, photos, template, lock)

            self.assertEqual(created.returncode, 0, created.stderr)
            pending = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(pending["photo_count"], 1)
            self.assertEqual(pending["exact_duplicate_group_count"], 1)
            self.assertEqual(pending["exact_duplicate_file_count"], 1)
            self.assertEqual(len(pending["duplicate_resolution_digest"]), 64)
            self.assertEqual(
                pending["duplicate_resolution"][0]["canonical_path"],
                "IMG_0001.jpg",
            )

    def test_rejects_generic_confirmation_and_confirmed_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos, template, lock = self.prepare(root)
            self.assertEqual(self.create(root, photos, template, lock).returncode, 0)
            generic = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "confirm", "--lock", str(lock),
                    "--confirmed-by", "Test Reviewer", "--confirmation-text", "confirmed",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(generic.returncode, 2)
            self.assertIn("must exactly equal", generic.stderr)

            subprocess.run(
                [
                    sys.executable, str(SCRIPT), "confirm", "--lock", str(lock),
                    "--confirmed-by", "Test Reviewer", "--confirmation-text", CONFIRMATION,
                ],
                text=True, capture_output=True, check=True,
            )
            replace = self.create(root, photos, template, lock)
            self.assertEqual(replace.returncode, 2)


if __name__ == "__main__":
    unittest.main()
