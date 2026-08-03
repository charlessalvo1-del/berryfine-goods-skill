import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "apply_grouping.py"


class ApplyGroupingTests(unittest.TestCase):
    def test_applies_every_photo_once_and_binds_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); digest = "a" * 64
            manifest = root / "manifest.json"; grouping = root / "grouping.json"; identities = root / "identities.json"; reconciliation = root / "reconciliation.json"
            manifest.write_text(json.dumps({"client_id": "c", "intake_id": "i", "photo_set_digest": digest, "photos": [{"sequence": 1, "status": "pending"}, {"sequence": 2, "status": "pending"}]}), encoding="utf-8")
            grouping.write_text(json.dumps({"client_id": "c", "intake_id": "i", "manifest_photo_digest": digest, "groups": [{"ordinal": 1, "sequences": [1, 2], "grouping_review_status": "AUTO_ACCEPTED"}]}), encoding="utf-8")
            identities.write_text(json.dumps({"groups": [{"ordinal": 1, "item_id": "item-1", "sku": "BB1", "group_id": "BB1 - Item"}]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--grouping", str(grouping), "--identities", str(identities), "--reconciliation", str(reconciliation)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual({photo["item_id"] for photo in updated["photos"]}, {"item-1"})
            self.assertIn("grouping_binding", updated)

    def test_rejects_unassigned_inventory_photo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); digest = "b" * 64
            manifest = root / "m.json"; grouping = root / "g.json"; identities = root / "i.json"
            manifest.write_text(json.dumps({"client_id": "c", "intake_id": "i", "photo_set_digest": digest, "photos": [{"sequence": 1, "status": "pending"}, {"sequence": 2, "status": "pending"}]}), encoding="utf-8")
            grouping.write_text(json.dumps({"client_id": "c", "intake_id": "i", "manifest_photo_digest": digest, "groups": [{"ordinal": 1, "sequences": [1]}]}), encoding="utf-8")
            identities.write_text(json.dumps({"groups": [{"ordinal": 1, "item_id": "x", "sku": "X", "group_id": "X - One"}]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--grouping", str(grouping), "--identities", str(identities), "--reconciliation", str(root / "r.json")], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unassigned", result.stderr)


if __name__ == "__main__":
    unittest.main()
