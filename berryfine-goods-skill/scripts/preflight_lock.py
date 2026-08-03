#!/usr/bin/env python3
"""Create and confirm an auditable BFG intake preflight lock."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, photo_set_digest, sha256_file, sha256_json
from photo_manifest import (
    DUPLICATE_RESOLUTION_POLICY,
    duplicate_group_count,
    duplicate_resolution_digest,
    make_entry,
    normalize_ignored_dirs,
    normalize_ignored_files,
    resolve_exact_duplicates,
    scan_folder,
)


CATALOG_RULES = {
    "actions": ["SELL", "DONATE", "REVIEW", "CONFIRM DONATION"],
    "sell_minimum": 50.0,
    "confirm_donation_minimum": 40.0,
    "confirm_donation_maximum": 49.99,
    "donate_maximum": 39.99,
    "new_location": "Storage",
    "history_column": "H",
    "preserved_column": "I",
    "recommended_action_column": "J",
    "attention_actions": ["DONATE", "REVIEW", "CONFIRM DONATION"],
    "attention_fill": "#FFFF00",
    "preserve_historical_rows_and_locations": True,
    "legacy_refresh_preserves_completed_research": True,
    "legacy_refresh_listing_authorized": False,
    "legacy_refresh_requires_categorized_delivery": True,
}
CONFIRMATION_TEXT = "I confirm the selected inputs, exclusions, and catalog rules."
WORKFLOWS = {"full-intake", "legacy-catalog-refresh"}


class PreflightError(ValueError):
    """Raised when a preflight lock is invalid or stale."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_lock(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise PreflightError("Preflight lock is not a supported version 1 record")
    return value


def create_lock(args: argparse.Namespace) -> dict[str, Any]:
    template = args.catalog_template.resolve()
    if not template.is_file():
        raise PreflightError(f"Catalog template does not exist: {template}")
    workflow = args.workflow
    if workflow not in WORKFLOWS:
        raise PreflightError(f"Unsupported workflow: {workflow}")

    source_ledger = ""
    source_ledger_sha256 = ""
    source_intake_id = ""
    source_manifest = ""
    source_manifest_sha256 = ""
    source_categorized = ""
    source_categorized_digest = ""
    linked_categorized_photo_count = 0
    linked_categorized_group_count = 0
    categorized_verification = ""
    categorized_verification_sha256 = ""
    if workflow == "legacy-catalog-refresh":
        if args.photos or args.ignore_dir or args.ignore_file:
            raise PreflightError(
                "Legacy catalog refresh must not select photos or photo exclusions"
            )
        if not args.source_ledger or not args.source_ledger.is_file():
            raise PreflightError(
                "Legacy catalog refresh requires an existing --source-ledger"
            )
        source_intake_id = args.source_intake_id.strip()
        if not source_intake_id:
            raise PreflightError(
                "Legacy catalog refresh requires --source-intake-id"
            )
        if (
            not args.categorized_verification
            or not args.categorized_verification.is_file()
        ):
            raise PreflightError(
                "Legacy catalog refresh requires --categorized-verification"
            )
        if not args.categorized_output:
            raise PreflightError(
                "Legacy catalog refresh requires --categorized-output in the main client folder"
            )
        try:
            categorized_summary = json.loads(
                args.categorized_verification.read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise PreflightError(
                f"Invalid categorized verification: {exc}"
            ) from exc
        if (
            not isinstance(categorized_summary, dict)
            or categorized_summary.get("version") != 1
            or categorized_summary.get("status") != "PASS"
            or categorized_summary.get("listing_authorized") is not False
        ):
            raise PreflightError(
                "Categorized verification must be a PASS version 1 non-listing record"
            )
        if categorized_summary.get("source_intake_id") != source_intake_id:
            raise PreflightError(
                "Categorized verification source intake does not match --source-intake-id"
            )
        verified_manifest = Path(str(categorized_summary.get("manifest", "")))
        if not verified_manifest.is_file() or categorized_summary.get(
            "manifest_sha256"
        ) != sha256_file(verified_manifest):
            raise PreflightError(
                "Categorized verification source manifest is missing or stale"
            )
        if (
            len(str(categorized_summary.get("categorized_digest", ""))) != 64
            or int(categorized_summary.get("assigned_photo_count", 0)) < 1
            or int(categorized_summary.get("group_count", 0)) < 1
        ):
            raise PreflightError(
                "Categorized verification has invalid digest or reconciliation counts"
            )
        if (
            Path(
                str(categorized_summary.get("categorized_inventory", ""))
            ).resolve()
            != args.categorized_output.resolve()
        ):
            raise PreflightError(
                "Categorized verification path does not match --categorized-output"
            )
        source_ledger = str(args.source_ledger.resolve())
        source_ledger_sha256 = sha256_file(args.source_ledger)
        source_manifest = str(categorized_summary.get("manifest", ""))
        source_manifest_sha256 = str(
            categorized_summary.get("manifest_sha256", "")
        )
        source_categorized = str(
            categorized_summary.get("categorized_inventory", "")
        )
        source_categorized_digest = str(
            categorized_summary["categorized_digest"]
        )
        linked_categorized_photo_count = int(
            categorized_summary["assigned_photo_count"]
        )
        linked_categorized_group_count = int(categorized_summary["group_count"])
        categorized_verification = str(args.categorized_verification.resolve())
        categorized_verification_sha256 = sha256_file(
            args.categorized_verification
        )
        photos_text = ""
        entries: list[dict[str, Any]] = []
        ignored_dirs: list[str] = []
        ignored_files: list[str] = []
        ignored_directory_report: list[dict[str, Any]] = []
        ignored_file_report: list[dict[str, Any]] = []
        duplicate_resolution: list[dict[str, str]] = []
    else:
        if not args.photos:
            raise PreflightError("Full intake requires --photos")
        photos = args.photos.resolve()
        if not photos.is_dir():
            raise PreflightError(f"Photo folder does not exist: {photos}")
        if not args.categorized_output:
            raise PreflightError("Full intake requires --categorized-output")
        ignored_dirs = normalize_ignored_dirs(args.ignore_dir)
        ignored_files = normalize_ignored_files(args.ignore_file)
        scanned_images, ignored_directory_report, ignored_file_report = scan_folder(
            photos, ignored_dirs, ignored_files
        )
        images, duplicate_resolution, content_hashes = resolve_exact_duplicates(
            scanned_images, photos
        )
        ignored_file_report.extend(duplicate_resolution)
        ignored_file_report.sort(key=lambda entry: entry["relative_path"].casefold())
        entries = [
            make_entry(path, photos, index, "sequence", content_hashes[path])
            for index, path in enumerate(images, 1)
        ]
        if not entries:
            raise PreflightError("Preflight found no included inventory images")
        photos_text = str(photos)
    paths = {
        "catalog": str(args.catalog_output.resolve()),
        "exceptions": str(args.exceptions_output.resolve()),
        "categorized": (
            str(args.categorized_output.resolve()) if args.categorized_output else ""
        ),
        "records": str(args.records_folder.resolve()),
    }
    lock = {
        "version": 1,
        "status": "PENDING",
        "workflow": workflow,
        "client_id": args.client_id.strip(),
        "client_name": args.client_name.strip(),
        "intake_id": args.intake_id.strip(),
        "source_folder": photos_text,
        "source_ledger": source_ledger,
        "source_ledger_sha256": source_ledger_sha256,
        "source_intake_id": source_intake_id,
        "source_manifest": source_manifest,
        "source_manifest_sha256": source_manifest_sha256,
        "source_categorized": source_categorized,
        "source_categorized_digest": source_categorized_digest,
        "linked_categorized_photo_count": linked_categorized_photo_count,
        "linked_categorized_group_count": linked_categorized_group_count,
        "categorized_verification": categorized_verification,
        "categorized_verification_sha256": categorized_verification_sha256,
        "catalog_template": str(template),
        "catalog_template_sha256": sha256_file(template),
        "photo_count": len(entries),
        "photo_set_digest": photo_set_digest(entries) if entries else "",
        "ignored_directory_rules": sorted(ignored_dirs),
        "ignored_file_rules": ignored_files,
        "ignored_directories": ignored_directory_report,
        "ignored_files": ignored_file_report,
        "duplicate_resolution_policy": DUPLICATE_RESOLUTION_POLICY,
        "duplicate_resolution_digest": duplicate_resolution_digest(
            duplicate_resolution
        ),
        "exact_duplicate_group_count": duplicate_group_count(
            duplicate_resolution
        ),
        "exact_duplicate_file_count": len(duplicate_resolution),
        "duplicate_resolution": duplicate_resolution,
        "deliverable_paths": paths,
        "catalog_rules": CATALOG_RULES,
        "catalog_rules_digest": sha256_json(CATALOG_RULES),
        "created_at": utc_now(),
        "confirmed_by": "",
        "confirmed_at": "",
        "confirmation_text": "",
        "user_confirmation": "",
    }
    if not lock["client_id"] or not lock["intake_id"]:
        raise PreflightError("client_id and intake_id are required")
    if args.output.exists() and not args.replace_pending:
        raise PreflightError(
            "Preflight lock already exists; use a new intake ID or --replace-pending"
        )
    if args.output.exists():
        existing = read_lock(args.output)
        if existing.get("status") == "CONFIRMED":
            raise PreflightError("A confirmed preflight lock is immutable")
    atomic_write_json(args.output, lock)
    return lock


def confirm_lock(args: argparse.Namespace) -> dict[str, Any]:
    lock = read_lock(args.lock)
    if lock.get("status") != "PENDING":
        raise PreflightError("Only a PENDING preflight lock can be confirmed")
    if not args.confirmed_by.strip():
        raise PreflightError("confirmed-by is required; do not invent an identity")
    if args.confirmation_text.strip() != CONFIRMATION_TEXT:
        raise PreflightError(f"confirmation-text must exactly equal: {CONFIRMATION_TEXT}")
    lock.update(
        status="CONFIRMED",
        confirmed_by=args.confirmed_by.strip(),
        confirmed_at=utc_now(),
        confirmation_text=CONFIRMATION_TEXT,
        user_confirmation=args.user_confirmation.strip(),
    )
    atomic_write_json(args.lock, lock)
    return lock


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or confirm an auditable BFG preflight lock.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Create a PENDING preflight record")
    create.add_argument("--output", required=True, type=Path)
    create.add_argument(
        "--workflow", choices=sorted(WORKFLOWS), default="full-intake"
    )
    create.add_argument("--photos", type=Path)
    create.add_argument("--source-ledger", type=Path)
    create.add_argument("--source-intake-id", default="")
    create.add_argument("--categorized-verification", type=Path)
    create.add_argument("--catalog-template", required=True, type=Path)
    create.add_argument("--client-id", required=True)
    create.add_argument("--client-name", required=True)
    create.add_argument("--intake-id", required=True)
    create.add_argument("--catalog-output", required=True, type=Path)
    create.add_argument("--exceptions-output", required=True, type=Path)
    create.add_argument("--categorized-output", type=Path)
    create.add_argument("--records-folder", required=True, type=Path)
    create.add_argument("--ignore-dir", action="append", default=[])
    create.add_argument("--ignore-file", action="append", default=[])
    create.add_argument("--replace-pending", action="store_true")
    confirm = sub.add_parser("confirm", help="Record the user's exact preflight confirmation")
    confirm.add_argument("--lock", required=True, type=Path)
    confirm.add_argument("--confirmed-by", required=True)
    confirm.add_argument("--confirmation-text", required=True)
    confirm.add_argument(
        "--user-confirmation",
        default="",
        help="Exact user message that authorized this confirmed preflight",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = create_lock(args) if args.command == "create" else confirm_lock(args)
    except (PreflightError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: output.get(key) for key in ("status", "client_id", "intake_id", "photo_count", "photo_set_digest", "exact_duplicate_group_count", "exact_duplicate_file_count", "duplicate_resolution_digest", "catalog_rules_digest", "confirmed_by", "confirmed_at")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
