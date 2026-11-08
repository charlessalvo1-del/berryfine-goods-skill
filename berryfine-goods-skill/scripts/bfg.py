#!/usr/bin/env python3
"""One-entry BFG diagnostics and fail-closed intake status audit."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
from collections import Counter
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
ALLOWED_DECISIONS = ("SELL", "DONATE", "CONFIRM DONATION", "REVIEW")
REQUIRED_RESEARCH_POLICY_VERSION = "2.6.0"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def doctor() -> dict[str, Any]:
    checks = {
        "python_supported": sys.version_info >= (3, 11),
        "python_version": platform.python_version(),
        "windows": platform.system() == "Windows",
        "powershell_available": bool(shutil.which("pwsh") or shutil.which("powershell")),
        "stdlib_sqlite_available": True,
    }
    checks["status"] = "PASS" if checks["python_supported"] and checks["powershell_available"] else "FAIL"
    checks["excel_builder_note"] = "Run catalog_builder.ps1 only on a Windows PC with desktop Excel; otherwise use the Codex spreadsheet workflow."
    return checks


def summarize_dispositions(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Create the mandatory, reconciled end-of-run state summary."""
    decisions = Counter(str(row.get("decision", "")).strip().upper() for row in rows)
    item_ids = [str(row.get("item_id", "")).strip() for row in rows]
    total = len(rows)
    allowed_total = sum(decisions[action] for action in ALLOWED_DECISIONS)
    pending = sum(
        str(row.get("human_review_status", "")).strip().upper() == "PENDING"
        for row in rows
    )
    return {
        "total_items": total,
        "sell": decisions["SELL"],
        "donate": decisions["DONATE"],
        "confirm_donation": decisions["CONFIRM DONATION"],
        "review": decisions["REVIEW"],
        "needs_owner_attention": decisions["CONFIRM DONATION"] + decisions["REVIEW"],
        "human_review_pending": pending,
        "invalid_decision_count": total - allowed_total,
        "duplicate_item_id_count": len(item_ids) - len(set(item_ids)),
        "reconciled": allowed_total == total and len(item_ids) == len(set(item_ids)),
    }


def resolve_ledger_path(records: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    iteration_copy = records / "client-inventory.csv"
    canonical = records.parent / "client-inventory.csv"
    return iteration_copy if iteration_copy.is_file() else canonical


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
    ledger_path = resolve_ledger_path(records, args.ledger)
    artifacts["ledger"] = str(ledger_path)
    disposition_summary = summarize_dispositions([])
    if not ledger_path.is_file():
        blockers.append({"code": "MISSING_LEDGER", "artifact": "ledger", "message": f"Missing client inventory ledger: {ledger_path}"})
    else:
        with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required_headers = {"intake_id", "item_id", "decision", "human_review_status"}
            missing_headers = required_headers - set(reader.fieldnames or [])
            if missing_headers:
                blockers.append({"code": "LEDGER_HEADERS_MISSING", "artifact": "ledger", "message": "Ledger is missing headers: " + ", ".join(sorted(missing_headers))})
                current_rows: list[dict[str, str]] = []
            else:
                current_rows = [row for row in reader if row.get("intake_id") == args.intake_id]
            disposition_summary = summarize_dispositions(current_rows)
            if not current_rows:
                blockers.append({"code": "LEDGER_INTAKE_MISSING", "artifact": "ledger", "message": f"Ledger has no rows for intake_id={args.intake_id!r}."})
            if disposition_summary["invalid_decision_count"]:
                blockers.append({"code": "INVALID_DISPOSITION_SUMMARY", "artifact": "ledger", "message": f"{disposition_summary['invalid_decision_count']} current-intake row(s) have an invalid disposition."})
            if disposition_summary["duplicate_item_id_count"]:
                blockers.append({"code": "DUPLICATE_LEDGER_ITEM", "artifact": "ledger", "message": f"{disposition_summary['duplicate_item_id_count']} duplicate current-intake item ID row(s) prevent a reconciled summary."})
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
    research_verification_path = records / REQUIRED_RECORDS["research_verification"]
    if research_verification_path.is_file():
        research_verification = read_json(research_verification_path)
        if research_verification.get("research_policy_version") != REQUIRED_RESEARCH_POLICY_VERSION:
            blockers.append({"code": "STALE_RESEARCH_POLICY", "artifact": "research_verification", "message": f"Research verification must pass policy version {REQUIRED_RESEARCH_POLICY_VERSION}."})
    categorized = args.categorized.resolve()
    artifacts["categorized"] = str(categorized)
    if categorized.parent != client_folder or not categorized.is_dir() or not categorized.name.startswith("Categorized Inventory "):
        blockers.append({"code": "CATEGORIZED_FOLDER_INVALID", "artifact": "categorized", "message": "The exact dated categorized folder must exist directly in the main client folder."})
    return {"version": 1, "status": "PASS" if not blockers else "FAIL", "client_name": client_name, "intake_id": args.intake_id, "client_folder": str(client_folder), "records": str(records), "disposition_summary": disposition_summary, "blocker_count": len(blockers), "blockers": blockers, "artifacts": artifacts}


def legacy_audit(args: argparse.Namespace) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    manifest = read_json(args.manifest)
    photos = manifest.get("photos", []) if isinstance(manifest.get("photos"), list) else []
    missing_hashes = sum(not str(photo.get("sha256", "")) for photo in photos)
    if missing_hashes:
        findings.append({"code": "PHOTO_HASHES_MISSING", "message": f"{missing_hashes} photo records lack SHA-256."})
    if not args.preflight.is_file():
        findings.append({"code": "PREFLIGHT_MISSING", "message": "Confirmed preflight lock is absent."})
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
    parser = argparse.ArgumentParser(description="BFG workflow diagnostics and status audit.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--client-folder", required=True, type=Path); audit_parser.add_argument("--records", required=True, type=Path); audit_parser.add_argument("--categorized", required=True, type=Path); audit_parser.add_argument("--client-name", required=True); audit_parser.add_argument("--intake-id", required=True); audit_parser.add_argument("--ledger", type=Path); audit_parser.add_argument("--output", type=Path)
    legacy = commands.add_parser("legacy-audit")
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
