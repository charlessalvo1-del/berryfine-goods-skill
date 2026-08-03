#!/usr/bin/env python3
"""Verify a categorized photo set against its source intake manifest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, contained_path, sha256_file, sha256_json
from organize_photos import validate_group_id


class CategorizedInventoryError(ValueError):
    """Raised when a categorized photo delivery is incomplete or stale."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CategorizedInventoryError(f"Invalid source manifest: {exc}") from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("photos"), list)
    ):
        raise CategorizedInventoryError(
            "Source manifest is not a supported version 1 photo manifest"
        )
    return value


def digest_categorized_folder(categorized_folder: Path) -> dict[str, Any]:
    """Compute a destination-only digest for a previously verified delivery."""
    if not categorized_folder.is_dir():
        raise CategorizedInventoryError(
            f"Categorized inventory folder does not exist: {categorized_folder}"
        )
    files = sorted(
        (path for path in categorized_folder.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(categorized_folder).as_posix().casefold(),
    )
    entries = [
        {
            "relative_path": path.relative_to(categorized_folder).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    groups = [path for path in categorized_folder.iterdir() if path.is_dir()]
    return {
        "categorized_digest": sha256_json(entries),
        "assigned_photo_count": len(files),
        "group_count": len(groups),
    }


def validate_categorized_set(
    manifest_path: Path, categorized_folder: Path
) -> dict[str, Any]:
    """Hash-verify every assigned photo and reject missing or extra files."""
    manifest = read_manifest(manifest_path)
    source_folder = Path(str(manifest.get("source_folder", "")))
    if not source_folder.is_dir():
        raise CategorizedInventoryError(
            f"Manifest source folder does not exist: {source_folder}"
        )
    if not categorized_folder.is_dir():
        raise CategorizedInventoryError(
            f"Categorized inventory folder does not exist: {categorized_folder}"
        )

    expected_files: set[Path] = set()
    expected_hashes: dict[str, Path] = {}
    digest_entries: list[dict[str, Any]] = []
    groups: set[str] = set()
    assigned = 0
    excluded = 0
    separators = 0
    hash_bound = 0
    legacy_recomputed = 0

    for entry in manifest["photos"]:
        if not isinstance(entry, dict):
            raise CategorizedInventoryError("Manifest contains an invalid photo entry")
        status = str(entry.get("status", "")).strip()
        relative_path = str(entry.get("relative_path", "")).strip()
        if status == "excluded":
            if not str(entry.get("notes", "")).strip():
                raise CategorizedInventoryError(
                    f"Excluded photo has no reason: {relative_path}"
                )
            excluded += 1
            continue
        if status == "separator":
            separators += 1
            continue
        if status != "assigned":
            raise CategorizedInventoryError(
                f"Manifest photo is not in a final status: {relative_path}"
            )

        try:
            group_id = validate_group_id(str(entry.get("group_id", "")))
            source = contained_path(
                source_folder, relative_path, label="manifest relative_path"
            )
            destination = contained_path(
                categorized_folder,
                str(Path(group_id) / Path(relative_path).name),
                label="categorized destination",
            )
        except ValueError as exc:
            raise CategorizedInventoryError(str(exc)) from exc

        if destination in expected_files:
            raise CategorizedInventoryError(
                f"Duplicate categorized destination: {destination}"
            )
        if not source.is_file():
            raise CategorizedInventoryError(f"Assigned source photo is missing: {source}")
        if not destination.is_file():
            raise CategorizedInventoryError(
                f"Assigned categorized photo is missing: {destination}"
            )

        expected_bytes = entry.get("bytes")
        try:
            expected_size = int(expected_bytes)
        except (TypeError, ValueError) as exc:
            raise CategorizedInventoryError(
                f"Manifest photo has invalid byte count: {relative_path}"
            ) from exc
        if source.stat().st_size != expected_size:
            raise CategorizedInventoryError(
                f"Assigned source photo size changed: {source}"
            )
        if destination.stat().st_size != expected_size:
            raise CategorizedInventoryError(
                f"Categorized photo size does not match manifest: {destination}"
            )

        expected_hash = str(entry.get("sha256", "")).casefold()
        if len(expected_hash) == 64:
            hash_bound += 1
        else:
            # Historical manifests predate per-photo hashes. Recompute from the
            # immutable source and require the delivered copy to match it.
            expected_hash = sha256_file(source)
            legacy_recomputed += 1
        prior_destination = expected_hashes.get(expected_hash)
        if prior_destination is not None:
            raise CategorizedInventoryError(
                "Manifest assigns identical photo content to multiple categorized files: "
                f"{prior_destination} and {destination}"
            )
        expected_hashes[expected_hash] = destination
        if sha256_file(destination) != expected_hash:
            raise CategorizedInventoryError(
                f"Categorized photo content does not match source evidence: {destination}"
            )

        expected_files.add(destination)
        groups.add(group_id)
        assigned += 1
        digest_entries.append(
            {
                "relative_path": destination.relative_to(
                    categorized_folder.resolve()
                ).as_posix(),
                "bytes": expected_size,
                "sha256": expected_hash,
            }
        )

    actual_files = {path.resolve() for path in categorized_folder.rglob("*") if path.is_file()}
    expected_resolved = {path.resolve() for path in expected_files}
    missing = expected_resolved - actual_files
    extra = actual_files - expected_resolved
    if missing:
        raise CategorizedInventoryError(
            f"Categorized inventory is missing {len(missing)} assigned photo(s)"
        )
    if extra:
        raise CategorizedInventoryError(
            f"Categorized inventory contains {len(extra)} unexpected file(s)"
        )

    actual_groups = {
        path.name for path in categorized_folder.iterdir() if path.is_dir()
    }
    if actual_groups != groups:
        raise CategorizedInventoryError(
            "Categorized item-folder set does not exactly match manifest group IDs"
        )
    if assigned == 0 or not groups:
        raise CategorizedInventoryError(
            "Categorized inventory has no assigned photos or item folders"
        )

    digest_entries.sort(key=lambda value: value["relative_path"].casefold())
    return {
        "source_intake_id": str(manifest.get("intake_id", "")).strip(),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "categorized_inventory": str(categorized_folder.resolve()),
        "categorized_digest": sha256_json(digest_entries),
        "assigned_photo_count": assigned,
        "group_count": len(groups),
        "excluded_photo_count": excluded,
        "separator_photo_count": separators,
        "manifest_hash_mode": (
            "manifest-sha256"
            if legacy_recomputed == 0
            else "legacy-source-recomputed"
        ),
        "manifest_hash_bound_photos": hash_bound,
        "legacy_recomputed_photos": legacy_recomputed,
    }


def build_record(manifest_path: Path, categorized_folder: Path) -> dict[str, Any]:
    summary = validate_categorized_set(manifest_path, categorized_folder)
    return {
        "version": 1,
        "status": "PASS",
        **summary,
        "listing_authorized": False,
        "verified_at": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash-verify a categorized inventory against its source manifest."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--categorized", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise CategorizedInventoryError(
                f"Refusing to overwrite categorized verification: {args.output}"
            )
        record = build_record(args.manifest, args.categorized)
        atomic_write_json(args.output, record)
    except (CategorizedInventoryError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
