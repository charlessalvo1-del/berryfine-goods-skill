#!/usr/bin/env python3
"""Apply a locked final grouping and stable catalog identities to a manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, sha256_file, sha256_json


class GroupingError(ValueError):
    """Raised when grouping coverage or identity bindings are unsafe."""


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise GroupingError(f"Expected JSON object: {path}")
    return value


def apply(manifest_path: Path, grouping_path: Path, identities_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load(manifest_path)
    grouping = load(grouping_path)
    identities = load(identities_path)
    if grouping.get("manifest_photo_digest") != manifest.get("photo_set_digest"):
        raise GroupingError("Final grouping is not bound to this manifest photo digest")
    if grouping.get("client_id") != manifest.get("client_id") or grouping.get("intake_id") != manifest.get("intake_id"):
        raise GroupingError("Final grouping client/intake does not match manifest")
    raw_groups = grouping.get("groups")
    raw_identities = identities.get("groups")
    if not isinstance(raw_groups, list) or not isinstance(raw_identities, list):
        raise GroupingError("Grouping and identity files must contain groups arrays")
    identity_by_ordinal = {int(entry["ordinal"]): entry for entry in raw_identities}
    if len(identity_by_ordinal) != len(raw_identities):
        raise GroupingError("Identity file repeats a group ordinal")

    inventory_photos = {
        int(photo["sequence"]): photo
        for photo in manifest.get("photos", [])
        if str(photo.get("status", "pending")).casefold() not in {"excluded", "separator", "missing"}
    }
    covered: set[int] = set()
    item_ids: set[str] = set()
    group_ids: set[str] = set()
    manifest_groups: list[dict[str, Any]] = []
    for group in raw_groups:
        ordinal = int(group["ordinal"])
        identity = identity_by_ordinal.get(ordinal)
        if not identity:
            raise GroupingError(f"Group {ordinal} has no approved identity")
        item_id = str(identity.get("item_id", "")).strip()
        group_id = str(identity.get("group_id", "")).strip()
        sku = str(identity.get("sku", "")).strip()
        if not item_id or not group_id or not sku:
            raise GroupingError(f"Group {ordinal} requires item_id, sku, and group_id")
        if not group_id.casefold().startswith(f"{sku} - ".casefold()):
            raise GroupingError(f"Group {ordinal} group_id must begin with its exact catalog SKU and ' - '")
        if item_id in item_ids or group_id.casefold() in group_ids:
            raise GroupingError(f"Duplicate item_id or group_id at group {ordinal}")
        item_ids.add(item_id)
        group_ids.add(group_id.casefold())
        sequences = [int(value) for value in group.get("sequences", [])]
        if not sequences:
            raise GroupingError(f"Group {ordinal} contains no photos")
        for index, sequence in enumerate(sequences):
            if sequence in covered:
                raise GroupingError(f"Photo sequence {sequence} appears in multiple groups")
            if sequence not in inventory_photos:
                raise GroupingError(f"Group {ordinal} references unavailable sequence {sequence}")
            covered.add(sequence)
            inventory_photos[sequence].update(
                status="assigned",
                item_id=item_id,
                group_id=group_id,
                role="primary" if index == 0 else "detail",
                notes="Assigned by locked final grouping.",
            )
        manifest_groups.append({
            "ordinal": ordinal,
            "item_id": item_id,
            "sku": sku,
            "group_id": group_id,
            "photo_count": len(sequences),
            "grouping_review_status": group.get("grouping_review_status", "REVIEW"),
        })
    missing = sorted(set(inventory_photos) - covered)
    if missing:
        raise GroupingError(f"Final grouping leaves {len(missing)} inventory photo(s) unassigned")
    if set(identity_by_ordinal) != {int(group["ordinal"]) for group in raw_groups}:
        raise GroupingError("Identity file contains groups not present in final grouping")

    manifest["groups"] = manifest_groups
    counts: dict[str, int] = {}
    for photo in manifest.get("photos", []):
        status = str(photo.get("status", "pending")).casefold()
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = len(manifest.get("photos", []))
    counts["accounted_for"] = sum(counts.get(key, 0) for key in ("assigned", "excluded", "separator", "missing"))
    manifest["summary"] = counts
    manifest["grouping_binding"] = {
        "final_grouping_sha256": sha256_file(grouping_path),
        "identity_map_sha256": sha256_file(identities_path),
        "group_count": len(manifest_groups),
        "assigned_photo_count": len(covered),
    }
    reconciliation = {
        "version": 1,
        "client_id": manifest.get("client_id", ""),
        "intake_id": manifest.get("intake_id", ""),
        "status": "PASS",
        "manifest_photo_digest": manifest.get("photo_set_digest", ""),
        "final_grouping_sha256": sha256_file(grouping_path),
        "identity_map_sha256": sha256_file(identities_path),
        "group_count": len(manifest_groups),
        "assigned_photo_count": len(covered),
        "duplicate_assignment_count": 0,
        "unassigned_inventory_photo_count": 0,
        "assignment_digest": sha256_json(manifest_groups),
    }
    return manifest, reconciliation


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply final grouping identities to a photo manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--grouping", required=True, type=Path)
    parser.add_argument("--identities", required=True, type=Path)
    parser.add_argument("--reconciliation", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest, reconciliation = apply(args.manifest, args.grouping, args.identities)
        atomic_write_json(args.manifest, manifest)
        atomic_write_json(args.reconciliation, reconciliation)
        print(json.dumps(reconciliation, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, GroupingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
