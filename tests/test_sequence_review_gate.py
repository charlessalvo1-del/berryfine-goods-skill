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
    / "sequence_review_gate.py"
)


def manifest_entries(count: int) -> list[dict]:
    return [
        {
            "sequence": sequence,
            "relative_path": f"IMG_{sequence:04d}.jpg",
            "bytes": sequence,
            "sha256": hashlib.sha256(f"photo-{sequence}".encode()).hexdigest(),
            "status": "pending",
        }
        for sequence in range(1, count + 1)
    ]


def manifest_digest(count: int) -> str:
    entries = [
        {key: entry[key] for key in ("sequence", "relative_path", "bytes", "sha256")}
        for entry in manifest_entries(count)
    ]
    return hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def boundary(position: int, left: str, right: str, confidence: str = "high") -> dict:
    return {
        "after_sequence": position,
        "confidence": confidence,
        "reason": f"Visible transition from {left} to {right}",
        "left_identity": left,
        "right_identity": right,
    }


class SequenceReviewGateTests(unittest.TestCase):
    def write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def run_gate(
        self,
        root: Path,
        forward: dict,
        reverse: dict,
        cohesion: dict,
        adjudication: dict | None = None,
    ) -> subprocess.CompletedProcess[str]:
        manifest_path = root / "manifest.json"
        self.write_json(
            manifest_path,
            {
                "version": 1,
                "client_id": "client-a",
                "intake_id": "intake-a",
                "intake_method": "sequence",
                "photo_set_digest": manifest_digest(forward["photo_count"]),
                "photos": manifest_entries(forward["photo_count"]),
            },
        )
        paths = {}
        for name, value in {
            "forward": forward,
            "reverse": reverse,
            "cohesion": cohesion,
        }.items():
            paths[name] = root / f"{name}.json"
            self.write_json(paths[name], value)
        command = [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest_path),
            "--forward",
            str(paths["forward"]),
            "--reverse",
            str(paths["reverse"]),
            "--cohesion",
            str(paths["cohesion"]),
            "--output",
            str(root / "final.json"),
        ]
        if adjudication is not None:
            path = root / "adjudication.json"
            self.write_json(path, adjudication)
            command.extend(["--adjudication", str(path)])
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def review(self, pass_name: str, count: int, boundaries: list[dict]) -> dict:
        return {
            "version": 1,
            "pass": pass_name,
            "photo_count": count,
            "manifest_photo_digest": manifest_digest(count),
            "boundaries": boundaries,
        }

    def test_regression_boundaries_split_distinct_item_types(self) -> None:
        # Generic failure patterns: visually similar items must still split when
        # their style, product type, or tableware form changes.
        positions = [3, 5, 9, 11]
        evidence = [
            boundary(3, "clear stemware", "etched stemware"),
            boundary(5, "collectible figure set", "single boxed figurine"),
            boundary(9, "ceramic bowls", "ceramic dinner plates"),
            boundary(11, "ceramic dinner plates", "ceramic salad plates"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_gate(
                root,
                self.review("forward", 12, evidence),
                self.review("reverse", 12, list(reversed(evidence))),
                self.review("cohesion", 12, []),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads((root / "final.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [entry["after_sequence"] for entry in output["boundary_decisions"]],
                positions,
            )
            self.assertEqual(output["summary"]["final_group_count"], 5)
            self.assertEqual(output["summary"]["status"], "PASS")

    def test_unadjudicated_disagreement_defaults_to_reviewed_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_gate(
                root,
                self.review(
                    "forward", 8, [boundary(4, "camera body", "camera lens")]
                ),
                self.review("reverse", 8, []),
                self.review("cohesion", 8, []),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads((root / "final.json").read_text(encoding="utf-8"))
            self.assertEqual(output["summary"]["final_group_count"], 2)
            self.assertEqual(output["summary"]["review_group_count"], 2)
            self.assertEqual(output["summary"]["status"], "PASS_WITH_REVIEW")
            self.assertEqual(
                output["boundary_decisions"][0]["basis"],
                "conservative_split_unadjudicated_disagreement",
            )

    def test_disputed_join_requires_high_confidence_and_lot_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disputed = boundary(4, "plate stack A", "plate stack B")
            adjudication = {
                "version": 1,
                "pass": "adjudication",
                "photo_count": 8,
                "manifest_photo_digest": manifest_digest(8),
                "decisions": [
                    {
                        **disputed,
                        "decision": "join",
                        "lot_rationale": "",
                    }
                ],
            }
            result = self.run_gate(
                root,
                self.review("forward", 8, [disputed]),
                self.review("reverse", 8, []),
                self.review("cohesion", 8, []),
                adjudication,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("lot_rationale", result.stderr)


if __name__ == "__main__":
    unittest.main()
