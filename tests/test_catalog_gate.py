import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "berryfine-goods-skill" / "scripts" / "catalog_gate.py"
sys.path.insert(0, str(SCRIPT.parent))
from catalog_gate import is_allowed_formula_extension, retained_conditional_ranges


def column_index(ref: str) -> int:
    letters = "".join(char for char in ref if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - 64
    return value


def write_book(path: Path, sheets: dict[str, dict[str, tuple[str, int]]]) -> None:
    sheet_nodes = []
    rel_nodes = []
    overrides = []
    print_areas = []
    worksheet_parts: list[tuple[str, str]] = []
    for index, (name, cells) in enumerate(sheets.items(), 1):
        sheet_nodes.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
        rel_nodes.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
        overrides.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        max_row = max(int("".join(char for char in ref if char.isdigit())) for ref in cells)
        max_col = max(column_index(ref) for ref in cells)
        end_column = chr(64 + max_col)
        print_areas.append(
            f'<definedName name="_xlnm.Print_Area" localSheetId="{index - 1}">\'{escape(name)}\'!$A$1:${end_column}${max_row}</definedName>'
        )
    # Build worksheet rows without relying on cell order.
    for index, cells in enumerate(sheets.values(), 1):
        rows: dict[int, list[str]] = {}
        for ref, (value, style) in cells.items():
            row = int("".join(char for char in ref if char.isdigit()))
            rows.setdefault(row, []).append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        row_xml = "".join(f'<row r="{row}" ht="30" customHeight="1">{"".join(values)}</row>' for row, values in sorted(rows.items()))
        last_row = max(rows)
        last_col_num = max(column_index(ref) for ref in cells)
        last_col = chr(64 + last_col_num)
        worksheet_parts.append((f"xl/worksheets/sheet{index}.xml", f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="10" max="10" width="20" customWidth="1"/></cols><sheetData>{row_xml}</sheetData><autoFilter ref="A1:{last_col}{last_row}"/></worksheet>'))

    workbook = f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{"".join(sheet_nodes)}</sheets><definedNames>{"".join(print_areas)}</definedNames></workbook>'
    rels = f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rel_nodes)}<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    styles = '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/><bgColor indexed="64"/></patternFill></fill></fills><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="0" fillId="2" borderId="0" applyFill="1"/><xf numFmtId="0" fontId="0" fillId="2" borderId="0" applyFill="1" applyAlignment="1"><alignment wrapText="1"/></xf></cellXfs></styleSheet>'
    content_types = f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>{"".join(overrides)}</Types>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/styles.xml", styles)
        for target, xml in worksheet_parts:
            archive.writestr(target, xml)


class CatalogGateTests(unittest.TestCase):
    def test_conditional_formats_may_only_truncate_after_retained_rows(self) -> None:
        self.assertEqual(
            retained_conditional_ranges(["B6:G103", "F6:F103"], 44),
            ["B6:G44", "F6:F44"],
        )
        self.assertEqual(
            retained_conditional_ranges(["B6:G40", "J50:J60"], 44),
            ["B6:G40"],
        )

    def test_formula_extension_is_exact_and_cannot_hide_summary_edits(self) -> None:
        self.assertTrue(is_allowed_formula_extension("=SUM(F5:F144)", "=SUM(F5:F148)", 144, 148))
        self.assertTrue(is_allowed_formula_extension("=SUM(F5:F144)", "=SUM(F5:F144)", 144, 148))
        self.assertFalse(is_allowed_formula_extension("=SUM(F5:F144)", "=AVERAGE(F5:F148)", 144, 148))
        self.assertFalse(is_allowed_formula_extension("=SUM(F5:F144)", "=SUM(F1:F148)", 144, 148))

    def prepare(self, root: Path) -> tuple[list[str], Path, Path]:
        template = root / "template.xlsx"
        catalog = root / "Example New Catalog.xlsx"
        exceptions = root / "Example Exceptions.xlsx"
        historical = {
            "D1": ("LOCATION", 0), "H1": ("HISTORY/INFO", 0),
            "A2": ("Historical item", 0), "D2": ("Warehouse A", 0),
        }
        write_book(template, {"Inventory List": historical})
        current = dict(historical)
        current["J1"] = ("RECOMMENDED ACTION", 0)
        for column in "ABCDEFGHIJ":
            current[f"{column}3"] = ("", 1)
        current.update({
            "A3": ("Current item", 1), "B3": ("item-1", 1), "D3": ("Storage", 1),
            "H3": ("Supported sold evidence; confirm donation.", 2),
            "I3": ("", 1), "J3": ("CONFIRM DONATION", 1),
        })
        write_book(catalog, {"Inventory List": current})
        write_book(exceptions, {"Exceptions": {"A1": ("ITEM ID", 0), "A2": ("item-1", 0)}})
        ledger = root / "client-inventory.csv"
        with ledger.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["intake_id", "item_id", "decision"])
            writer.writeheader()
            writer.writerow({"intake_id": "intake-a", "item_id": "item-1", "decision": "CONFIRM DONATION"})
        output = root / "catalog-verification.json"
        command = [
            sys.executable, str(SCRIPT), "--template", str(template),
            "--catalog", str(catalog), "--exceptions", str(exceptions),
            "--ledger", str(ledger), "--intake-id", "intake-a", "--output", str(output),
        ]
        return command, catalog, output

    def test_passes_complete_contract_and_writes_hash_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command, _, output = self.prepare(Path(directory))
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertIn('"status": "PASS"', output.read_text(encoding="utf-8"))

    def test_rejects_changed_historical_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, catalog, _ = self.prepare(root)
            # Rebuild with a changed historical location.
            changed = {
                "D1": ("LOCATION", 0), "H1": ("HISTORY/INFO", 0),
                "A2": ("Historical item", 0), "D2": ("Storage", 0),
                "J1": ("RECOMMENDED ACTION", 0),
            }
            for column in "ABCDEFGHIJ":
                changed[f"{column}3"] = ("", 1)
            changed.update({"A3": ("Current", 1), "B3": ("item-1", 1), "D3": ("Storage", 1), "H3": ("History", 2), "I3": ("", 1), "J3": ("CONFIRM DONATION", 1)})
            write_book(catalog, {"Inventory List": changed})
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Retained template cell changed", result.stderr)

    def test_existing_action_column_is_preserved_but_excluded_from_current_intake(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.xlsx"
            catalog = root / "Example New Catalog.xlsx"
            exceptions = root / "Example Exceptions.xlsx"
            historical = {
                "D1": ("LOCATION", 0), "H1": ("HISTORY/INFO", 0), "J1": ("RECOMMENDED ACTION", 0),
                "B2": ("OLD-1", 0), "D2": ("Warehouse A", 0), "J2": ("SELL", 0),
            }
            write_book(template, {"Inventory List": historical})
            current = dict(historical)
            for column in "ABCDEFGHIJ":
                current[f"{column}3"] = ("", 1)
            current.update({
                "B3": ("item-1", 1), "D3": ("Storage", 1), "H3": ("Supported evidence", 2),
                "I3": ("", 1), "J3": ("CONFIRM DONATION", 1),
            })
            write_book(catalog, {"Inventory List": current})
            write_book(exceptions, {"Exceptions": {"A1": ("ITEM ID", 0), "A2": ("item-1", 0)}})
            ledger = root / "client-inventory.csv"
            ledger.write_text("intake_id,item_id,decision\nintake-a,item-1,CONFIRM DONATION\n", encoding="utf-8")

            def digest(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest()

            builder = root / "builder-verification.json"
            builder.write_text(json.dumps({
                "status": "PASS", "template_sha256": digest(template), "catalog_sha256": digest(catalog),
                "exceptions_sha256": digest(exceptions), "retained_locations_preserved": True,
                "retained_displayed_fills_preserved": True,
                "retained_fill_method": "excel-materialized-format-snapshot", "new_location": "Storage",
                "retained_last_row": 2, "first_new_row": 3, "final_row": 3, "new_item_count": 1,
                "actions": ["SELL", "DONATE", "REVIEW", "CONFIRM DONATION"],
            }), encoding="utf-8")
            output = root / "catalog-verification.json"
            command = [
                sys.executable, str(SCRIPT), "--template", str(template), "--catalog", str(catalog),
                "--exceptions", str(exceptions), "--ledger", str(ledger), "--intake-id", "intake-a",
                "--builder-verification", str(builder), "--output", str(output),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"current_intake_rows": 1', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
