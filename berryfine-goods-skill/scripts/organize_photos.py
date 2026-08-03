#!/usr/bin/env python3
"""Copy assigned intake photos into spreadsheet-matched item folders."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from bfg_integrity import contained_path, sha256_file


INVALID_FOLDER_CHARS = set('<>:"/\\|?*')
RESERVED_FOLDER_NAMES = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
}


class OrganizeError(ValueError):
    """Raised when organized output cannot be created safely."""


def read_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise OrganizeError("Manifest is not a supported version 1 manifest")
    if not isinstance(manifest.get("photos"), list):
        raise OrganizeError("Manifest has no valid photos array")
    return manifest


def validate_group_id(value: str) -> str:
    group_id = value.strip()
    if (
        not group_id
        or group_id in {".", ".."}
        or any(character in INVALID_FOLDER_CHARS for character in group_id)
        or group_id.endswith((".", " "))
        or group_id.split(".", 1)[0].upper() in RESERVED_FOLDER_NAMES
    ):
        raise OrganizeError(f"Unsafe or blank group_id: {value!r}")
    return group_id


def organize(manifest_path: Path, output_folder: Path, resume: bool) -> dict[str, int]:
    manifest = read_manifest(manifest_path)
    source_folder = Path(str(manifest.get("source_folder", "")))
    if not source_folder.is_dir():
        raise OrganizeError(f"Manifest source folder does not exist: {source_folder}")

    assignments: list[tuple[Path, Path, str]] = []
    assigned_hashes: dict[str, Path] = {}
    groups: set[str] = set()
    excluded = 0
    separators = 0
    for entry in manifest["photos"]:
        if not isinstance(entry, dict):
            raise OrganizeError("Manifest contains an invalid photo entry")
        relative_path = str(entry.get("relative_path", "")).strip()
        status = str(entry.get("status", "")).strip()
        if status == "excluded":
            if not str(entry.get("notes", "")).strip():
                raise OrganizeError(f"Excluded photo has no reason: {relative_path}")
            excluded += 1
            continue
        if status == "separator":
            separators += 1
            continue
        if status != "assigned":
            raise OrganizeError(f"Photo is not assigned: {relative_path}")
        group_id = validate_group_id(str(entry.get("group_id", "")))
        try:
            source = contained_path(source_folder, relative_path, label="manifest relative_path")
            destination = contained_path(
                output_folder,
                str(Path(group_id) / Path(relative_path).name),
                label="categorized destination",
            )
        except ValueError as exc:
            raise OrganizeError(str(exc)) from exc
        if not source.is_file():
            raise OrganizeError(f"Assigned source photo is missing: {source}")
        expected_hash = str(entry.get("sha256", "")).casefold()
        if len(expected_hash) != 64 or sha256_file(source) != expected_hash:
            raise OrganizeError(f"Assigned source photo does not match manifest hash: {source}")
        prior_destination = assigned_hashes.get(expected_hash)
        if prior_destination is not None:
            raise OrganizeError(
                "Manifest assigns identical photo content to multiple categorized files: "
                f"{prior_destination} and {destination}"
            )
        assigned_hashes[expected_hash] = destination
        assignments.append((source, destination, expected_hash))
        groups.add(group_id)

    if output_folder.exists() and any(output_folder.iterdir()) and not resume:
        raise OrganizeError(
            f"Output folder is not empty; use --resume to verify/copy safely: {output_folder}"
        )

    copied = 0
    verified = 0
    output_folder.mkdir(parents=True, exist_ok=True)
    for group_id in sorted(groups, key=str.casefold):
        (output_folder / group_id).mkdir(exist_ok=True)
    for source, destination, expected_hash in assignments:
        if destination.exists():
            if sha256_file(destination) != expected_hash:
                raise OrganizeError(f"Conflicting destination file: {destination}")
            verified += 1
            continue
        shutil.copy2(source, destination)
        if sha256_file(destination) != expected_hash:
            destination.unlink(missing_ok=True)
            raise OrganizeError(f"Copied photo failed hash verification: {destination}")
        copied += 1

    return {
        "groups": len(groups),
        "photos": len(assignments),
        "copied": copied,
        "verified_existing": verified,
        "excluded_skipped": excluded,
        "separators_skipped": separators,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy assigned manifest photos into one folder per item group."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Allow existing output and verify identical files before skipping them",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = organize(args.manifest, args.output, args.resume)
    except (OrganizeError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
