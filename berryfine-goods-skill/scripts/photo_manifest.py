#!/usr/bin/env python3
"""Create or refresh a resumable manifest for a large client photo intake."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, photo_set_digest, sha256_file, sha256_json


IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
PHOTO_STATUSES = {
    "pending",
    "assigned",
    "separator",
    "excluded",
    "unresolved",
    "missing",
}
PRESERVED_FIELDS = ("status", "item_id", "group_id", "role", "notes")
INTAKE_METHODS = {"auto", "folders", "sequence"}
DEFAULT_IGNORED_DIRS = {".git", "__pycache__", "categorized inventory", "output"}
DUPLICATE_RESOLUTION_POLICY = "sha256-prefer-non-copy-name-then-natural-path-v1"
COPY_STYLE_SUFFIX = re.compile(
    r"(?i)(?:\s*-\s*copy(?:\s*\(\d+\))?|\s*\(\d+\)|[_-]copy)$"
)


class ManifestError(ValueError):
    """Raised when manifest arguments or data are invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def natural_key(value: str) -> list[object]:
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    ]


def read_existing(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ManifestError("Existing manifest is not a supported version 1 manifest")
    photos = value.get("photos")
    if not isinstance(photos, list):
        raise ManifestError("Existing manifest has no valid photos array")
    return value


def normalize_ignored_dirs(values: list[str]) -> set[str]:
    normalized = {
        value.strip().replace("\\", "/").strip("/").casefold()
        for value in values
    }
    if "" in normalized:
        raise ManifestError("Ignored directory names cannot be blank")
    return {name.casefold() for name in DEFAULT_IGNORED_DIRS} | normalized


def normalize_ignored_files(values: list[str]) -> list[str]:
    normalized = [value.strip().replace("\\", "/") for value in values]
    if any(not value for value in normalized):
        raise ManifestError("Ignored file rules cannot be blank")
    return sorted(set(normalized), key=natural_key)


def is_ignored_directory(path: Path, root: Path, ignored_dirs: set[str]) -> bool:
    relative = path.relative_to(root).as_posix().strip("/").casefold()
    directory_name = path.name.casefold()
    return (
        relative in ignored_dirs
        or directory_name in ignored_dirs
        or directory_name.startswith("categorized inventory ")
    )


def scan_folder(
    folder: Path, ignored_dirs: set[str], ignored_file_rules: list[str]
) -> tuple[list[Path], list[dict[str, Any]], list[dict[str, str]]]:
    images: list[Path] = []
    ignored_directories: list[dict[str, Any]] = []
    ignored_files_report: list[dict[str, str]] = []

    for current_root, directory_names, filenames in os.walk(folder):
        current = Path(current_root)
        kept_directories: list[str] = []
        for directory_name in sorted(directory_names, key=natural_key):
            directory = current / directory_name
            if is_ignored_directory(directory, folder, ignored_dirs):
                file_count = sum(1 for path in directory.rglob("*") if path.is_file())
                image_count = sum(
                    1
                    for path in directory.rglob("*")
                    if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
                )
                ignored_directories.append(
                    {
                        "relative_path": directory.relative_to(folder).as_posix(),
                        "reason": "ignored_directory",
                        "file_count": file_count,
                        "image_count": image_count,
                    }
                )
            else:
                kept_directories.append(directory_name)
        directory_names[:] = kept_directories

        for filename in sorted(filenames, key=natural_key):
            path = current / filename
            relative_path = path.relative_to(folder).as_posix()
            ignored_by_rule = next(
                (
                    rule
                    for rule in ignored_file_rules
                    if fnmatch.fnmatchcase(relative_path.casefold(), rule.casefold())
                    or fnmatch.fnmatchcase(filename.casefold(), rule.casefold())
                ),
                None,
            )
            if ignored_by_rule:
                ignored_files_report.append(
                    {
                        "relative_path": relative_path,
                        "reason": "ignored_file_rule",
                        "rule": ignored_by_rule,
                    }
                )
            elif path.suffix.casefold() in IMAGE_EXTENSIONS:
                images.append(path)
            else:
                ignored_files_report.append(
                    {
                        "relative_path": relative_path,
                        "reason": "unsupported_extension",
                    }
                )

    images.sort(key=lambda path: natural_key(path.relative_to(folder).as_posix()))
    ignored_directories.sort(key=lambda entry: natural_key(entry["relative_path"]))
    ignored_files_report.sort(key=lambda entry: natural_key(entry["relative_path"]))
    return images, ignored_directories, ignored_files_report


def duplicate_candidate_key(path: Path, root: Path) -> tuple[object, ...]:
    relative = path.relative_to(root).as_posix()
    natural = tuple(
        f"{int(part):020d}" if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", relative)
    )
    return (1 if COPY_STYLE_SUFFIX.search(path.stem) else 0, natural)


def resolve_exact_duplicates(
    images: list[Path], root: Path
) -> tuple[list[Path], list[dict[str, str]], dict[Path, str]]:
    """Keep one deterministic path for each exact image hash without deleting sources."""
    content_hashes = {path: sha256_file(path) for path in images}
    by_hash: dict[str, list[Path]] = {}
    for path in images:
        by_hash.setdefault(content_hashes[path], []).append(path)

    included: list[Path] = []
    resolution: list[dict[str, str]] = []
    for digest, members in by_hash.items():
        ordered = sorted(members, key=lambda path: duplicate_candidate_key(path, root))
        canonical = ordered[0]
        included.append(canonical)
        canonical_relative = canonical.relative_to(root).as_posix()
        for redundant in ordered[1:]:
            resolution.append(
                {
                    "relative_path": redundant.relative_to(root).as_posix(),
                    "reason": "exact_duplicate",
                    "canonical_path": canonical_relative,
                    "sha256": digest,
                }
            )

    included.sort(key=lambda path: natural_key(path.relative_to(root).as_posix()))
    resolution.sort(key=lambda entry: natural_key(entry["relative_path"]))
    return included, resolution, content_hashes


def duplicate_resolution_digest(resolution: list[dict[str, str]]) -> str:
    return sha256_json(
        {"policy": DUPLICATE_RESOLUTION_POLICY, "redundant_files": resolution}
    )


def duplicate_group_count(resolution: list[dict[str, str]]) -> int:
    return len({entry["sha256"] for entry in resolution})


def proposed_group_id(path: Path, root: Path, intake_method: str) -> str:
    if intake_method != "folders":
        return ""
    parts = path.relative_to(root).parts
    if len(parts) < 2:
        return "UNASSIGNED_ROOT"
    return parts[0]


def make_entry(
    path: Path,
    root: Path,
    sequence: int,
    intake_method: str,
    content_sha256: str = "",
) -> dict[str, Any]:
    stat = path.stat()
    return {
        "sequence": sequence,
        "relative_path": path.relative_to(root).as_posix(),
        "filename": path.name,
        "extension": path.suffix.casefold(),
        "bytes": stat.st_size,
        "sha256": content_sha256 or sha256_file(path),
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat(),
        "status": "pending",
        "item_id": "",
        "group_id": proposed_group_id(path, root, intake_method),
        "role": "",
        "notes": "",
    }


def refresh_manifest(
    *,
    photos_folder: Path,
    output_path: Path,
    client_id: str,
    client_name: str,
    intake_id: str,
    catalog_template: str,
    requested_intake_method: str,
    preflight_lock_path: Path,
    ignored_dirs: list[str] | None = None,
    ignored_files: list[str] | None = None,
) -> dict[str, Any]:
    if not photos_folder.is_dir():
        raise ManifestError(f"Photo folder does not exist: {photos_folder}")
    if not client_id.strip() or not intake_id.strip():
        raise ManifestError("client_id and intake_id are required")
    if requested_intake_method not in INTAKE_METHODS:
        raise ManifestError(
            f"Unsupported intake method: {requested_intake_method}"
        )

    preflight = validate_preflight_lock(
        preflight_lock_path,
        photos_folder=photos_folder,
        client_id=client_id,
        intake_id=intake_id,
        catalog_template=catalog_template,
        ignored_dirs=ignored_dirs or [],
        ignored_files=ignored_files or [],
    )

    existing = read_existing(output_path)
    if existing:
        if existing.get("client_id") != client_id:
            raise ManifestError("Existing manifest belongs to a different client_id")
        if existing.get("intake_id") != intake_id:
            raise ManifestError("Existing manifest belongs to a different intake_id")

    old_by_path = {
        str(entry.get("relative_path", "")): entry
        for entry in (existing or {}).get("photos", [])
        if isinstance(entry, dict)
    }

    normalized_ignored_dirs = normalize_ignored_dirs(ignored_dirs or [])
    normalized_ignored_files = normalize_ignored_files(ignored_files or [])
    scanned_images, ignored_directories, ignored_files = scan_folder(
        photos_folder, normalized_ignored_dirs, normalized_ignored_files
    )
    images, duplicate_resolution, content_hashes = resolve_exact_duplicates(
        scanned_images, photos_folder
    )
    ignored_files.extend(duplicate_resolution)
    ignored_files.sort(key=lambda entry: natural_key(entry["relative_path"]))
    has_nested_images = any(
        len(path.relative_to(photos_folder).parts) > 1 for path in images
    )
    intake_method = (
        "folders"
        if requested_intake_method == "auto" and has_nested_images
        else "sequence"
        if requested_intake_method == "auto"
        else requested_intake_method
    )

    current_paths: set[str] = set()
    refreshed: list[dict[str, Any]] = []
    for sequence, path in enumerate(images, start=1):
        entry = make_entry(
            path,
            photos_folder,
            sequence,
            intake_method,
            content_hashes[path],
        )
        relative_path = entry["relative_path"]
        current_paths.add(relative_path)
        previous = old_by_path.get(relative_path)
        if previous:
            content_unchanged = (
                str(previous.get("sha256", "")).casefold() == entry["sha256"]
                and int(previous.get("bytes", -1)) == entry["bytes"]
            )
            if content_unchanged:
                for field in PRESERVED_FIELDS:
                    prior_value = str(previous.get(field, "")).strip()
                    if prior_value:
                        entry[field] = prior_value
            else:
                entry["notes"] = combine_notes(
                    entry["notes"],
                    "Photo content changed since the prior scan; assignment reset.",
                )
            if entry["status"] not in PHOTO_STATUSES:
                entry["status"] = "unresolved"
                entry["notes"] = combine_notes(
                    entry["notes"], "Invalid prior status reset to unresolved."
                )
        refreshed.append(entry)

    for relative_path, previous in old_by_path.items():
        if relative_path in current_paths:
            continue
        if any(
            relative_path == entry["relative_path"] for entry in ignored_files
        ) or any(
            relative_path == entry["relative_path"]
            or relative_path.startswith(f'{entry["relative_path"]}/')
            for entry in ignored_directories
        ):
            continue
        missing = dict(previous)
        missing["sequence"] = len(refreshed) + 1
        missing["status"] = "missing"
        missing["notes"] = combine_notes(
            str(missing.get("notes", "")),
            "File was present in an earlier scan but is now missing.",
        )
        refreshed.append(missing)

    current_digest = photo_set_digest(refreshed)
    if current_digest != preflight.get("photo_set_digest"):
        raise ManifestError(
            "Included photo set changed after preflight confirmation; create and confirm a new preflight lock"
        )
    current_duplicate_digest = duplicate_resolution_digest(duplicate_resolution)
    if current_duplicate_digest != preflight.get("duplicate_resolution_digest"):
        raise ManifestError(
            "Exact duplicate set changed after preflight confirmation; create and confirm a new preflight lock"
        )

    now = utc_now()
    manifest = {
        "version": 1,
        "client_id": client_id.strip(),
        "client_name": client_name.strip(),
        "intake_id": intake_id.strip(),
        "source_folder": str(photos_folder.resolve()),
        "catalog_template": catalog_template.strip(),
        "catalog_template_sha256": preflight["catalog_template_sha256"],
        "preflight_lock": str(preflight_lock_path.resolve()),
        "preflight_lock_sha256": sha256_file(preflight_lock_path),
        "catalog_rules_digest": preflight["catalog_rules_digest"],
        "intake_method": intake_method,
        "requested_intake_method": requested_intake_method,
        "ignored_directory_rules": sorted(normalized_ignored_dirs, key=natural_key),
        "ignored_file_rules": normalized_ignored_files,
        "ignored_directories": ignored_directories,
        "ignored_files": ignored_files,
        "duplicate_resolution_policy": DUPLICATE_RESOLUTION_POLICY,
        "duplicate_resolution_digest": current_duplicate_digest,
        "exact_duplicate_group_count": duplicate_group_count(duplicate_resolution),
        "exact_duplicate_file_count": len(duplicate_resolution),
        "duplicate_resolution": duplicate_resolution,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
        "batch_limits": {"max_photos": 24, "max_candidate_objects": 24},
        "photos": refreshed,
        "photo_set_digest": current_digest,
        "groups": summarize_groups(refreshed),
        "summary": summarize(refreshed),
        "scan_summary": {
            "included_images": len(images),
            "ignored_directories": len(ignored_directories),
            "ignored_directory_images": sum(
                int(entry["image_count"]) for entry in ignored_directories
            ),
            "ignored_files": len(ignored_files),
            "exact_duplicate_groups": duplicate_group_count(duplicate_resolution),
            "exact_duplicate_files": len(duplicate_resolution),
        },
    }
    atomic_write_json(output_path, manifest)
    return manifest


def validate_preflight_lock(
    path: Path,
    *,
    photos_folder: Path,
    client_id: str,
    intake_id: str,
    catalog_template: str,
    ignored_dirs: list[str],
    ignored_files: list[str],
) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"Confirmed preflight lock is required: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        lock = json.load(handle)
    if not isinstance(lock, dict) or lock.get("version") != 1:
        raise ManifestError("Preflight lock is not a supported version 1 record")
    if lock.get("status") != "CONFIRMED":
        raise ManifestError("Preflight lock must be CONFIRMED before scanning")
    expected = {
        "client_id": client_id.strip(),
        "intake_id": intake_id.strip(),
        "source_folder": str(photos_folder.resolve()),
        "catalog_template": str(Path(catalog_template).resolve()),
    }
    for field, value in expected.items():
        if str(lock.get(field, "")) != value:
            raise ManifestError(f"Preflight {field} does not match this scan")
    if Path(catalog_template).is_file() and lock.get("catalog_template_sha256") != sha256_file(Path(catalog_template)):
        raise ManifestError("Catalog template changed after preflight confirmation")
    lock_dirs = set(str(value).casefold() for value in lock.get("ignored_directory_rules", []))
    scan_dirs = normalize_ignored_dirs(ignored_dirs)
    if lock_dirs != scan_dirs:
        raise ManifestError("Ignored directory rules differ from the confirmed preflight")
    if list(lock.get("ignored_file_rules", [])) != normalize_ignored_files(ignored_files):
        raise ManifestError("Ignored file rules differ from the confirmed preflight")
    return lock


def combine_notes(existing: str, addition: str) -> str:
    existing = existing.strip()
    return f"{existing} {addition}".strip()


def summarize(photos: list[dict[str, Any]]) -> dict[str, int]:
    result = {status: 0 for status in sorted(PHOTO_STATUSES)}
    for photo in photos:
        status = str(photo.get("status", "unresolved"))
        result[status if status in result else "unresolved"] += 1
    result["total"] = len(photos)
    result["accounted_for"] = sum(
        result[status]
        for status in ("assigned", "separator", "excluded", "unresolved", "missing")
    )
    return result


def summarize_groups(photos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for photo in photos:
        group_id = str(photo.get("group_id", "")).strip()
        if not group_id:
            continue
        grouped.setdefault(group_id, []).append(photo)
    return [
        {
            "group_id": group_id,
            "photo_count": len(group_photos),
            "item_id": next(
                (
                    str(photo.get("item_id", "")).strip()
                    for photo in group_photos
                    if str(photo.get("item_id", "")).strip()
                ),
                "",
            ),
            "status": (
                "assigned"
                if all(photo.get("status") == "assigned" for photo in group_photos)
                else "review"
                if any(
                    photo.get("status")
                    in {"assigned", "unresolved", "missing", "excluded", "separator"}
                    for photo in group_photos
                )
                else "pending"
            ),
        }
        for group_id, group_photos in sorted(
            grouped.items(), key=lambda item: natural_key(item[0])
        )
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or refresh a resumable bulk photo intake manifest."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Scan a client photo folder")
    scan.add_argument("--photos", required=True, type=Path)
    scan.add_argument("--output", required=True, type=Path)
    scan.add_argument("--client-id", required=True)
    scan.add_argument("--client-name", default="")
    scan.add_argument("--intake-id", required=True)
    scan.add_argument("--catalog-template", required=True)
    scan.add_argument("--preflight-lock", required=True, type=Path)
    scan.add_argument(
        "--ignore-dir",
        action="append",
        default=[],
        help="Directory name or root-relative directory path to exclude; repeat as needed",
    )
    scan.add_argument(
        "--ignore-file",
        action="append",
        default=[],
        help="Filename or root-relative glob to exclude; repeat as needed",
    )
    scan.add_argument(
        "--intake-method",
        choices=sorted(INTAKE_METHODS),
        default="auto",
        help="auto detects child folders; folders groups by top-level folder; sequence leaves grouping for separator-card review",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = refresh_manifest(
            photos_folder=args.photos,
            output_path=args.output,
            client_id=args.client_id,
            client_name=args.client_name,
            intake_id=args.intake_id,
            catalog_template=args.catalog_template,
            requested_intake_method=args.intake_method,
            preflight_lock_path=args.preflight_lock,
            ignored_dirs=args.ignore_dir,
            ignored_files=args.ignore_file,
        )
    except (ManifestError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest["summary"], indent=2))
    print(json.dumps({"scan_summary": manifest["scan_summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
