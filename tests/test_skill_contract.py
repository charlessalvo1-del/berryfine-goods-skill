import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "berryfine-goods-skill" / "SKILL.md"
BULK_GUIDE = (
    ROOT / "berryfine-goods-skill" / "references" / "bulk-photo-intake.md"
)


class SkillContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_text = SKILL.read_text(encoding="utf-8")
        self.guide_text = BULK_GUIDE.read_text(encoding="utf-8")

    def test_centralized_records_contract_is_documented(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn(r"C:\BFG Bulk Import Records", text)
            self.assertIn("client-inventory.csv", text)
            self.assertIn("<intake-id>", text)

    def test_new_catalog_filename_is_mandatory(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("<Client Folder Name> New Catalog.xlsx", text)
            self.assertNotIn("<Client Folder Name> Catalog.xlsx", text)

    def test_client_catalog_column_contract_is_documented(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("RECOMMENDED ACTION", text)
            self.assertIn("HISTORY/INFO", text)
            self.assertIn("Storage", text)
            self.assertIn("SELL", text)
            self.assertIn("DONATE", text)
            self.assertIn("REVIEW", text)
            self.assertIn("CONFIRM DONATION", text)
            self.assertIn("column I", text)

        self.assertIn("Preserve every pre-populated column D value exactly", self.skill_text)
        self.assertIn("only in column D for newly appended rows", self.skill_text)
        self.assertIn("When introducing J to a template that did not have it", self.skill_text)
        self.assertIn("When the template already has J, preserve every retained J value", self.skill_text)
        self.assertIn("Never write testing status in this column", self.skill_text)

    def test_catalog_rules_require_explicit_preflight_confirmation(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("catalog rules", text)
            self.assertIn("generic", text.lower())
            self.assertIn("confirm", text.lower())

    def test_forty_dollar_confirmation_band_is_documented(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("$40 through $49.99", text)
            self.assertIn(
                "Confirm this item will not be sold before donation or rehoming.",
                text,
            )
            self.assertIn("`CONFIRM DONATION`", text)

    def test_categorized_folders_use_unique_catalog_identity(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("<SKU> - <DESCRIPTION>", text)
            self.assertIn("Never use column D", text)
            self.assertIn("duplicate", text)

    def test_recommended_action_controls_new_row_fill(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("#FFFF00", text)
            self.assertIn("current-intake", text)
            self.assertIn("`SELL`", text)
            self.assertIn("`REVIEW`", text)
            self.assertIn("`DONATE`", text)
            self.assertIn("`CONFIRM DONATION`", text)
            self.assertIn("yellow", text.lower())
            self.assertIn("blue", text.lower())

        self.assertIn("across columns A through J", self.skill_text)
        self.assertIn("Do not use conditional formatting", self.skill_text)
        for text in (self.skill_text, self.guide_text):
            self.assertIn("materialize the read-only source table's displayed formats", text)
            self.assertIn("one bulk format operation", text)
        self.assertIn("auto-fit", self.skill_text)
        self.assertIn("never recolor retained historical rows", self.guide_text)
        self.assertNotIn("Add new inventory rows with no fill color", self.skill_text)

    def test_prior_safeguards_remain_documented(self) -> None:
        required_skill_rules = (
            "Treat this confirmation as a hard gate",
            "Never resume, copy, seed",
            "Blue fill means sold",
            "current-intake `SELL` row is unfilled",
            "Treat required testing as an operational limitation",
            "Never place these internal files in the main client intake",
        )
        for rule in required_skill_rules:
            self.assertIn(rule, self.skill_text)

    def test_flat_sequence_uses_automated_independent_review(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("forward", text.lower())
            self.assertIn("reverse", text.lower())
            self.assertIn("cohesion", text.lower())
            self.assertIn("lot_rationale", text)
            self.assertIn("sequence_review_gate.py", text)
            self.assertIn("default to a split", text)
        self.assertIn("Do not require the user to create item folders", self.skill_text)
        self.assertIn("Do not ask the user to review boundaries", self.skill_text)

    def test_completion_requires_both_client_workbooks(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("delivery_gate.py", text)
            self.assertIn("New Catalog", text)
            self.assertIn("Exceptions", text)
            self.assertIn("mandatory paired", text)
            self.assertIn("report", text.lower())
            self.assertIn("complete", text.lower())

    def test_integrity_and_verification_gates_are_documented(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("preflight-lock.json", text)
            self.assertIn("catalog_gate.py", text)
            self.assertIn("catalog-verification.json", text)
            self.assertIn("photo", text.lower())
            self.assertIn("hash", text.lower())

    def test_exact_duplicates_are_resolved_and_fail_closed(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("exact duplicate", text.lower())
            self.assertIn("canonical", text.lower())
            self.assertIn("without", text.lower())
            self.assertIn("delet", text.lower())
            self.assertIn("SHA-256", text)
        self.assertIn("hard blocker", self.skill_text)
        self.assertIn("invalidates the run", self.guide_text)

    def test_legacy_refresh_is_explicit_and_cannot_authorize_listing(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("legacy-catalog-refresh", text)
            self.assertIn("legacy_catalog_refresh.py", text)
            self.assertIn("listing", text.lower())
            self.assertIn("DRAFT", text)
            self.assertIn("PENDING", text)
        self.assertIn("Do not silently relabel those rows `REVIEW`", self.skill_text)
        self.assertIn("categorized_inventory_gate.py", self.skill_text)
        self.assertIn("destination-only digest", self.guide_text)
        self.assertIn("main client folder", self.guide_text)

    def test_repository_root_completion_commands_are_explicit(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn(r"python .\berryfine-goods-skill\scripts\catalog_gate.py", text)
            self.assertIn(r"python .\berryfine-goods-skill\scripts\delivery_gate.py --workflow full-intake", text)
            self.assertIn(r"python .\berryfine-goods-skill\scripts\bfg.py audit", text)
            self.assertIn(r"python .\berryfine-goods-skill\scripts\bfg.py legacy-audit", text)
            self.assertIn(r"delivery_gate.py --workflow legacy-catalog-refresh", text)
            self.assertIn("does not replace", text)

    def test_exact_excel_builder_requirements_are_documented(self) -> None:
        for text in (self.skill_text, self.guide_text):
            self.assertIn("catalog_builder.ps1", text)
            self.assertIn("Windows", text)
            self.assertIn("PowerShell", text)
            self.assertIn("desktop Microsoft Excel", text)
            self.assertIn("Excel COM", text)
            self.assertIn("cannot claim exact compatibility", text)
            self.assertIn("does not replace deterministic gates", text)


if __name__ == "__main__":
    unittest.main()
