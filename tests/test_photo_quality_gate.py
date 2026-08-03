import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "photo_quality_gate.py"


class PhotoQualityGateTests(unittest.TestCase):
    def prepare(self, root: Path, *, include_hash: bool = True) -> tuple[Path, Path]:
        photos = root / "photos"; photos.mkdir()
        image = photos / "item.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 640, 480) + b"evidence")
        entry = {"sequence": 1, "relative_path": "item.png", "bytes": image.stat().st_size, "status": "pending"}
        if include_hash:
            entry["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"client_id": "c", "intake_id": "i", "source_folder": str(photos), "photos": [entry]}), encoding="utf-8")
        return manifest, root / "quality.json"

    def test_passes_real_signature_hash_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, output = self.prepare(Path(directory))
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["photos"][0]["width"], 640)
            self.assertEqual(report["status"], "PASS")

    def test_rejects_manifest_without_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, output = self.prepare(Path(directory), include_hash=False)
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing sha256", result.stderr)


if __name__ == "__main__":
    unittest.main()
