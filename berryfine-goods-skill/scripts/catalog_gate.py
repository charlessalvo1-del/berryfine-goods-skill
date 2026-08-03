#!/usr/bin/env python3
"""Deterministically verify BFG catalog and Exceptions workbook contracts."""

from __future__ import annotations

import argparse
import csv
import json
import posixpath
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from bfg_integrity import atomic_write_json, sha256_file, sha256_json


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")
RANGE_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")
FORMULA_ERRORS = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
ACTIONS = {"SELL", "DONATE", "REVIEW", "CONFIRM DONATION"}
ATTENTION_ACTIONS = {"DONATE", "REVIEW", "CONFIRM DONATION"}


class CatalogError(ValueError):
    """Raised when a workbook violates the BFG catalog contract."""


def is_allowed_formula_extension(expected: str, actual: str, old_last_row: int, new_last_row: int) -> bool:
    """Allow only an unchanged formula or the builder's exact last-row extension."""
    if actual == expected:
        return True
    pattern = re.compile(rf"(?<=[A-Z]){old_last_row}(?![0-9])")
    return actual == pattern.sub(str(new_last_row), expected)


def retained_conditional_ranges(ranges: list[str], retained_last_row: int) -> list[str]:
    """Trim template rules only where they covered blank rows after inventory."""
    retained: list[str] = []
    for value in ranges:
        match = RANGE_RE.fullmatch(value)
        if not match:
            retained.append(value)
            continue
        start_col, start_row_text, end_col, end_row_text = match.groups()
        start_row = int(start_row_text)
        end_row = int(end_row_text)
        if start_row > retained_last_row:
            continue
        end_row = min(end_row, retained_last_row)
        retained.append(f"{start_col}{start_row}:{end_col}{end_row}")
    return sorted(retained)


def q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def col_number(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - 64
    return value


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in si.iter(q(MAIN, "t"))) for si in root]


def xml_signature(node: ET.Element | None) -> str:
    return ET.tostring(node, encoding="unicode") if node is not None else ""


def read_styles(archive: zipfile.ZipFile) -> dict[int, dict[str, Any]]:
    if "xl/styles.xml" not in archive.namelist():
        return {0: {"fill": ("none", ""), "signature": "default", "signature_no_fill": "default"}}
    root = ET.fromstring(archive.read("xl/styles.xml"))
    fonts_node = root.find(q(MAIN, "fonts"))
    borders_node = root.find(q(MAIN, "borders"))
    num_formats_node = root.find(q(MAIN, "numFmts"))
    fonts = [xml_signature(node) for node in (list(fonts_node) if fonts_node is not None else [])]
    borders = [xml_signature(node) for node in (list(borders_node) if borders_node is not None else [])]
    custom_formats = {
        node.get("numFmtId", ""): node.get("formatCode", "")
        for node in (list(num_formats_node) if num_formats_node is not None else [])
    }
    fills_node = root.find(q(MAIN, "fills"))
    fills: list[tuple[str, str]] = []
    fill_xml: list[str] = []
    for fill in list(fills_node) if fills_node is not None else []:
        pattern = fill.find(q(MAIN, "patternFill"))
        pattern_type = (pattern.get("patternType", "none") if pattern is not None else "none")
        color = ""
        if pattern is not None:
            foreground = pattern.find(q(MAIN, "fgColor"))
            if foreground is not None:
                color = foreground.get("rgb", "") or foreground.get("indexed", "")
        fills.append((pattern_type, color.upper()))
        fill_xml.append(xml_signature(fill))
    cell_xfs = root.find(q(MAIN, "cellXfs"))
    result: dict[int, dict[str, Any]] = {}
    for index, xf in enumerate(list(cell_xfs) if cell_xfs is not None else []):
        fill_id = int(xf.get("fillId", "0"))
        font_id = int(xf.get("fontId", "0"))
        border_id = int(xf.get("borderId", "0"))
        num_fmt_id = xf.get("numFmtId", "0")
        signature = {
            "num_fmt": custom_formats.get(num_fmt_id, f"builtin:{num_fmt_id}"),
            "font": fonts[font_id] if font_id < len(fonts) else f"missing:{font_id}",
            "fill": fill_xml[fill_id] if fill_id < len(fill_xml) else f"missing:{fill_id}",
            "border": borders[border_id] if border_id < len(borders) else f"missing:{border_id}",
            "xf_attributes": sorted(
                (key, value)
                for key, value in xf.attrib.items()
                if key not in {"numFmtId", "fontId", "fillId", "borderId"}
            ),
            "alignment": xml_signature(xf.find(q(MAIN, "alignment"))),
            "protection": xml_signature(xf.find(q(MAIN, "protection"))),
        }
        result[index] = {
            "fill": fills[fill_id] if fill_id < len(fills) else ("unknown", ""),
            "signature": sha256_json(signature),
            "signature_no_fill": sha256_json({key: value for key, value in signature.items() if key != "fill"}),
            "wrap_text": (
                xf.find(q(MAIN, "alignment")) is not None
                and xf.find(q(MAIN, "alignment")).get("wrapText") == "1"
            ),
        }
    return result or {0: {"fill": ("none", ""), "signature": "default", "signature_no_fill": "default"}}


def workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.get("Id", ""): rel.get("Target", "")
        for rel in rels.findall(q(PKG_REL, "Relationship"))
    }
    output = []
    for sheet in workbook.iter(q(MAIN, "sheet")):
        target = targets.get(sheet.get(q(REL, "id"), ""), "")
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        output.append((sheet.get("name", ""), target.replace("\\", "/")))
    return output


def read_sheet(archive: zipfile.ZipFile, target: str, shared: list[str]) -> dict[str, dict[str, Any]]:
    root = ET.fromstring(archive.read(target))
    cells: dict[str, dict[str, Any]] = {}
    for cell in root.iter(q(MAIN, "c")):
        ref = cell.get("r", "")
        cell_type = cell.get("t", "")
        value_node = cell.find(q(MAIN, "v"))
        formula_node = cell.find(q(MAIN, "f"))
        inline = cell.find(q(MAIN, "is"))
        raw = value_node.text if value_node is not None and value_node.text is not None else ""
        if cell_type == "s" and raw:
            value = shared[int(raw)]
        elif cell_type == "inlineStr" and inline is not None:
            value = "".join(node.text or "" for node in inline.iter(q(MAIN, "t")))
        else:
            value = raw
        cells[ref] = {
            "value": value,
            "formula": formula_node.text if formula_node is not None else "",
            "style": int(cell.get("s", "0")),
        }
    cells["__conditional_ranges__"] = {
        "value": [node.get("sqref", "") for node in root.iter(q(MAIN, "conditionalFormatting"))],
        "formula": "",
        "style": 0,
    }
    auto_filter = root.find(q(MAIN, "autoFilter"))
    cells["__filter_ranges__"] = {
        "value": [auto_filter.get("ref", "")] if auto_filter is not None else [],
        "formula": "",
        "style": 0,
    }
    relationship_target = posixpath.join(
        posixpath.dirname(target), "_rels", posixpath.basename(target) + ".rels"
    )
    if relationship_target in archive.namelist():
        rel_root = ET.fromstring(archive.read(relationship_target))
        relationships = {
            rel.get("Id", ""): rel.get("Target", "")
            for rel in rel_root.findall(q(PKG_REL, "Relationship"))
        }
        for table_part in root.iter(q(MAIN, "tablePart")):
            raw_target = relationships.get(table_part.get(q(REL, "id"), ""), "")
            table_target = posixpath.normpath(
                posixpath.join(posixpath.dirname(target), raw_target)
            )
            if table_target in archive.namelist():
                table = ET.fromstring(archive.read(table_target))
                cells["__filter_ranges__"]["value"].append(table.get("ref", ""))
    cells["__row_attributes__"] = {
        "value": {
            int(row.get("r", "0")): dict(row.attrib)
            for row in root.iter(q(MAIN, "row"))
            if row.get("r", "").isdigit()
        },
        "formula": "",
        "style": 0,
    }
    column_widths: list[dict[str, str]] = []
    for column in root.iter(q(MAIN, "col")):
        column_widths.append(dict(column.attrib))
    cells["__column_widths__"] = {
        "value": column_widths,
        "formula": "",
        "style": 0,
    }
    return cells


def load_workbook(path: Path) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[int, dict[str, Any]]]:
    if not path.is_file():
        raise CatalogError(f"Workbook does not exist: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            shared = read_shared_strings(archive)
            styles = read_styles(archive)
            sheets = {name: read_sheet(archive, target, shared) for name, target in workbook_sheets(archive)}
            workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
            sheet_names = list(sheets)
            for defined_name in workbook_root.iter(q(MAIN, "definedName")):
                if defined_name.get("name") != "_xlnm.Print_Area":
                    continue
                local_index = int(defined_name.get("localSheetId", "0"))
                if 0 <= local_index < len(sheet_names):
                    sheets[sheet_names[local_index]]["__print_area__"] = {
                        "value": defined_name.text or "",
                        "formula": "",
                        "style": 0,
                    }
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, ValueError) as exc:
        raise CatalogError(f"Invalid or unsupported XLSX workbook {path}: {exc}") from exc
    if not sheets:
        raise CatalogError(f"Workbook has no worksheets: {path}")
    return sheets, styles


def find_catalog_sheet(sheets: dict[str, dict[str, dict[str, Any]]]) -> tuple[str, dict[str, dict[str, Any]], int]:
    for name, cells in sheets.items():
        for ref, cell in cells.items():
            match = CELL_RE.match(ref)
            if match and match.group(1) == "D" and str(cell["value"]).strip().upper() == "LOCATION":
                row = int(match.group(2))
                if str(cells.get(f"H{row}", {}).get("value", "")).strip().upper() == "HISTORY/INFO":
                    return name, cells, row
    raise CatalogError("Could not locate a catalog header row with D=LOCATION and H=HISTORY/INFO")


def relevant_cells(cells: dict[str, dict[str, Any]], max_col: int = 9) -> dict[str, dict[str, Any]]:
    return {
        ref: value
        for ref, value in cells.items()
        if (match := CELL_RE.match(ref)) and col_number(match.group(1)) <= max_col
    }


def is_yellow(fill: tuple[str, str]) -> bool:
    pattern, color = fill
    return pattern == "solid" and color.endswith("FFFF00")


def is_no_fill(fill: tuple[str, str]) -> bool:
    pattern, color = fill
    return pattern in {"", "none"} or not color


def range_covers(reference: str, *, row: int, column: int) -> bool:
    normalized = reference.replace("$", "").strip()
    if "!" in normalized:
        normalized = normalized.rsplit("!", 1)[1]
    match = RANGE_RE.fullmatch(normalized)
    if not match:
        return False
    start_column, start_row, end_column, end_row = match.groups()
    return (
        col_number(start_column) <= column <= col_number(end_column)
        and int(start_row) <= row <= int(end_row)
    )


def load_current_ledger(path: Path, intake_id: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"intake_id", "item_id", "decision"}
        if required - set(reader.fieldnames or []):
            raise CatalogError("Ledger is missing intake_id, item_id, or decision")
        rows = [row for row in reader if row.get("intake_id") == intake_id]
    if not rows:
        raise CatalogError(f"Ledger has no rows for intake_id={intake_id!r}")
    return rows


def verify(args: argparse.Namespace) -> dict[str, Any]:
    builder_verification: dict[str, Any] | None = None
    retained_last_row = 0
    final_row_from_builder = 0
    if args.builder_verification:
        builder_verification = json.loads(args.builder_verification.read_text(encoding="utf-8-sig"))
        expected_hashes = {
            "template_sha256": sha256_file(args.template),
            "catalog_sha256": sha256_file(args.catalog),
            "exceptions_sha256": sha256_file(args.exceptions),
        }
        required_contract = {
            "retained_locations_preserved": True,
            "retained_displayed_fills_preserved": True,
            "retained_fill_method": "excel-materialized-format-snapshot",
            "new_location": "Storage",
        }
        if builder_verification.get("status") != "PASS" or any(
            builder_verification.get(key) != value for key, value in expected_hashes.items()
        ) or any(
            builder_verification.get(key) != value for key, value in required_contract.items()
        ):
            raise CatalogError("Excel builder verification is missing, stale, or failed")
        try:
            retained_last_row = int(builder_verification["retained_last_row"])
            first_new_row = int(builder_verification["first_new_row"])
            final_row_from_builder = int(builder_verification["final_row"])
            new_item_count = int(builder_verification["new_item_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogError("Excel builder verification has invalid row bounds") from exc
        if (
            retained_last_row < 1
            or first_new_row != retained_last_row + 1
            or new_item_count < 1
            or final_row_from_builder != first_new_row + new_item_count - 1
            or set(builder_verification.get("actions", [])) != ACTIONS
        ):
            raise CatalogError("Excel builder verification has inconsistent row or action bounds")
    template_sheets, template_styles = load_workbook(args.template)
    catalog_sheets, catalog_styles = load_workbook(args.catalog)
    exception_sheets, _ = load_workbook(args.exceptions)
    template_name, template_cells, template_header = find_catalog_sheet(template_sheets)
    catalog_name, catalog_cells, catalog_header = find_catalog_sheet(catalog_sheets)
    if template_name != catalog_name or template_header != catalog_header:
        raise CatalogError("Catalog sheet name or header row changed from the template")
    if str(catalog_cells.get(f"J{catalog_header}", {}).get("value", "")).strip() != "RECOMMENDED ACTION":
        raise CatalogError("Catalog column J header must be RECOMMENDED ACTION")

    template_has_action_column = str(template_cells.get(f"J{template_header}", {}).get("value", "")).strip() == "RECOMMENDED ACTION"
    for ref, expected in relevant_cells(template_cells, max_col=10 if template_has_action_column else 9).items():
        row_number = int("".join(char for char in ref if char.isdigit()))
        if builder_verification and row_number > retained_last_row:
            continue
        actual = catalog_cells.get(ref, {"value": "", "formula": "", "style": 0})
        expected_style = template_styles.get(expected["style"], {}).get("signature")
        actual_style = catalog_styles.get(actual["style"], {}).get("signature")
        formula_extension = bool(
            builder_verification
            and row_number < template_header
            and expected["formula"]
            and actual["formula"]
            and is_allowed_formula_extension(
                str(expected["formula"]),
                str(actual["formula"]),
                retained_last_row,
                final_row_from_builder,
            )
        )
        values_match = (actual["value"], actual["formula"]) == (expected["value"], expected["formula"])
        # Table styles are materialized into direct cell styles by the Excel
        # builder so new SELL rows can be visibly unfilled. The builder's
        # hash-bound bulk format snapshot verifies retained appearance; this
        # independent gate still compares every retained value and formula.
        style_changed_without_builder = not builder_verification and actual_style != expected_style
        if (not values_match and not formula_extension) or style_changed_without_builder:
            raise CatalogError(f"Retained template cell changed: {catalog_name}!{ref}")

    ledger_rows = load_current_ledger(args.ledger, args.intake_id)
    payload_rows: list[dict[str, Any]] = []
    if args.catalog_payload:
        payload = json.loads(args.catalog_payload.read_text(encoding="utf-8-sig"))
        payload_rows = payload.get("catalog_rows", [])
        if payload.get("intake_id") != args.intake_id or not isinstance(payload_rows, list):
            raise CatalogError("Catalog payload does not match the requested intake")
        if builder_verification and builder_verification.get("payload_sha256") != sha256_file(args.catalog_payload):
            raise CatalogError("Excel builder verification is stale for the catalog payload")
    action_rows: list[tuple[int, str, str]] = []
    first_current_row = int(builder_verification["first_new_row"]) if builder_verification else catalog_header + 1
    for ref, cell in catalog_cells.items():
        match = CELL_RE.match(ref)
        if match and match.group(1) == "J" and int(match.group(2)) >= first_current_row:
            action = str(cell["value"]).strip().upper()
            if action:
                if action not in ACTIONS:
                    raise CatalogError(f"Invalid RECOMMENDED ACTION {action!r} at {ref}")
                row_number = int(match.group(2))
                item_id = str(catalog_cells.get(f"B{row_number}", {}).get("value", "")).strip()
                if not item_id:
                    raise CatalogError(f"Current-intake action row {row_number} is missing its column B item ID")
                action_rows.append((row_number, action, item_id))
    action_rows.sort()
    if len({item_id for _, _, item_id in action_rows}) != len(action_rows):
        raise CatalogError("Catalog has duplicate current-intake item IDs in column B")
    actual_actions = {item_id: action for _, action, item_id in action_rows}
    if payload_rows:
        ledger_actions = {row["item_id"]: row["decision"] for row in ledger_rows}
        payload_ids = {str(row.get("item_id", "")): str(row.get("recommended_action", "")) for row in payload_rows}
        if payload_ids != ledger_actions:
            raise CatalogError("Catalog payload item IDs and decisions do not match the current ledger")
        expected_actions = {str(row.get("sku", "")): str(row.get("recommended_action", "")) for row in payload_rows}
        if "" in expected_actions or len(expected_actions) != len(payload_rows):
            raise CatalogError("Catalog payload contains blank or duplicate SKUs")
    else:
        expected_actions = {row["item_id"]: row["decision"] for row in ledger_rows}
    if actual_actions != expected_actions:
        raise CatalogError("Catalog action rows do not match current-intake ledger item IDs and decisions")

    for row_number, action, _ in action_rows:
        if str(catalog_cells.get(f"D{row_number}", {}).get("value", "")).strip() != "Storage":
            raise CatalogError(f"New row {row_number} must use Storage in column D")
        if not str(catalog_cells.get(f"H{row_number}", {}).get("value", "")).strip():
            raise CatalogError(f"New row {row_number} is missing HISTORY/INFO")
        if str(catalog_cells.get(f"I{row_number}", {}).get("value", "")).strip():
            raise CatalogError(f"New row {row_number} must leave column I blank")
        for column in "ABCDEFGHIJ":
            style_id = int(catalog_cells.get(f"{column}{row_number}", {}).get("style", 0))
            fill = catalog_styles.get(style_id, {"fill": ("unknown", "")})["fill"]
            if action in ATTENTION_ACTIONS and not is_yellow(fill):
                raise CatalogError(f"{action} row {row_number} must be solid yellow across A:J")
            if action == "SELL" and not is_no_fill(fill):
                raise CatalogError(f"SELL row {row_number} must have no direct fill across A:J")
        history_style = int(catalog_cells.get(f"H{row_number}", {}).get("style", 0))
        if not catalog_styles.get(history_style, {}).get("wrap_text", False):
            raise CatalogError(f"HISTORY/INFO must be wrapped on new row {row_number}")

    final_row = max(row for row, _, _ in action_rows)
    filter_ranges = catalog_cells.get("__filter_ranges__", {}).get("value", [])
    if not any(range_covers(reference, row=final_row, column=10) for reference in filter_ranges):
        raise CatalogError("Catalog table or filter range must extend through column J and the final row")
    print_area = str(catalog_cells.get("__print_area__", {}).get("value", ""))
    if not range_covers(print_area, row=final_row, column=10):
        raise CatalogError("Catalog print area must extend through column J and the final row")
    column_widths = catalog_cells.get("__column_widths__", {}).get("value", [])
    if not any(
        int(column.get("min", "0")) <= 10 <= int(column.get("max", "0"))
        and float(column.get("width", "0")) > 0
        for column in column_widths
    ):
        raise CatalogError("Catalog column J must have an explicit usable width")

    for sheet_name, cells in catalog_sheets.items():
        for ref, cell in cells.items():
            if ref != "__conditional_ranges__" and str(cell.get("value", "")).upper() in FORMULA_ERRORS:
                raise CatalogError(f"Formula error {cell['value']} at {sheet_name}!{ref}")
    template_cf = {
        name: cells.get("__conditional_ranges__", {}).get("value", [])
        for name, cells in template_sheets.items()
    }
    catalog_cf = {
        name: cells.get("__conditional_ranges__", {}).get("value", [])
        for name, cells in catalog_sheets.items()
    }
    expected_cf = template_cf
    if builder_verification:
        expected_cf = {
            name: retained_conditional_ranges(ranges, retained_last_row)
            for name, ranges in template_cf.items()
        }
        catalog_cf = {
            name: sorted(ranges)
            for name, ranges in catalog_cf.items()
        }
    if catalog_cf != expected_cf:
        raise CatalogError(
            "Catalog conditional-format ranges changed beyond the retained-row boundary; "
            "disposition fills must be direct"
        )

    exception_text = {
        str(cell["value"]).strip()
        for cells in exception_sheets.values()
        for ref, cell in cells.items()
        if ref != "__conditional_ranges__" and str(cell["value"]).strip()
    }
    if not exception_text:
        raise CatalogError("Exceptions workbook must contain headers even when it has no rows")
    for row in ledger_rows:
        if row["decision"] in {"REVIEW", "CONFIRM DONATION"} and row["item_id"] not in exception_text:
            raise CatalogError(f"Exceptions workbook is missing item_id {row['item_id']}")

    return {
        "version": 1,
        "status": "PASS",
        "intake_id": args.intake_id,
        "template": str(args.template.resolve()),
        "template_sha256": sha256_file(args.template),
        "catalog": str(args.catalog.resolve()),
        "catalog_sha256": sha256_file(args.catalog),
        "exceptions": str(args.exceptions.resolve()),
        "exceptions_sha256": sha256_file(args.exceptions),
        "ledger": str(args.ledger.resolve()),
        "ledger_sha256": sha256_file(args.ledger),
        "builder_verification_sha256": sha256_file(args.builder_verification) if args.builder_verification else "",
        "catalog_payload_sha256": sha256_file(args.catalog_payload) if args.catalog_payload else "",
        "catalog_sheet": catalog_name,
        "header_row": catalog_header,
        "current_intake_rows": len(action_rows),
        "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify BFG catalog workbook content and formatting contracts.")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--exceptions", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--builder-verification", type=Path)
    parser.add_argument("--catalog-payload", type=Path, help="Map stable item IDs to catalog SKUs")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = verify(args)
        atomic_write_json(args.output, result)
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
