import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "organize_photos.py"


class OrganizePhotosTests(unittest.TestCase):
    def run_organize(
        self, manifest: Path, output: Path, resume: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ]
        if resume:
            command.append("--resume")
        return subprocess.run(
            command, text=True, capture_output=True, check=False
        )

    def make_manifest(self, root: Path, status: str = "assigned") -> Path:
        photos = root / "photos"
        photos.mkdir()
        (photos / "front.jpg").write_bytes(b"front")
        (photos / "detail.jpg").write_bytes(b"detail")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "source_folder": str(photos),
                    "photos": [
                        {
                            "relative_path": "front.jpg",
                            "sha256": hashlib.sha256(b"front").hexdigest(),
                            "status": status,
                            "group_id": "Item 001",
                        },
                        {
                            "relative_path": "detail.jpg",
                            "sha256": hashlib.sha256(b"detail").hexdigest(),
                            "status": "assigned",
                            "group_id": "Item 002",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_copies_photos_into_exact_group_folders_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root)
            output = root / "Categorized Inventory"

            result = self.run_organize(manifest, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((output / "Item 001" / "front.jpg").read_bytes(), b"front")
            self.assertEqual((output / "Item 002" / "detail.jpg").read_bytes(), b"detail")

            resumed = self.run_organize(manifest, output, resume=True)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["verified_existing"], 2)

    def test_rejects_unassigned_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root, status="unresolved")
            result = self.run_organize(manifest, root / "output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not assigned", result.stderr)

    def test_skips_documented_excluded_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root, status="excluded")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["photos"][0]["notes"] = "Non-inventory reference screenshot"
            payload["photos"][0].pop("group_id")
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            output = root / "output"
            result = self.run_organize(manifest, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["photos"], 1)
            self.assertEqual(summary["excluded_skipped"], 1)
            self.assertFalse((output / "Item 001" / "front.jpg").exists())
            self.assertEqual((output / "Item 002" / "detail.jpg").read_bytes(), b"detail")

    def test_rejects_excluded_photo_without_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root, status="excluded")
            result = self.run_organize(manifest, root / "output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("no reason", result.stderr)

    def test_skips_separator_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root, status="separator")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["photos"][0].pop("group_id")
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            output = root / "output"
            result = self.run_organize(manifest, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["photos"], 1)
            self.assertEqual(summary["separators_skipped"], 1)
            self.assertFalse((output / "Item 001" / "front.jpg").exists())

    def test_rejects_manifest_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["photos"][0]["relative_path"] = "../outside.jpg"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_organize(manifest, root / "output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("escapes its root", result.stderr)

    def test_rejects_changed_source_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root)
            (root / "photos" / "front.jpg").write_bytes(b"changed")
            result = self.run_organize(manifest, root / "output")
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not match manifest hash", result.stderr)

    def test_rejects_identical_content_assigned_to_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_manifest(root)
            photos = root / "photos"
            (photos / "detail.jpg").write_bytes(b"front")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["photos"][1]["sha256"] = hashlib.sha256(b"front").hexdigest()
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            result = self.run_organize(manifest, root / "output")

            self.assertEqual(result.returncode, 2)
            self.assertIn("identical photo content", result.stderr)


if __name__ == "__main__":
    unittest.main()
