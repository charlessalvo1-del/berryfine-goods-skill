import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "photo_manifest.py"
PREFLIGHT = ROOT / "berryfine-goods-skill" / "scripts" / "preflight_lock.py"
CONFIRMATION = "I confirm the selected inputs, exclusions, and catalog rules."


class PhotoManifestTests(unittest.TestCase):
    def run_scan(
        self,
        photos: Path,
        output: Path,
        intake_method: str = "auto",
        ignore_dirs: list[str] | None = None,
        ignore_files: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        template = output.parent / "template.xlsx"
        template.write_bytes(b"template")
        index = 1
        while (output.parent / f"preflight-{index}.json").exists():
            index += 1
        preflight = output.parent / f"preflight-{index}.json"
        create = [
            sys.executable,
            str(PREFLIGHT),
            "create",
            "--output", str(preflight),
            "--photos", str(photos),
            "--catalog-template", str(template),
            "--client-id", "client-a",
            "--client-name", "Example Client",
            "--intake-id", "intake-a",
            "--catalog-output", str(output.parent / "Example Client New Catalog.xlsx"),
            "--exceptions-output", str(output.parent / "Example Client Exceptions.xlsx"),
            "--categorized-output", str(output.parent / "Categorized Inventory 2026-08-02"),
            "--records-folder", str(output.parent),
        ]
        for ignored_dir in ignore_dirs or []:
            create.extend(["--ignore-dir", ignored_dir])
        for ignored_file in ignore_files or []:
            create.extend(["--ignore-file", ignored_file])
        created = subprocess.run(create, text=True, capture_output=True, check=False)
        if created.returncode:
            return created
        confirmed = subprocess.run(
            [sys.executable, str(PREFLIGHT), "confirm", "--lock", str(preflight), "--confirmed-by", "Test Reviewer", "--confirmation-text", CONFIRMATION],
            text=True, capture_output=True, check=False,
        )
        if confirmed.returncode:
            return confirmed
        command = [
            sys.executable,
            str(SCRIPT),
            "scan",
            "--photos",
            str(photos),
            "--output",
            str(output),
            "--client-id",
            "client-a",
            "--client-name",
            "Example Client",
            "--intake-id",
            "intake-a",
            "--catalog-template",
            str(template),
            "--preflight-lock",
            str(preflight),
            "--intake-method",
            intake_method,
        ]
        for ignored_dir in ignore_dirs or []:
            command.extend(["--ignore-dir", ignored_dir])
        for ignored_file in ignore_files or []:
            command.extend(["--ignore-file", ignored_file])
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_scan_natural_sort_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "IMG_10.jpg").write_bytes(b"ten")
            (photos / "IMG_2.jpg").write_bytes(b"two")
            (photos / "notes.txt").write_text("ignored", encoding="utf-8")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [photo["filename"] for photo in manifest["photos"]],
                ["IMG_2.jpg", "IMG_10.jpg"],
            )

            manifest["photos"][0].update(
                status="assigned", item_id="intake-a-001", role="hero"
            )
            output.write_text(json.dumps(manifest), encoding="utf-8")
            (photos / "IMG_10.jpg").unlink()
            (photos / "IMG_3.png").write_bytes(b"three")

            refreshed = self.run_scan(photos, output)
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            by_name = {photo["filename"]: photo for photo in manifest["photos"]}
            self.assertEqual(by_name["IMG_2.jpg"]["status"], "assigned")
            self.assertEqual(by_name["IMG_2.jpg"]["item_id"], "intake-a-001")
            self.assertEqual(by_name["IMG_10.jpg"]["status"], "missing")
            self.assertEqual(by_name["IMG_3.png"]["status"], "pending")
            self.assertEqual(manifest["intake_method"], "sequence")
            self.assertEqual(manifest["groups"], [])
            self.assertEqual(
                manifest["ignored_files"],
                [{"relative_path": "notes.txt", "reason": "unsupported_extension"}],
            )

    def test_exact_duplicates_are_deterministically_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "item.jpg").write_bytes(b"same-photo")
            (photos / "item - Copy.jpg").write_bytes(b"same-photo")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([photo["filename"] for photo in manifest["photos"]], ["item.jpg"])
            self.assertEqual(manifest["exact_duplicate_group_count"], 1)
            self.assertEqual(manifest["exact_duplicate_file_count"], 1)
            self.assertEqual(
                manifest["duplicate_resolution"],
                [
                    {
                        "relative_path": "item - Copy.jpg",
                        "reason": "exact_duplicate",
                        "canonical_path": "item.jpg",
                        "sha256": manifest["photos"][0]["sha256"],
                    }
                ],
            )
            self.assertEqual(manifest["ignored_files"], manifest["duplicate_resolution"])

    def test_duplicate_set_change_invalidates_confirmed_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "item.jpg").write_bytes(b"same-photo")
            duplicate = photos / "item (1).jpg"
            duplicate.write_bytes(b"same-photo")
            output = root / "manifest.json"
            self.assertEqual(self.run_scan(photos, output).returncode, 0)

            duplicate.unlink()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "scan",
                    "--photos", str(photos),
                    "--output", str(output),
                    "--client-id", "client-a",
                    "--client-name", "Example Client",
                    "--intake-id", "intake-a",
                    "--catalog-template", str(root / "template.xlsx"),
                    "--preflight-lock", str(root / "preflight-1.json"),
                    "--intake-method", "auto",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate set changed", result.stderr.lower())

    def test_ignores_named_archive_directory_and_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            active = photos / "Inventory"
            archive = photos / "Prior Test 1" / "Item 001"
            active.mkdir(parents=True)
            archive.mkdir(parents=True)
            (active / "IMG_1.jpg").write_bytes(b"active")
            (archive / "IMG_2.jpg").write_bytes(b"archive")
            (photos / "catalog.xlsx").write_bytes(b"workbook")
            output = root / "manifest.json"

            result = self.run_scan(
                photos, output, intake_method="sequence", ignore_dirs=["Prior Test 1"]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [photo["relative_path"] for photo in manifest["photos"]],
                ["Inventory/IMG_1.jpg"],
            )
            self.assertEqual(
                manifest["ignored_directories"][0]["relative_path"],
                "Prior Test 1",
            )
            self.assertEqual(
                manifest["scan_summary"],
                {
                    "included_images": 1,
                    "ignored_directories": 1,
                    "ignored_directory_images": 1,
                    "ignored_files": 1,
                    "exact_duplicate_groups": 0,
                    "exact_duplicate_files": 0,
                },
            )

    def test_ignores_dated_categorized_inventory_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            categorized = photos / "Categorized Inventory 2026-08-01" / "Item 001"
            categorized.mkdir(parents=True)
            (photos / "original.jpg").write_bytes(b"original")
            (categorized / "copy.jpg").write_bytes(b"copy")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [photo["filename"] for photo in manifest["photos"]],
                ["original.jpg"],
            )
            self.assertEqual(
                manifest["ignored_directories"][0]["relative_path"],
                "Categorized Inventory 2026-08-01",
            )

    def test_ignores_supported_image_by_explicit_file_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "item.jpg").write_bytes(b"item")
            (photos / "research screenshot.png").write_bytes(b"screen")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [photo["filename"] for photo in manifest["photos"]],
                ["item.jpg", "research screenshot.png"],
            )

            refreshed = self.run_scan(
                photos, output, ignore_files=["research screenshot.png"]
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn(
                "research screenshot.png",
                [photo["relative_path"] for photo in manifest["photos"]],
            )
            self.assertEqual(manifest["summary"]["missing"], 0)
            self.assertEqual(
                manifest["ignored_files"],
                [
                    {
                        "relative_path": "research screenshot.png",
                        "reason": "ignored_file_rule",
                        "rule": "research screenshot.png",
                    }
                ],
            )

    def test_groups_nested_photos_by_top_level_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            lamp = photos / "Brass Lamp"
            chair = photos / "Oak Chair" / "details"
            lamp.mkdir(parents=True)
            chair.mkdir(parents=True)
            (lamp / "front.jpg").write_bytes(b"front")
            (lamp / "label.jpg").write_bytes(b"label")
            (chair / "joint.jpg").write_bytes(b"joint")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["intake_method"], "folders")
            by_path = {
                photo["relative_path"]: photo for photo in manifest["photos"]
            }
            self.assertEqual(
                by_path["Brass Lamp/front.jpg"]["group_id"], "Brass Lamp"
            )
            self.assertEqual(
                by_path["Oak Chair/details/joint.jpg"]["group_id"], "Oak Chair"
            )
            self.assertEqual(
                [group["group_id"] for group in manifest["groups"]],
                ["Brass Lamp", "Oak Chair"],
            )

    def test_naturally_sorts_numbered_item_folders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            (photos / "10 - Lamp").mkdir(parents=True)
            (photos / "2 - Chair").mkdir(parents=True)
            (photos / "10 - Lamp" / "front.jpg").write_bytes(b"lamp")
            (photos / "2 - Chair" / "front.jpg").write_bytes(b"chair")
            output = root / "manifest.json"

            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [photo["group_id"] for photo in manifest["photos"]],
                ["2 - Chair", "10 - Lamp"],
            )

    def test_explicit_folder_mode_marks_root_photos_unassigned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "loose.jpg").write_bytes(b"loose")
            output = root / "manifest.json"

            result = self.run_scan(photos, output, intake_method="folders")
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["intake_method"], "folders")
            self.assertEqual(
                manifest["photos"][0]["group_id"], "UNASSIGNED_ROOT"
            )

    def test_rejects_cross_client_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            (photos / "one.jpg").write_bytes(b"one")
            output = root / "manifest.json"
            self.assertEqual(self.run_scan(photos, output).returncode, 0)

            manifest = json.loads(output.read_text(encoding="utf-8"))
            manifest["client_id"] = "another-client"
            output.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_scan(photos, output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("different client_id", result.stderr)

    def test_changed_photo_content_resets_prior_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            photo = photos / "one.jpg"
            photo.write_bytes(b"original")
            output = root / "manifest.json"
            self.assertEqual(self.run_scan(photos, output).returncode, 0)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            manifest["photos"][0].update(
                status="assigned", item_id="item-1", group_id="Item 1"
            )
            output.write_text(json.dumps(manifest), encoding="utf-8")
            photo.write_bytes(b"changed")

            refreshed = self.run_scan(photos, output)
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            entry = json.loads(output.read_text(encoding="utf-8"))["photos"][0]
            self.assertEqual(entry["status"], "pending")
            self.assertEqual(entry["item_id"], "")
            self.assertIn("content changed", entry["notes"].lower())


if __name__ == "__main__":
    unittest.main()
