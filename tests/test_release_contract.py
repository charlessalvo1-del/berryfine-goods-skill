import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "berryfine-goods-skill"


class ReleaseContractTests(unittest.TestCase):
    def test_reliability_release_resources_are_routed_from_skill(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8-sig")
        for name in ("photo_quality_gate.py", "review_provenance_gate.py", "apply_grouping.py", "research_gate.py", "adaptive_market_gate.py", "price_first_gate.py", "pricing_policy.py", "pricing_replay.py", "legacy_catalog_refresh.py", "categorized_inventory_gate.py", "catalog_payload.py", "catalog_builder.ps1", "bfg.py", "audit_seal.py", "outcome_ledger.py"):
            self.assertIn(name, text)
            self.assertTrue((SKILL / "scripts" / name).is_file())

    def test_warehouse_tracking_is_not_added_to_release(self) -> None:
        new_scripts = {path.name for path in (SKILL / "scripts").iterdir()}
        self.assertFalse({"warehouse.py", "movement.py", "container_tracking.py"} & new_scripts)

    def test_version_is_two_point_nine_zero(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "2.9.0")

    def test_v2_9_adaptive_age_policy_is_documented(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8-sig")
        for required in (
            "adaptive `6 / 8 / 10` search ladder",
            "$40-$50 STAFF DECISION",
            "Auction data is identification-only",
            "weighted-median anchor",
            "conservative decision floor",
            "three years",
            "decision confidence",
            "scripts/price_first_gate.py",
        ):
            self.assertIn(required, text)

    def test_catalog_builder_keeps_new_rows_out_of_conditional_formatting(self) -> None:
        text = (SKILL / "scripts" / "catalog_builder.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('FormatConditions.Delete()', text)
        self.assertIn("$target.Interior.Color = $yellow", text)

    def test_catalog_builder_preserves_blank_values_and_utf8(self) -> None:
        text = (SKILL / "scripts" / "catalog_builder.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Get-Content -Raw -Encoding UTF8", text)
        self.assertIn("$cell.ClearContents()", text)
        self.assertIn("$sheet.Cells.Item($rowNumber, 6).ClearContents()", text)
        self.assertNotIn("$excel.CutCopyMode = 0", text)

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
