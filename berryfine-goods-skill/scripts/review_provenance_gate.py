#!/usr/bin/env python3
"""Prove that forward and reverse grouping reviews declare isolated provenance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, sha256_file


class ProvenanceError(ValueError):
    """Raised when grouping review provenance is missing or contradictory."""


def load(path: Path, expected_pass: str, manifest_digest: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("pass") != expected_pass or payload.get("manifest_photo_digest") != manifest_digest:
        raise ProvenanceError(f"{expected_pass} review is not bound to the current manifest")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ProvenanceError(f"{expected_pass} review lacks provenance")
    required = ("review_run_id", "created_at", "model", "prompt_sha256", "input_order", "isolated_context", "visible_prior_passes", "prior_run_data_visible")
    missing = [field for field in required if field not in provenance]
    if missing:
        raise ProvenanceError(f"{expected_pass} provenance is missing: {', '.join(missing)}")
    if len(str(provenance["prompt_sha256"])) != 64:
        raise ProvenanceError(f"{expected_pass} prompt_sha256 is invalid")
    try:
        datetime.fromisoformat(str(provenance["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceError(f"{expected_pass} created_at is invalid") from exc
    if not isinstance(provenance["visible_prior_passes"], list):
        raise ProvenanceError(f"{expected_pass} visible_prior_passes must be a list")
    return payload, provenance


def gate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    manifest_digest = str(manifest.get("photo_set_digest", ""))
    if len(manifest_digest) != 64:
        raise ProvenanceError("Manifest lacks a valid photo_set_digest")
    forward, forward_provenance = load(args.forward, "forward", manifest_digest)
    reverse, reverse_provenance = load(args.reverse, "reverse", manifest_digest)
    cohesion, cohesion_provenance = load(args.cohesion, "cohesion", manifest_digest)
    if forward_provenance["review_run_id"] == reverse_provenance["review_run_id"]:
        raise ProvenanceError("Forward and reverse reviews must use different review_run_id values")
    if forward_provenance["input_order"] != "forward" or reverse_provenance["input_order"] != "reverse":
        raise ProvenanceError("Forward and reverse input_order declarations are incorrect")
    for pass_name, provenance in (("forward", forward_provenance), ("reverse", reverse_provenance)):
        if provenance["isolated_context"] is not True or provenance["visible_prior_passes"] or provenance["prior_run_data_visible"] is not False:
            raise ProvenanceError(f"{pass_name} review was not declared isolated and blind")
    if cohesion_provenance["input_order"] != "group-sample":
        raise ProvenanceError("Cohesion input_order must be group-sample")
    records = [
        {"pass": "forward", "sha256": sha256_file(args.forward), **forward_provenance},
        {"pass": "reverse", "sha256": sha256_file(args.reverse), **reverse_provenance},
        {"pass": "cohesion", "sha256": sha256_file(args.cohesion), **cohesion_provenance},
    ]
    return {"version": 1, "status": "PASS", "client_id": manifest.get("client_id", ""), "intake_id": manifest.get("intake_id", ""), "manifest_photo_digest": manifest_digest, "reviews": records}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate blind grouping-review provenance.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--forward", required=True, type=Path)
    parser.add_argument("--reverse", required=True, type=Path)
    parser.add_argument("--cohesion", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = gate(args)
        atomic_write_json(args.output, result)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
