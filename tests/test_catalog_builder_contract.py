import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "catalog_builder.ps1"


class CatalogBuilderContractTests(unittest.TestCase):
    def test_builder_encodes_catalog_regressions(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("retained_locations_preserved=$true", text)
        self.assertIn("CONFIRM DONATION", text)
        self.assertIn("Refusing to overwrite existing output", text)
        self.assertIn("Catalog and Exceptions workbooks must be in the same client folder", text)
        self.assertIn("Builder verification must be stored outside the main client folder", text)
        self.assertIn("retained_fill_method='excel-materialized-format-snapshot'", text)
        self.assertIn("$templateHasActionColumn", text)
        self.assertIn("historical_action_column_preserved=$templateHasActionColumn", text)
        self.assertNotIn("Cells.Item($row, 4).Value2 = 'Storage'", text)

    def test_paired_publication_rolls_back_on_failure(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("$catalogPublished=$false", text)
        self.assertIn("if ($catalogPublished -and", text)
        self.assertIn("if ($exceptionsPublished -and", text)
        self.assertIn("if ($verificationPublished -and", text)

    def test_builder_uses_bulk_excel_operations_for_large_catalogs(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn('Range("I$headerRow`:I$retainedLastRow").Copy', text)
        self.assertIn("Unlist without resizing", text)
        self.assertNotIn("$table.Resize", text)
        self.assertIn("$table.Unlist()", text)
        self.assertIn("PasteSpecial($xlPasteFormats)", text)
        self.assertIn("historical conditional-format", text)
        self.assertIn("$formattedLastRow, $retainedFormatLastCol", text)
        self.assertIn("last populated SKU in column B", text)
        self.assertIn("$styleSourceRow", text)
        self.assertIn("outside historical conditional-format", text)
        self.assertIn("$allNewRows.ClearContents()", text)
        self.assertIn("Preserve the template's historical conditional-format ranges", text)
        self.assertNotIn("$allNewRows.FormatConditions.Delete()", text)
        self.assertIn("$sheet.Calculate()", text)
        self.assertNotIn("CalculateFullRebuild", text)
        self.assertNotIn("for ($row = $headerRow; $row -le $retainedLastRow; $row++)", text)
        self.assertNotIn('Copy($sheet.Range("A$rowNumber`:I$rowNumber"))', text)

    def test_exceptions_numeric_layout_values_are_com_safe(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("ColumnWidth=[double]", text)
        self.assertIn("RowHeight=[double]", text)


if __name__ == "__main__":
    unittest.main()
