#!/usr/bin/env python3
"""One-entry BFG diagnostics and fail-closed intake status audit."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json


REQUIRED_RECORDS = {
    "preflight": "preflight-lock.json",
    "manifest": "intake-manifest.json",
    "photo_quality": "photo-quality-verification.json",
    "review_provenance": "review-provenance.json",
    "grouping": "final-grouping.json",
    "grouping_reconciliation": "grouping-reconciliation.json",
    "research": "research-audit.json",
    "research_verification": "research-verification.json",
    "catalog_payload": "catalog-payload.json",
    "builder_verification": "catalog-builder-verification.json",
    "catalog_verification": "catalog-verification.json",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def stdlib_sqlite_available() -> bool:
    try:
        import sqlite3
    except ImportError:
        return False
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("SELECT 1").fetchone()
        connection.close()
    except sqlite3.Error:
        return False
    return True


def detect_desktop_excel() -> tuple[bool | None, str]:
    if platform.system() != "Windows":
        return False, "Desktop Excel COM registration is available only on Windows."

    try:
        import winreg
    except ImportError:
        return None, "Windows registry access is unavailable; desktop Excel detection is indeterminate."

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID") as key:
            clsid = str(winreg.QueryValueEx(key, None)[0]).strip()
        if not clsid:
            return None, "Excel.Application is registered without a CLSID; detection is indeterminate."
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as key:
            command = str(winreg.QueryValueEx(key, None)[0]).strip()
    except FileNotFoundError:
        return False, "No desktop Excel COM registration was found."
    except OSError as exc:
        return None, f"Desktop Excel registry detection was indeterminate: {exc}."

    executable_match = re.match(r'^\s*"([^"]+\.exe)"|^\s*(.+?\.exe)(?:\s|$)', command, re.IGNORECASE)
    executable = next(
        (group for group in executable_match.groups() if group), ""
    ) if executable_match else ""
    if not executable:
        return None, "Excel COM registration has no executable path; detection is indeterminate."
    if not Path(executable).is_file():
        return False, f"Excel COM registration points to a missing executable: {executable}."
    return True, f"Desktop Excel COM registration points to: {executable}."


def doctor() -> dict[str, Any]:
    excel_available, excel_detection = detect_desktop_excel()
    checks = {
        "python_supported": sys.version_info >= (3, 11),
        "python_version": platform.python_version(),
        "windows": platform.system() == "Windows",
        "powershell_available": bool(shutil.which("pwsh") or shutil.which("powershell")),
        "desktop_excel_available": excel_available,
        "desktop_excel_detection": excel_detection,
        "stdlib_sqlite_available": stdlib_sqlite_available(),
    }
    checks["core_workflow_ready"] = bool(
        checks["python_supported"] and checks["stdlib_sqlite_available"]
    )
    checks["exact_excel_builder_ready"] = bool(
        checks["core_workflow_ready"]
        and checks["windows"]
        and checks["powershell_available"]
        and checks["desktop_excel_available"] is True
    )
    checks["status"] = "PASS" if checks["core_workflow_ready"] else "FAIL"
    return checks


def audit(args: argparse.Namespace) -> dict[str, Any]:
    client_folder = args.client_folder.resolve()
    records = args.records.resolve()
    blockers: list[dict[str, str]] = []
    try:
        records.relative_to(client_folder)
        blockers.append({"code": "AUDIT_RECORDS_IN_CLIENT_FOLDER", "artifact": "records", "message": "Internal audit records must be outside the client delivery folder."})
    except ValueError:
        pass
    artifacts: dict[str, str] = {}
    for label, name in REQUIRED_RECORDS.items():
        path = records / name
        artifacts[label] = str(path)
        if not path.is_file():
            blockers.append({"code": "MISSING_RECORD", "artifact": label, "message": f"Missing {name}"})
    client_name = args.client_name
    catalog = client_folder / f"{client_name} New Catalog.xlsx"
    exceptions = client_folder / f"{client_name} Exceptions.xlsx"
    artifacts.update(catalog=str(catalog), exceptions=str(exceptions))
    for label, path in (("catalog", catalog), ("exceptions", exceptions)):
        if not path.is_file():
            blockers.append({"code": "MISSING_DELIVERABLE", "artifact": label, "message": f"Missing exact client-facing {path.name}"})
    preflight_path = records / "preflight-lock.json"
    if preflight_path.is_file():
        preflight = read_json(preflight_path)
        if preflight.get("status") != "CONFIRMED" or not preflight.get("confirmed_by"):
            blockers.append({"code": "PREFLIGHT_NOT_CONFIRMED", "artifact": "preflight", "message": "Preflight is not explicitly confirmed by a human."})
    manifest_path = records / "intake-manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        photos = manifest.get("photos", []) if isinstance(manifest.get("photos"), list) else []
        missing_hashes = sum(not str(photo.get("sha256", "")) for photo in photos)
        if missing_hashes:
            blockers.append({"code": "PHOTO_HASHES_MISSING", "artifact": "manifest", "message": f"{missing_hashes} manifest photo records lack SHA-256."})
        if manifest.get("intake_id") != args.intake_id:
            blockers.append({"code": "INTAKE_MISMATCH", "artifact": "manifest", "message": "Manifest intake ID does not match."})
        if not manifest.get("grouping_binding"):
            blockers.append({"code": "GROUPING_NOT_BOUND", "artifact": "manifest", "message": "Manifest lacks a deterministic final-grouping binding."})
    for label in ("photo_quality", "review_provenance", "grouping_reconciliation", "research_verification", "builder_verification", "catalog_verification"):
        path = records / REQUIRED_RECORDS[label]
        if path.is_file() and read_json(path).get("status") != "PASS":
            blockers.append({"code": "GATE_NOT_PASS", "artifact": label, "message": f"{path.name} does not contain PASS."})
    categorized = args.categorized.resolve()
    artifacts["categorized"] = str(categorized)
    if categorized.parent != client_folder or not categorized.is_dir() or not categorized.name.startswith("Categorized Inventory "):
        blockers.append({"code": "CATEGORIZED_FOLDER_INVALID", "artifact": "categorized", "message": "The exact dated categorized folder must exist directly in the main client folder."})
    return {"version": 1, "status": "PASS" if not blockers else "FAIL", "client_name": client_name, "intake_id": args.intake_id, "client_folder": str(client_folder), "records": str(records), "blocker_count": len(blockers), "blockers": blockers, "artifacts": artifacts}


def legacy_audit(args: argparse.Namespace) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    manifest = read_json(args.manifest)
    photos = manifest.get("photos", []) if isinstance(manifest.get("photos"), list) else []
    missing_hashes = sum(not str(photo.get("sha256", "")) for photo in photos)
    if missing_hashes:
        findings.append({"code": "PHOTO_HASHES_MISSING", "message": f"{missing_hashes} photo records lack SHA-256."})
    if not args.preflight.is_file():
        findings.append({"code": "PREFLIGHT_MISSING", "message": "Confirmed preflight lock is absent."})
    else:
        preflight = read_json(args.preflight)
        if preflight.get("status") != "CONFIRMED" or not preflight.get("confirmed_by"):
            findings.append({"code": "PREFLIGHT_NOT_CONFIRMED", "message": "Preflight exists but is not explicitly confirmed by a human."})
    if not manifest.get("grouping_binding"):
        findings.append({"code": "GROUPING_NOT_BOUND", "message": "Final grouping was not hash-bound back into the manifest."})
    with args.ledger.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == args.intake_id]
    for row in rows:
        value = float(row.get("decision_basis_value") or 0)
        if 40 <= value < 50 and row.get("decision") not in {"CONFIRM DONATION", "REVIEW"}:
            findings.append({"code": "BORDERLINE_POLICY_VIOLATION", "message": f"{row.get('item_id')} uses {row.get('decision')} at ${value:.2f}."})
        if row.get("decision") != "REVIEW" and (row.get("valuation_basis") == "insufficient_evidence" or row.get("valuation_confidence") == "low") and row.get("decision") in {"DONATE", "CONFIRM DONATION"}:
            findings.append({"code": "UNSUPPORTED_DISPOSITION", "message": f"{row.get('item_id')} has a disposal-sensitive decision without sufficient evidence."})
    if args.catalog.parent.resolve() != args.exceptions.parent.resolve():
        findings.append({"code": "SPLIT_DELIVERY_LOCATION", "message": "Catalog and Exceptions workbook are not in the same main client folder."})
    return {"version": 1, "status": "FAIL" if findings else "PASS", "intake_id": args.intake_id, "finding_count": len(findings), "findings": findings}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BFG workflow diagnostics and status audit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Full intake completion sequence (repository root):\n"
            "  python .\\berryfine-goods-skill\\scripts\\catalog_gate.py ...\n"
            "  python .\\berryfine-goods-skill\\scripts\\delivery_gate.py --workflow full-intake ...\n"
            "  python .\\berryfine-goods-skill\\scripts\\bfg.py audit ...\n"
            "Legacy refresh completion sequence (repository root):\n"
            "  python .\\berryfine-goods-skill\\scripts\\catalog_gate.py ...\n"
            "  python .\\berryfine-goods-skill\\scripts\\bfg.py legacy-audit ...\n"
            "  python .\\berryfine-goods-skill\\scripts\\delivery_gate.py --workflow legacy-catalog-refresh ...\n"
            "All applicable commands must return PASS. Audit does not replace delivery."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Report core Python readiness and separate exact Excel-builder readiness without launching Excel.")
    audit_parser = commands.add_parser("audit", help="Run the final aggregate full-intake artifact and workflow-status audit after delivery_gate.py passes.")
    audit_parser.add_argument("--client-folder", required=True, type=Path); audit_parser.add_argument("--records", required=True, type=Path); audit_parser.add_argument("--categorized", required=True, type=Path); audit_parser.add_argument("--client-name", required=True); audit_parser.add_argument("--intake-id", required=True); audit_parser.add_argument("--output", type=Path)
    legacy = commands.add_parser("legacy-audit", help="Validate retained evidence and policy-only refresh conditions; do not use the full-intake audit for a legacy refresh.")
    legacy.add_argument("--manifest", required=True, type=Path); legacy.add_argument("--preflight", required=True, type=Path); legacy.add_argument("--ledger", required=True, type=Path); legacy.add_argument("--intake-id", required=True); legacy.add_argument("--catalog", required=True, type=Path); legacy.add_argument("--exceptions", required=True, type=Path); legacy.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = doctor() if args.command == "doctor" else audit(args) if args.command == "audit" else legacy_audit(args)
        if getattr(args, "output", None):
            atomic_write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
