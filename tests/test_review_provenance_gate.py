import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "review_provenance_gate.py"


class ReviewProvenanceGateTests(unittest.TestCase):
    def review(self, name: str, run_id: str, order: str, visible: list[str] | None = None) -> dict:
        return {"version": 1, "pass": name, "manifest_photo_digest": "a" * 64, "boundaries": [], "provenance": {"review_run_id": run_id, "created_at": "2026-08-02T12:00:00-04:00", "model": "vision-model", "prompt_sha256": "b" * 64, "input_order": order, "isolated_context": True, "visible_prior_passes": visible or [], "prior_run_data_visible": False}}

    def run_gate(self, root: Path, reverse_visible: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        manifest = root / "manifest.json"; manifest.write_text(json.dumps({"client_id": "c", "intake_id": "i", "photo_set_digest": "a" * 64}), encoding="utf-8")
        paths = {}
        for name, value in {"forward": self.review("forward", "run-f", "forward"), "reverse": self.review("reverse", "run-r", "reverse", reverse_visible), "cohesion": self.review("cohesion", "run-c", "group-sample")}.items():
            paths[name] = root / f"{name}.json"; paths[name].write_text(json.dumps(value), encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), "--forward", str(paths["forward"]), "--reverse", str(paths["reverse"]), "--cohesion", str(paths["cohesion"]), "--output", str(root / "lock.json")], text=True, capture_output=True)

    def test_passes_distinct_blind_review_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_gate(Path(directory)).returncode, 0)

    def test_rejects_reverse_pass_that_saw_forward_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(Path(directory), ["forward"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("isolated", result.stderr)


if __name__ == "__main__":
    unittest.main()
