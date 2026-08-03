#!/usr/bin/env python3
"""Block batch completion until every required BFG deliverable exists."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from bfg_integrity import contained_path, photo_set_digest, sha256_file
from categorized_inventory_gate import (
    CategorizedInventoryError,
    digest_categorized_folder,
)


CATEGORIZED_PATTERN = re.compile(r"^Categorized Inventory \d{4}-\d{2}-\d{2}$")
REQUIRED_XLSX_MEMBERS = {"[Content_Types].xml", "xl/workbook.xml"}


class DeliveryError(ValueError):
    """Raised when a batch is missing or has invalid deliverables."""


def read_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise DeliveryError("Manifest is not a supported version 1 manifest")
    if not isinstance(manifest.get("photos"), list):
        raise DeliveryError("Manifest has no valid photos array")
    return manifest


def validate_xlsx(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"Missing {label}: {path}")
        return
    if path.suffix.casefold() != ".xlsx":
        errors.append(f"{label} must be an .xlsx file: {path}")
        return
    if path.stat().st_size == 0:
        errors.append(f"{label} is empty: {path}")
        return
    try:
        with zipfile.ZipFile(path) as archive:
            missing = REQUIRED_XLSX_MEMBERS - set(archive.namelist())
    except zipfile.BadZipFile:
        errors.append(f"{label} is not a valid XLSX container: {path}")
        return
    if missing:
        errors.append(
            f"{label} is missing required workbook members: {', '.join(sorted(missing))}"
        )


def validate_delivery(
    *,
    client_folder: Path,
    manifest_path: Path,
    ledger_path: Path,
    categorized_folder: Path,
    catalog_path: Path | None,
    exceptions_path: Path | None,
    preflight_lock_path: Path,
    catalog_verification_path: Path,
) -> dict[str, Any]:
    if not client_folder.is_dir():
        raise DeliveryError(f"Client folder does not exist: {client_folder}")
    manifest = read_manifest(manifest_path)
    client_name = client_folder.name
    expected_catalog = client_folder / f"{client_name} New Catalog.xlsx"
    expected_exceptions = client_folder / f"{client_name} Exceptions.xlsx"
    catalog = catalog_path or expected_catalog
    exceptions = exceptions_path or expected_exceptions
    errors: list[str] = []

    preflight = read_bound_record(preflight_lock_path, "preflight lock", errors)
    verification = read_bound_record(
        catalog_verification_path, "catalog verification", errors
    )

    if catalog.resolve() != expected_catalog.resolve():
        errors.append(f"Catalog must use exact path: {expected_catalog}")
    if exceptions.resolve() != expected_exceptions.resolve():
        errors.append(f"Exceptions workbook must use exact path: {expected_exceptions}")
    if not CATEGORIZED_PATTERN.fullmatch(categorized_folder.name):
        errors.append(
            "Categorized folder must be named 'Categorized Inventory YYYY-MM-DD'"
        )

    validate_xlsx(catalog, "New Catalog workbook", errors)
    validate_xlsx(exceptions, "Exceptions workbook", errors)

    template_text = str(manifest.get("catalog_template", "")).strip()
    if template_text:
        template = Path(template_text)
        if catalog.resolve() == template.resolve():
            errors.append("New Catalog path cannot overwrite the source template")
        elif catalog.is_file() and template.is_file() and sha256_file(catalog) == sha256_file(template):
            errors.append("New Catalog is byte-for-byte identical to the source template")

    manifest_digest = str(manifest.get("photo_set_digest", ""))
    try:
        calculated_manifest_digest = photo_set_digest(manifest["photos"])
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"Manifest photo hash records are invalid: {exc}")
        calculated_manifest_digest = ""
    if calculated_manifest_digest != manifest_digest:
        errors.append("Manifest photo_set_digest does not match its photo records")

    if preflight:
        if preflight.get("status") != "CONFIRMED":
            errors.append("Preflight lock is not CONFIRMED")
        bindings = {
            "client_id": manifest.get("client_id"),
            "intake_id": manifest.get("intake_id"),
            "source_folder": manifest.get("source_folder"),
            "catalog_template": manifest.get("catalog_template"),
            "catalog_template_sha256": manifest.get("catalog_template_sha256"),
            "photo_set_digest": manifest_digest,
            "catalog_rules_digest": manifest.get("catalog_rules_digest"),
        }
        for field, expected in bindings.items():
            if preflight.get(field) != expected:
                errors.append(f"Preflight {field} does not match the manifest")
        confirmed_paths = preflight.get("deliverable_paths", {})
        if not isinstance(confirmed_paths, dict):
            errors.append("Preflight deliverable_paths is invalid")
        else:
            path_bindings = {
                "catalog": catalog.resolve(),
                "exceptions": exceptions.resolve(),
                "categorized": categorized_folder.resolve(),
                "records": manifest_path.parent.resolve(),
            }
            for field, expected in path_bindings.items():
                recorded = str(confirmed_paths.get(field, ""))
                if not recorded or Path(recorded).resolve() != expected:
                    errors.append(f"Preflight deliverable path {field} does not match this delivery")
        if manifest.get("preflight_lock_sha256") != sha256_file(preflight_lock_path):
            errors.append("Manifest preflight lock hash is stale or incorrect")

    photos = manifest["photos"]
    allowed_final_statuses = {"assigned", "excluded", "separator"}
    invalid_statuses = [
        str(photo.get("relative_path", ""))
        for photo in photos
        if str(photo.get("status", "")).strip() not in allowed_final_statuses
    ]
    if invalid_statuses:
        errors.append(
            f"Manifest has {len(invalid_statuses)} non-final photo statuses"
        )

    assigned = [photo for photo in photos if photo.get("status") == "assigned"]
    if not assigned:
        errors.append("Manifest has no assigned inventory photos")
    expected_copies: set[Path] = set()
    expected_hashes: dict[str, Path] = {}
    for photo in assigned:
        group_id = str(photo.get("group_id", "")).strip()
        relative_path = str(photo.get("relative_path", "")).strip()
        if not group_id or not relative_path:
            errors.append("Assigned photo has a blank group_id or relative_path")
            continue
        try:
            destination = contained_path(
                categorized_folder,
                str(Path(group_id) / Path(relative_path).name),
                label="categorized destination",
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if destination in expected_copies:
            errors.append(f"Duplicate categorized destination: {destination}")
        expected_copies.add(destination)
        expected_hash = str(photo.get("sha256", "")).casefold()
        if len(expected_hash) == 64:
            prior_destination = expected_hashes.get(expected_hash)
            if prior_destination is not None:
                errors.append(
                    "Manifest assigns identical photo content to multiple categorized files: "
                    f"{prior_destination} and {destination}"
                )
            else:
                expected_hashes[expected_hash] = destination
        if not destination.is_file():
            errors.append(f"Missing categorized photo: {destination}")
        else:
            if len(expected_hash) != 64 or sha256_file(destination) != expected_hash:
                errors.append(f"Categorized photo content does not match manifest: {destination}")

    actual_files = (
        [path for path in categorized_folder.rglob("*") if path.is_file()]
        if categorized_folder.is_dir()
        else []
    )
    if not categorized_folder.is_dir():
        errors.append(f"Missing categorized inventory folder: {categorized_folder}")
    elif len(actual_files) != len(expected_copies):
        errors.append(
            f"Categorized photo count {len(actual_files)} does not match assigned count {len(expected_copies)}"
        )

    ledger_rows: list[dict[str, str]] = []
    if not ledger_path.is_file():
        errors.append(f"Missing canonical client ledger: {ledger_path}")
    else:
        with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "intake_id",
                "item_id",
                "decision",
                "listing_status",
                "human_review_status",
            }
            missing_headers = required - set(reader.fieldnames or [])
            if missing_headers:
                errors.append(
                    "Ledger is missing headers: " + ", ".join(sorted(missing_headers))
                )
            ledger_rows = list(reader)

    intake_id = str(manifest.get("intake_id", "")).strip()
    current_rows = [row for row in ledger_rows if row.get("intake_id") == intake_id]
    if ledger_rows and not current_rows:
        errors.append(f"Ledger has no rows for intake_id={intake_id!r}")
    item_ids = [row.get("item_id", "") for row in current_rows]
    if len(item_ids) != len(set(item_ids)):
        errors.append("Ledger has duplicate item_id values for the current intake")

    allowed_actions = {"SELL", "DONATE", "REVIEW", "CONFIRM DONATION"}
    invalid_actions = [row.get("decision", "") for row in current_rows if row.get("decision") not in allowed_actions]
    if invalid_actions:
        errors.append("Ledger has invalid current-intake recommended actions")

    if verification:
        if verification.get("status") != "PASS":
            errors.append("Catalog verification status is not PASS")
        expected_hashes = {
            "template_sha256": sha256_file(Path(template_text)) if template_text and Path(template_text).is_file() else "",
            "catalog_sha256": sha256_file(catalog) if catalog.is_file() else "",
            "exceptions_sha256": sha256_file(exceptions) if exceptions.is_file() else "",
            "ledger_sha256": sha256_file(ledger_path) if ledger_path.is_file() else "",
        }
        for field, expected in expected_hashes.items():
            if verification.get(field) != expected:
                errors.append(f"Catalog verification {field} is stale or incorrect")
        expected_paths = {
            "template": Path(template_text).resolve() if template_text else None,
            "catalog": catalog.resolve(),
            "exceptions": exceptions.resolve(),
            "ledger": ledger_path.resolve(),
        }
        for field, expected in expected_paths.items():
            if expected is not None and Path(str(verification.get(field, ""))).resolve() != expected:
                errors.append(f"Catalog verification {field} path does not match this delivery")
        if verification.get("intake_id") != intake_id:
            errors.append("Catalog verification intake_id does not match the manifest")

    if errors:
        raise DeliveryError("\n".join(errors))
    return {
        "status": "PASS",
        "client_name": client_name,
        "intake_id": intake_id,
        "catalog": str(catalog.resolve()),
        "exceptions": str(exceptions.resolve()),
        "categorized_inventory": str(categorized_folder.resolve()),
        "assigned_photos": len(assigned),
        "categorized_photos": len(actual_files),
        "ledger_rows_for_intake": len(current_rows),
        "preflight_lock": str(preflight_lock_path.resolve()),
        "catalog_verification": str(catalog_verification_path.resolve()),
    }


def read_bound_record(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"Missing {label}: {path}")
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict) or value.get("version") != 1:
        errors.append(f"{label.capitalize()} is not a supported version 1 record")
        return {}
    return value


def validate_catalog_refresh(
    *,
    client_folder: Path,
    manifest_path: Path,
    ledger_path: Path,
    categorized_folder: Path,
    categorized_verification_path: Path,
    intake_id: str,
    catalog_path: Path | None,
    exceptions_path: Path | None,
    preflight_lock_path: Path,
    catalog_verification_path: Path,
) -> dict[str, Any]:
    """Validate a catalog-only legacy refresh without pretending photos were reprocessed."""
    if not client_folder.is_dir():
        raise DeliveryError(f"Client folder does not exist: {client_folder}")
    client_name = client_folder.name
    expected_catalog = client_folder / f"{client_name} New Catalog.xlsx"
    expected_exceptions = client_folder / f"{client_name} Exceptions.xlsx"
    catalog = catalog_path or expected_catalog
    exceptions = exceptions_path or expected_exceptions
    errors: list[str] = []
    preflight = read_bound_record(preflight_lock_path, "preflight lock", errors)
    verification = read_bound_record(
        catalog_verification_path, "catalog verification", errors
    )
    categorized_verification = read_bound_record(
        categorized_verification_path, "categorized verification", errors
    )
    try:
        categorized_summary = digest_categorized_folder(categorized_folder)
    except CategorizedInventoryError as exc:
        errors.append(str(exc))
        categorized_summary = {}

    if catalog.resolve() != expected_catalog.resolve():
        errors.append(f"Catalog must use exact path: {expected_catalog}")
    if exceptions.resolve() != expected_exceptions.resolve():
        errors.append(f"Exceptions workbook must use exact path: {expected_exceptions}")
    if categorized_folder.parent.resolve() != client_folder.resolve():
        errors.append("Categorized inventory must be directly inside the main client folder")
    if not CATEGORIZED_PATTERN.fullmatch(categorized_folder.name):
        errors.append(
            "Categorized folder must be named 'Categorized Inventory YYYY-MM-DD'"
        )
    validate_xlsx(catalog, "New Catalog workbook", errors)
    validate_xlsx(exceptions, "Exceptions workbook", errors)

    template_text = str(preflight.get("catalog_template", "")).strip()
    template = Path(template_text) if template_text else None
    if preflight:
        if preflight.get("status") != "CONFIRMED":
            errors.append("Preflight lock is not CONFIRMED")
        if preflight.get("workflow") != "legacy-catalog-refresh":
            errors.append("Preflight workflow is not legacy-catalog-refresh")
        if preflight.get("intake_id") != intake_id:
            errors.append("Preflight intake_id does not match this refresh")
        if not preflight.get("source_intake_id"):
            errors.append("Preflight source_intake_id is missing")
        if not preflight.get("source_ledger_sha256"):
            errors.append("Preflight source ledger hash is missing")
        if (
            preflight.get("catalog_rules", {}).get(
                "legacy_refresh_listing_authorized"
            )
            is not False
        ):
            errors.append("Preflight does not prohibit listing authorization")
        source_manifest_text = str(preflight.get("source_manifest", "")).strip()
        if source_manifest_text:
            if Path(source_manifest_text).resolve() != manifest_path.resolve():
                errors.append("Preflight source manifest path does not match")
            elif preflight.get("source_manifest_sha256") != sha256_file(
                manifest_path
            ):
                errors.append("Preflight source manifest hash is stale")
            if (
                preflight.get("catalog_rules", {}).get(
                    "legacy_refresh_requires_categorized_delivery"
                )
                is not True
            ):
                errors.append(
                    "Preflight does not require categorized inventory delivery"
                )
            recorded_categorized_verification = str(
                preflight.get("categorized_verification", "")
            )
            if (
                not recorded_categorized_verification
                or Path(recorded_categorized_verification).resolve()
                != categorized_verification_path.resolve()
            ):
                errors.append("Preflight categorized verification path does not match")
            elif preflight.get(
                "categorized_verification_sha256"
            ) != sha256_file(categorized_verification_path):
                errors.append("Preflight categorized verification hash is stale")
        if categorized_summary:
            if (
                categorized_verification.get("source_intake_id")
                != preflight.get("source_intake_id")
            ):
                errors.append(
                    "Categorized source manifest intake_id does not match the refresh source"
                )
            recorded_digest = str(
                preflight.get("source_categorized_digest", "")
            )
            if recorded_digest and recorded_digest != categorized_summary.get(
                "categorized_digest"
            ):
                errors.append("Preflight categorized inventory digest is stale")
        confirmed_paths = preflight.get("deliverable_paths", {})
        path_bindings = {
            "catalog": catalog.resolve(),
            "exceptions": exceptions.resolve(),
            "records": preflight_lock_path.parent.resolve(),
        }
        if not isinstance(confirmed_paths, dict):
            errors.append("Preflight deliverable_paths is invalid")
        else:
            for field, expected in path_bindings.items():
                recorded = str(confirmed_paths.get(field, ""))
                if not recorded or Path(recorded).resolve() != expected:
                    errors.append(
                        f"Preflight deliverable path {field} does not match this refresh"
                    )
            recorded_categorized = str(confirmed_paths.get("categorized", ""))
            if recorded_categorized:
                if Path(recorded_categorized).resolve() != categorized_folder.resolve():
                    errors.append(
                        "Preflight deliverable path categorized does not match this refresh"
                    )
            elif source_manifest_text:
                errors.append("Preflight categorized deliverable path is missing")
        if template and template.is_file():
            if preflight.get("catalog_template_sha256") != sha256_file(template):
                errors.append("Preflight catalog template hash is stale")
            if catalog.is_file() and sha256_file(catalog) == sha256_file(template):
                errors.append("New Catalog is byte-for-byte identical to the source template")
        else:
            errors.append("Preflight catalog template is missing")

    ledger_rows: list[dict[str, str]] = []
    if not ledger_path.is_file():
        errors.append(f"Missing canonical client ledger: {ledger_path}")
    else:
        with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
            ledger_rows = list(csv.DictReader(handle))
    current_rows = [row for row in ledger_rows if row.get("intake_id") == intake_id]
    if not current_rows:
        errors.append(f"Ledger has no rows for intake_id={intake_id!r}")
    item_ids = [row.get("item_id", "") for row in current_rows]
    if len(item_ids) != len(set(item_ids)):
        errors.append("Ledger has duplicate item_id values for the refresh intake")
    allowed_actions = {"SELL", "DONATE", "REVIEW", "CONFIRM DONATION"}
    if any(row.get("decision") not in allowed_actions for row in current_rows):
        errors.append("Ledger has invalid refresh recommended actions")
    if any(row.get("listing_status") == "READY" for row in current_rows):
        errors.append("Legacy catalog refresh cannot authorize READY listing status")
    if any(row.get("human_review_status") != "PENDING" for row in current_rows):
        errors.append("Legacy catalog refresh rows must remain human-review PENDING")

    if verification:
        if verification.get("status") != "PASS":
            errors.append("Catalog verification status is not PASS")
        expected_hashes = {
            "template_sha256": sha256_file(template) if template and template.is_file() else "",
            "catalog_sha256": sha256_file(catalog) if catalog.is_file() else "",
            "exceptions_sha256": sha256_file(exceptions) if exceptions.is_file() else "",
            "ledger_sha256": sha256_file(ledger_path) if ledger_path.is_file() else "",
        }
        for field, expected in expected_hashes.items():
            if verification.get(field) != expected:
                errors.append(f"Catalog verification {field} is stale or incorrect")
        expected_paths = {
            "template": template.resolve() if template else None,
            "catalog": catalog.resolve(),
            "exceptions": exceptions.resolve(),
            "ledger": ledger_path.resolve(),
        }
        for field, expected in expected_paths.items():
            if expected is not None and Path(
                str(verification.get(field, ""))
            ).resolve() != expected:
                errors.append(f"Catalog verification {field} path does not match")
        if verification.get("intake_id") != intake_id:
            errors.append("Catalog verification intake_id does not match the refresh")

    if categorized_verification and categorized_summary:
        if categorized_verification.get("status") != "PASS":
            errors.append("Categorized verification status is not PASS")
        expected_categorized = {
            "source_intake_id": preflight.get("source_intake_id"),
            "manifest_sha256": sha256_file(manifest_path),
            "categorized_digest": categorized_summary.get("categorized_digest"),
            "assigned_photo_count": categorized_summary.get(
                "assigned_photo_count"
            ),
            "group_count": categorized_summary.get("group_count"),
            "listing_authorized": False,
        }
        for field, expected in expected_categorized.items():
            if categorized_verification.get(field) != expected:
                errors.append(
                    f"Categorized verification {field} is stale or incorrect"
                )
        expected_paths = {
            "manifest": manifest_path.resolve(),
            "categorized_inventory": categorized_folder.resolve(),
        }
        for field, expected in expected_paths.items():
            if Path(str(categorized_verification.get(field, ""))).resolve() != expected:
                errors.append(f"Categorized verification {field} path does not match")

    if errors:
        raise DeliveryError("\n".join(errors))
    return {
        "status": "PASS",
        "workflow": "legacy-catalog-refresh",
        "client_name": client_name,
        "source_intake_id": preflight.get("source_intake_id", ""),
        "intake_id": intake_id,
        "catalog": str(catalog.resolve()),
        "exceptions": str(exceptions.resolve()),
        "categorized_inventory": str(categorized_folder.resolve()),
        "assigned_photos": int(categorized_summary.get("assigned_photo_count", 0)),
        "categorized_groups": int(categorized_summary.get("group_count", 0)),
        "ledger_rows_for_intake": len(current_rows),
        "listing_authorized": False,
        "preflight_lock": str(preflight_lock_path.resolve()),
        "catalog_verification": str(catalog_verification_path.resolve()),
        "categorized_verification": str(categorized_verification_path.resolve()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that the New Catalog, Exceptions workbook, categorized photos, "
            "manifest, and ledger are all present before reporting a batch complete."
        )
    )
    parser.add_argument(
        "--workflow",
        choices=("full-intake", "legacy-catalog-refresh"),
        default="full-intake",
    )
    parser.add_argument("--client-folder", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--categorized", type=Path)
    parser.add_argument("--intake-id")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--exceptions", type=Path)
    parser.add_argument("--preflight-lock", required=True, type=Path)
    parser.add_argument("--catalog-verification", required=True, type=Path)
    parser.add_argument("--categorized-verification", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.workflow == "legacy-catalog-refresh":
            if (
                not args.intake_id
                or not args.manifest
                or not args.categorized
                or not args.categorized_verification
            ):
                raise DeliveryError(
                    "legacy-catalog-refresh requires --intake-id, --manifest, "
                    "--categorized, and --categorized-verification"
                )
            summary = validate_catalog_refresh(
                client_folder=args.client_folder,
                manifest_path=args.manifest,
                ledger_path=args.ledger,
                categorized_folder=args.categorized,
                categorized_verification_path=args.categorized_verification,
                intake_id=args.intake_id,
                catalog_path=args.catalog,
                exceptions_path=args.exceptions,
                preflight_lock_path=args.preflight_lock,
                catalog_verification_path=args.catalog_verification,
            )
        else:
            if not args.manifest or not args.categorized:
                raise DeliveryError(
                    "full-intake requires --manifest and --categorized"
                )
            summary = validate_delivery(
                client_folder=args.client_folder,
                manifest_path=args.manifest,
                ledger_path=args.ledger,
                categorized_folder=args.categorized,
                catalog_path=args.catalog,
                exceptions_path=args.exceptions,
                preflight_lock_path=args.preflight_lock,
                catalog_verification_path=args.catalog_verification,
            )
    except (DeliveryError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
