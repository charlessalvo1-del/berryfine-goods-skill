import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "berryfine-goods-skill"
    / "scripts"
    / "categorized_inventory_gate.py"
)


class CategorizedInventoryGateTests(unittest.TestCase):
    def prepare(self, root: Path, *, legacy_hashless: bool = False) -> list[str]:
        source = root / "source"
        source.mkdir()
        categorized = root / "Categorized Inventory 2026-08-03"
        group = categorized / "EX40 - Example item"
        group.mkdir(parents=True)
        source_photo = source / "IMG_0001.jpg"
        source_photo.write_bytes(b"photo")
        (group / source_photo.name).write_bytes(b"photo")
        photo = {
            "sequence": 1,
            "relative_path": source_photo.name,
            "filename": source_photo.name,
            "bytes": source_photo.stat().st_size,
            "status": "assigned",
            "group_id": group.name,
        }
        if not legacy_hashless:
            photo["sha256"] = hashlib.sha256(b"photo").hexdigest()
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "intake_id": "source-intake",
                    "source_folder": str(source),
                    "photos": [photo],
                }
            ),
            encoding="utf-8",
        )
        return [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--categorized",
            str(categorized),
            "--output",
            str(root / "categorized-verification.json"),
        ]

    def test_verifies_manifest_hashes_and_writes_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(
                (root / "categorized-verification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["status"], "PASS")
            self.assertEqual(record["assigned_photo_count"], 1)
            self.assertEqual(record["group_count"], 1)
            self.assertEqual(record["manifest_hash_mode"], "manifest-sha256")

    def test_hashes_source_once_for_legacy_manifest_without_photo_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root, legacy_hashless=True)
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(
                (root / "categorized-verification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["manifest_hash_mode"], "legacy-source-recomputed")
            self.assertEqual(record["legacy_recomputed_photos"], 1)

    def test_changed_or_extra_categorized_file_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            categorized = root / "Categorized Inventory 2026-08-03"
            photo = categorized / "EX40 - Example item" / "IMG_0001.jpg"
            photo.write_bytes(b"changed")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("size does not match", result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = self.prepare(root)
            categorized = root / "Categorized Inventory 2026-08-03"
            (categorized / "EX40 - Example item" / "extra.jpg").write_bytes(b"extra")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unexpected file", result.stderr)


if __name__ == "__main__":
    unittest.main()
