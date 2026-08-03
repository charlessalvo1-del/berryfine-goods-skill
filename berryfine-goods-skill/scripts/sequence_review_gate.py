#!/usr/bin/env python3
"""Reconcile independent AI reviews of a flat photo sequence safely."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from bfg_integrity import photo_set_digest


CONFIDENCE_LEVELS = {"high", "medium", "low"}
NON_INVENTORY_STATUSES = {"excluded", "separator", "missing"}


class ReviewError(ValueError):
    """Raised when a sequence review cannot be reconciled safely."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ReviewError(f"Expected a JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def validate_manifest(manifest: dict[str, Any]) -> tuple[list[int], int]:
    if manifest.get("version") != 1:
        raise ReviewError("Manifest is not a supported version 1 manifest")
    if manifest.get("intake_method") != "sequence":
        raise ReviewError("Sequence review gate requires intake_method='sequence'")
    photos = manifest.get("photos")
    if not isinstance(photos, list) or not photos:
        raise ReviewError("Manifest has no photos")

    sequences: list[int] = []
    inventory_sequences: list[int] = []
    for photo in photos:
        if not isinstance(photo, dict):
            raise ReviewError("Manifest contains an invalid photo entry")
        sequence = photo.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            raise ReviewError("Every manifest photo needs a positive integer sequence")
        sequences.append(sequence)
        status = str(photo.get("status", "pending")).strip().casefold()
        if status not in NON_INVENTORY_STATUSES:
            inventory_sequences.append(sequence)

    if len(set(sequences)) != len(sequences):
        raise ReviewError("Manifest contains duplicate photo sequence numbers")
    if sorted(sequences) != list(range(1, len(sequences) + 1)):
        raise ReviewError("Manifest photo sequence must be contiguous from 1")
    if not inventory_sequences:
        raise ReviewError("Manifest contains no inventory photos")
    try:
        calculated_digest = photo_set_digest(photos)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError(f"Manifest photo hash records are invalid: {exc}") from exc
    if manifest.get("photo_set_digest") != calculated_digest:
        raise ReviewError("Manifest photo_set_digest does not match its photo records")
    return inventory_sequences, len(photos)


def validate_boundary(entry: Any, photo_count: int, label: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ReviewError(f"{label} contains a non-object boundary")
    after_sequence = entry.get("after_sequence")
    if not isinstance(after_sequence, int) or not 1 <= after_sequence < photo_count:
        raise ReviewError(
            f"{label} boundary after_sequence must be between 1 and {photo_count - 1}"
        )
    confidence = str(entry.get("confidence", "")).strip().casefold()
    if confidence not in CONFIDENCE_LEVELS:
        raise ReviewError(
            f"{label} boundary {after_sequence} has invalid confidence={confidence!r}"
        )
    reason = str(entry.get("reason", "")).strip()
    left_identity = str(entry.get("left_identity", "")).strip()
    right_identity = str(entry.get("right_identity", "")).strip()
    if not reason or not left_identity or not right_identity:
        raise ReviewError(
            f"{label} boundary {after_sequence} needs reason, left_identity, and right_identity"
        )
    if left_identity.casefold() == right_identity.casefold():
        raise ReviewError(
            f"{label} boundary {after_sequence} uses the same identity on both sides"
        )
    return {
        "after_sequence": after_sequence,
        "confidence": confidence,
        "reason": reason,
        "left_identity": left_identity,
        "right_identity": right_identity,
    }


def load_review(
    path: Path, expected_pass: str, photo_count: int, manifest_photo_digest: str
) -> dict[int, dict[str, Any]]:
    review = read_json(path)
    if review.get("version") != 1:
        raise ReviewError(f"{expected_pass} review is not version 1")
    if str(review.get("pass", "")).strip().casefold() != expected_pass:
        raise ReviewError(f"Expected pass={expected_pass!r}: {path}")
    if review.get("photo_count") != photo_count:
        raise ReviewError(
            f"{expected_pass} review photo_count does not match the manifest"
        )
    if review.get("manifest_photo_digest") != manifest_photo_digest:
        raise ReviewError(
            f"{expected_pass} review is not bound to this manifest photo digest"
        )
    boundaries = review.get("boundaries")
    if not isinstance(boundaries, list):
        raise ReviewError(f"{expected_pass} review has no boundaries array")
    by_position: dict[int, dict[str, Any]] = {}
    for raw in boundaries:
        boundary = validate_boundary(raw, photo_count, expected_pass)
        position = boundary["after_sequence"]
        if position in by_position:
            raise ReviewError(
                f"{expected_pass} review repeats boundary {position}"
            )
        by_position[position] = boundary
    return by_position


def load_adjudication(
    path: Path | None, photo_count: int, manifest_photo_digest: str
) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    payload = read_json(path)
    if payload.get("version") != 1 or payload.get("pass") != "adjudication":
        raise ReviewError("Adjudication must be a version 1 adjudication pass")
    if payload.get("photo_count") != photo_count:
        raise ReviewError("Adjudication photo_count does not match the manifest")
    if payload.get("manifest_photo_digest") != manifest_photo_digest:
        raise ReviewError("Adjudication is not bound to this manifest photo digest")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ReviewError("Adjudication has no decisions array")

    result: dict[int, dict[str, Any]] = {}
    for raw in decisions:
        boundary = validate_boundary(raw, photo_count, "adjudication")
        position = boundary["after_sequence"]
        decision = str(raw.get("decision", "")).strip().casefold()
        if decision not in {"split", "join"}:
            raise ReviewError(
                f"Adjudication boundary {position} must decide split or join"
            )
        lot_rationale = str(raw.get("lot_rationale", "")).strip()
        if decision == "join" and (
            boundary["confidence"] != "high" or not lot_rationale
        ):
            raise ReviewError(
                f"Joining disputed boundary {position} requires high confidence and lot_rationale"
            )
        if position in result:
            raise ReviewError(f"Adjudication repeats boundary {position}")
        boundary.update(decision=decision, lot_rationale=lot_rationale)
        result[position] = boundary
    return result


def build_groups(
    inventory_sequences: list[int],
    split_positions: set[int],
    review_positions: set[int],
) -> list[dict[str, Any]]:
    groups: list[list[int]] = [[]]
    for index, sequence in enumerate(inventory_sequences):
        groups[-1].append(sequence)
        if index == len(inventory_sequences) - 1:
            continue
        next_sequence = inventory_sequences[index + 1]
        if any(sequence <= boundary < next_sequence for boundary in split_positions):
            groups.append([])

    output: list[dict[str, Any]] = []
    for index, sequences in enumerate(groups):
        previous_end = groups[index - 1][-1] if index else None
        next_start = groups[index + 1][0] if index + 1 < len(groups) else None
        touches_review_boundary = any(
            (
                previous_end is not None
                and previous_end <= boundary < sequences[0]
            )
            or (
                next_start is not None
                and sequences[-1] <= boundary < next_start
            )
            for boundary in review_positions
        )
        output.append(
            {
                "ordinal": index + 1,
                "start_sequence": sequences[0],
                "end_sequence": sequences[-1],
                "photo_count": len(sequences),
                "sequences": sequences,
                "grouping_review_status": (
                    "REVIEW" if touches_review_boundary else "AUTO_ACCEPTED"
                ),
            }
        )
    return output


def reconcile(
    manifest_path: Path,
    forward_path: Path,
    reverse_path: Path,
    cohesion_path: Path,
    adjudication_path: Path | None,
) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    inventory_sequences, photo_count = validate_manifest(manifest)
    manifest_photo_digest = str(manifest.get("photo_set_digest", "")).strip()
    if len(manifest_photo_digest) != 64:
        raise ReviewError("Manifest is missing a valid photo_set_digest")
    forward = load_review(forward_path, "forward", photo_count, manifest_photo_digest)
    reverse = load_review(reverse_path, "reverse", photo_count, manifest_photo_digest)
    cohesion = load_review(cohesion_path, "cohesion", photo_count, manifest_photo_digest)
    adjudication = load_adjudication(adjudication_path, photo_count, manifest_photo_digest)

    candidate_positions = set(forward) | set(reverse)
    disagreement_positions = set(forward) ^ set(reverse)
    unexpected_adjudications = set(adjudication) - disagreement_positions
    if unexpected_adjudications:
        raise ReviewError(
            "Adjudication contains positions that were not forward/reverse disagreements: "
            + ", ".join(map(str, sorted(unexpected_adjudications)))
        )

    split_positions: set[int] = set()
    review_positions: set[int] = set()
    decisions: list[dict[str, Any]] = []
    for position in sorted(candidate_positions):
        if position in forward and position in reverse:
            split_positions.add(position)
            decisions.append(
                {
                    "after_sequence": position,
                    "decision": "split",
                    "basis": "forward_reverse_consensus",
                    "review_required": False,
                }
            )
            continue

        adjudicated = adjudication.get(position)
        if adjudicated:
            if adjudicated["decision"] == "split":
                split_positions.add(position)
            decisions.append(
                {
                    "after_sequence": position,
                    "decision": adjudicated["decision"],
                    "basis": "automated_high_resolution_adjudication",
                    "review_required": adjudicated["confidence"] != "high",
                    "reason": adjudicated["reason"],
                    "lot_rationale": adjudicated["lot_rationale"],
                }
            )
            if adjudicated["confidence"] != "high":
                review_positions.add(position)
            continue

        # Avoid an incorrect merge when an automated adjudication artifact is absent.
        split_positions.add(position)
        review_positions.add(position)
        decisions.append(
            {
                "after_sequence": position,
                "decision": "split",
                "basis": "conservative_split_unadjudicated_disagreement",
                "review_required": True,
            }
        )

    for position, boundary in sorted(cohesion.items()):
        split_positions.add(position)
        needs_review = boundary["confidence"] != "high"
        if needs_review:
            review_positions.add(position)
        decisions.append(
            {
                "after_sequence": position,
                "decision": "split",
                "basis": "within_group_cohesion_pass",
                "review_required": needs_review,
                "reason": boundary["reason"],
            }
        )

    # Keep one final record per position, preferring the later cohesion evidence.
    decisions_by_position = {
        decision["after_sequence"]: decision for decision in decisions
    }
    groups = build_groups(inventory_sequences, split_positions, review_positions)
    review_group_count = sum(
        group["grouping_review_status"] == "REVIEW" for group in groups
    )
    return {
        "version": 1,
        "client_id": manifest.get("client_id", ""),
        "intake_id": manifest.get("intake_id", ""),
        "manifest": str(manifest_path.resolve()),
        "review_method": "blind_forward_reverse_adjudication_and_cohesion",
        "prior_run_data_allowed": False,
        "photo_count": photo_count,
        "manifest_photo_digest": manifest_photo_digest,
        "inventory_photo_count": len(inventory_sequences),
        "boundary_decisions": [
            decisions_by_position[position]
            for position in sorted(decisions_by_position)
        ],
        "groups": groups,
        "summary": {
            "forward_boundaries": len(forward),
            "reverse_boundaries": len(reverse),
            "forward_reverse_disagreements": len(disagreement_positions),
            "adjudicated_disagreements": len(adjudication),
            "cohesion_splits": len(cohesion),
            "final_split_count": len(split_positions),
            "final_group_count": len(groups),
            "review_group_count": review_group_count,
            "status": "PASS_WITH_REVIEW" if review_group_count else "PASS",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile blind forward, reverse, adjudication, and cohesion reviews "
            "for a flat inventory photo sequence."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--forward", required=True, type=Path)
    parser.add_argument("--reverse", required=True, type=Path)
    parser.add_argument("--cohesion", required=True, type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = reconcile(
            args.manifest,
            args.forward,
            args.reverse,
            args.cohesion,
            args.adjudication,
        )
        atomic_write_json(args.output, output)
    except (ReviewError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
