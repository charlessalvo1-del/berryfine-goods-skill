#!/usr/bin/env python3
"""Append and verify immutable realized-outcome events without changing appraisals."""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, sha256_json


EVENT_TYPES = {"LISTED", "PRICE_CHANGED", "SOLD", "DONATED", "RETURNED", "TEST_PASSED", "TEST_FAILED", "IDENTIFICATION_CONFIRMED", "IDENTIFICATION_CORRECTED"}
MINIMUM_ACCURACY_SAMPLE = 100


class OutcomeError(ValueError):
    """Raised when an operational outcome event is unsafe or incomplete."""


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise OutcomeError(f"Outcome line {number} is not an object")
            events.append(value)
    return events


def validate_event(event: dict[str, Any]) -> None:
    required = {"event_id", "client_id", "item_id", "event_type", "occurred_at", "recorded_by"}
    missing = sorted(key for key in required if not str(event.get(key, "")).strip())
    if missing:
        raise OutcomeError(f"Outcome event is missing: {', '.join(missing)}")
    if event["event_type"] not in EVENT_TYPES:
        raise OutcomeError(f"Unsupported event_type {event['event_type']!r}")
    try:
        datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OutcomeError("occurred_at must be a valid ISO timestamp") from exc
    if event["event_type"] == "SOLD":
        for field in ("channel", "sold_price", "currency"):
            if event.get(field, "") in {"", None}:
                raise OutcomeError(f"SOLD event requires {field}")
    if event["event_type"] == "DONATED" and not event.get("destination"):
        raise OutcomeError("DONATED event requires destination")
    if event["event_type"] == "IDENTIFICATION_CONFIRMED":
        for field in ("confirmed_identity", "verification_method"):
            if not str(event.get(field, "")).strip():
                raise OutcomeError(f"IDENTIFICATION_CONFIRMED requires {field}")
    if event["event_type"] == "IDENTIFICATION_CORRECTED":
        for field in ("corrected_identity", "verification_method"):
            if not str(event.get(field, "")).strip():
                raise OutcomeError(f"IDENTIFICATION_CORRECTED requires {field}")


def append(path: Path, input_path: Path) -> dict[str, Any]:
    event = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(event, dict):
        raise OutcomeError("Outcome input must be an object")
    validate_event(event)
    existing = load(path)
    if event["event_id"] in {row.get("event_id") for row in existing}:
        raise OutcomeError(f"Duplicate event_id {event['event_id']}")
    previous_digest = existing[-1].get("event_digest", "") if existing else ""
    event = {**event, "previous_event_digest": previous_digest}
    event["event_digest"] = sha256_json(event)
    rows = [*existing, event]
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return {"status": "PASS", "event_count": len(rows), "event_id": event["event_id"], "event_digest": event["event_digest"]}


def verify(path: Path) -> dict[str, Any]:
    events = load(path)
    previous = ""
    ids: set[str] = set()
    for event in events:
        validate_event(event)
        if event["event_id"] in ids or event.get("previous_event_digest", "") != previous:
            raise OutcomeError("Outcome event chain is duplicated or broken")
        ids.add(event["event_id"])
        expected = event.pop("event_digest", "")
        if expected != sha256_json(event):
            raise OutcomeError(f"Outcome event {event['event_id']} was changed")
        event["event_digest"] = expected
        previous = expected
    return {"status": "PASS", "event_count": len(events), "last_event_digest": previous}


def accuracy_report(outcomes_path: Path, inventory_path: Path, intake_id: str) -> dict[str, Any]:
    verify(outcomes_path)
    events = load(outcomes_path)
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == intake_id]
    if not rows:
        raise OutcomeError(f"Inventory contains no rows for intake {intake_id}")
    inventory = {row.get("item_id", ""): row for row in rows}
    if "" in inventory or len(inventory) != len(rows):
        raise OutcomeError("Inventory has blank or duplicate current-intake item IDs")

    latest_sale: dict[str, dict[str, Any]] = {}
    latest_identity: dict[str, dict[str, Any]] = {}
    for event in events:
        item_id = str(event.get("item_id", ""))
        if item_id not in inventory:
            continue
        if event.get("event_type") == "SOLD":
            latest_sale[item_id] = event
        if event.get("event_type") in {"IDENTIFICATION_CONFIRMED", "IDENTIFICATION_CORRECTED"}:
            latest_identity[item_id] = event

    absolute_percentage_errors: list[float] = []
    price_range_hits = 0
    pricing_details: list[dict[str, Any]] = []
    for item_id, event in latest_sale.items():
        row = inventory[item_id]
        if str(event.get("currency", "")).upper() != str(row.get("currency", "")).upper():
            continue
        try:
            realized = float(event["sold_price"])
            low = float(row["market_value_low"])
            mid = float(row["market_value_mid"])
            high = float(row["market_value_high"])
        except (TypeError, ValueError, KeyError):
            continue
        if realized <= 0 or not low <= mid <= high:
            continue
        hit = low <= realized <= high
        error = abs(realized - mid) / realized * 100
        price_range_hits += int(hit)
        absolute_percentage_errors.append(error)
        pricing_details.append({"item_id": item_id, "realized_price": realized, "range_covered": hit, "absolute_percentage_error": round(error, 2)})

    identification_details = [
        {"item_id": item_id, "accurate": event.get("event_type") == "IDENTIFICATION_CONFIRMED"}
        for item_id, event in latest_identity.items()
    ]
    identification_sample = len(identification_details)
    pricing_sample = len(absolute_percentage_errors)
    identification_accuracy = (
        sum(detail["accurate"] for detail in identification_details) / identification_sample * 100
        if identification_sample else None
    )
    price_range_coverage = price_range_hits / pricing_sample * 100 if pricing_sample else None
    median_ape = statistics.median(absolute_percentage_errors) if pricing_sample else None
    enough_data = identification_sample >= MINIMUM_ACCURACY_SAMPLE and pricing_sample >= MINIMUM_ACCURACY_SAMPLE
    claim_authorized = bool(
        enough_data
        and identification_accuracy is not None and identification_accuracy >= 90
        and price_range_coverage is not None and price_range_coverage >= 90
        and median_ape is not None and median_ape <= 20
    )
    return {
        "version": 1,
        "status": "MEASURED" if identification_sample or pricing_sample else "INSUFFICIENT_DATA",
        "intake_id": intake_id,
        "target_identification_accuracy_pct": [90, 97.8],
        "target_price_range_coverage_pct": [90, 97.8],
        "minimum_accuracy_sample": MINIMUM_ACCURACY_SAMPLE,
        "identification_sample": identification_sample,
        "identification_accuracy_pct": round(identification_accuracy, 2) if identification_accuracy is not None else None,
        "pricing_sample": pricing_sample,
        "price_range_coverage_pct": round(price_range_coverage, 2) if price_range_coverage is not None else None,
        "median_absolute_percentage_error_pct": round(median_ape, 2) if median_ape is not None else None,
        "accuracy_claim_authorized": claim_authorized,
        "identification_details": identification_details,
        "pricing_details": pricing_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain append-only BFG realized-outcome events.")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("append"); add.add_argument("--ledger", required=True, type=Path); add.add_argument("--input", required=True, type=Path)
    check = commands.add_parser("verify"); check.add_argument("--ledger", required=True, type=Path)
    report = commands.add_parser("accuracy-report"); report.add_argument("--outcomes", required=True, type=Path); report.add_argument("--inventory", required=True, type=Path); report.add_argument("--intake-id", required=True); report.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "append":
            result = append(args.ledger, args.input)
        elif args.command == "verify":
            result = verify(args.ledger)
        else:
            result = accuracy_report(args.outcomes, args.inventory, args.intake_id)
            if args.output:
                atomic_write_json(args.output, result)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, OutcomeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
