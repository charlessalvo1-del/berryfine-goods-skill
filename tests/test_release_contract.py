import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "berryfine-goods-skill"


class ReleaseContractTests(unittest.TestCase):
    def test_reliability_release_resources_are_routed_from_skill(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8-sig")
        for name in ("photo_quality_gate.py", "review_provenance_gate.py", "apply_grouping.py", "research_gate.py", "legacy_catalog_refresh.py", "categorized_inventory_gate.py", "catalog_payload.py", "catalog_builder.ps1", "bfg.py", "audit_seal.py", "outcome_ledger.py"):
            self.assertIn(name, text)
            self.assertTrue((SKILL / "scripts" / name).is_file())

    def test_warehouse_tracking_is_not_added_to_release(self) -> None:
        new_scripts = {path.name for path in (SKILL / "scripts").iterdir()}
        self.assertFalse({"warehouse.py", "movement.py", "container_tracking.py"} & new_scripts)

    def test_version_is_two_point_two_zero(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "2.2.0")

    def test_ci_actions_are_immutable_sha_pins(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s+actions/(?:checkout|setup-python)@([0-9a-f]+)", workflow)
        self.assertEqual(len(uses), 2)
        self.assertTrue(all(len(commit) == 40 for commit in uses))
        self.assertIn("# v6.0.2", workflow)
        self.assertIn("# v6.2.0", workflow)

    def test_failure_baseline_is_retained_as_regression_evidence(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "estate-regression-baseline.json"
        text = fixture.read_text(encoding="utf-8")
        for code in ("PREFLIGHT_MISSING", "PHOTO_HASHES_MISSING", "GROUPING_NOT_BOUND", "BORDERLINE_POLICY_VIOLATION", "UNSUPPORTED_DISPOSITION"):
            self.assertIn(code, text)


if __name__ == "__main__":
    unittest.main()
