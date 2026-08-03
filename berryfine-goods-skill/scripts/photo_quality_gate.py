#!/usr/bin/env python3
"""Validate that manifest photos are real, readable image containers before AI review."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, contained_path, sha256_file


class PhotoQualityError(ValueError):
    """Raised when photo evidence is incomplete or invalid."""


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if length < 2 or offset + length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 7:
                return None
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    return None


def inspect_image(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    kind = ""
    dimensions: tuple[int, int] | None = None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        kind = "png"
        dimensions = struct.unpack(">II", data[16:24])
    elif data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        kind = "gif"
        dimensions = struct.unpack("<HH", data[6:10])
    elif data.startswith(b"BM") and len(data) >= 26:
        kind = "bmp"
        dimensions = struct.unpack("<II", data[18:26])
    elif data.startswith(b"\xff\xd8"):
        kind = "jpeg"
        dimensions = jpeg_dimensions(data)
    elif data[:4] in {b"II*\x00", b"MM\x00*"}:
        kind = "tiff"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        kind = "webp"
    elif len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].decode("ascii", errors="replace").casefold()
        kind = "heif" if brand in {"heic", "heix", "hevc", "hevx", "mif1", "msf1"} else "avif" if brand in {"avif", "avis"} else "isobmff"
    if not kind:
        raise PhotoQualityError("unrecognized or corrupt image signature")
    if dimensions and (dimensions[0] <= 0 or dimensions[1] <= 0):
        raise PhotoQualityError("invalid image dimensions")
    return {
        "detected_format": kind,
        "width": dimensions[0] if dimensions else None,
        "height": dimensions[1] if dimensions else None,
        "bytes": len(data),
        "sha256": sha256_file(path),
        "decoder_status": "HEADER_VALIDATED" if dimensions else "CONTAINER_VALIDATED",
    }


def run(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source = Path(str(manifest.get("source_folder", "")))
    if not source.is_dir():
        raise PhotoQualityError(f"Manifest source folder is unavailable: {source}")
    photos = manifest.get("photos")
    if not isinstance(photos, list) or not photos:
        raise PhotoQualityError("Manifest contains no photos")

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    exact_duplicates: dict[str, list[int]] = defaultdict(list)
    for photo in photos:
        sequence = int(photo.get("sequence", 0))
        relative = str(photo.get("relative_path", ""))
        try:
            path = contained_path(source, relative, label="photo path")
            if not path.is_file():
                raise PhotoQualityError("source file is missing")
            result = inspect_image(path)
            expected_hash = str(photo.get("sha256", "")).casefold()
            if not expected_hash:
                raise PhotoQualityError("manifest is missing sha256")
            if result["sha256"] != expected_hash:
                raise PhotoQualityError("source content no longer matches manifest sha256")
            if int(photo.get("bytes", -1)) != result["bytes"]:
                raise PhotoQualityError("source size no longer matches manifest bytes")
            exact_duplicates[result["sha256"]].append(sequence)
            records.append({"sequence": sequence, "relative_path": relative, **result})
        except (OSError, ValueError, PhotoQualityError) as exc:
            errors.append({"sequence": sequence, "relative_path": relative, "error": str(exc)})

    duplicate_groups = [values for values in exact_duplicates.values() if len(values) > 1]
    return {
        "version": 1,
        "client_id": manifest.get("client_id", ""),
        "intake_id": manifest.get("intake_id", ""),
        "manifest": str(manifest_path.resolve()),
        "status": "PASS" if not errors else "FAIL",
        "photo_count": len(photos),
        "validated_photo_count": len(records),
        "error_count": len(errors),
        "exact_duplicate_group_count": len(duplicate_groups),
        "exact_duplicate_sequences": duplicate_groups,
        "errors": errors,
        "photos": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate manifest photo content before AI analysis.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.manifest)
        atomic_write_json(args.output, result)
        print(json.dumps({key: result[key] for key in ("status", "photo_count", "validated_photo_count", "error_count", "exact_duplicate_group_count")}, indent=2))
        if result["status"] != "PASS":
            for error in result["errors"][:20]:
                print(f"error: photo {error['sequence']}: {error['error']}", file=sys.stderr)
            if len(result["errors"]) > 20:
                print(f"error: {len(result['errors']) - 20} additional photo errors are recorded in {args.output}", file=sys.stderr)
            return 2
    except (OSError, ValueError, json.JSONDecodeError, PhotoQualityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
