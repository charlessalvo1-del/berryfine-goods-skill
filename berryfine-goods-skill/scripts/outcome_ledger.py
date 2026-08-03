#!/usr/bin/env python3
"""Append and verify immutable realized-outcome events without changing appraisals."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from bfg_integrity import sha256_json


EVENT_TYPES = {"LISTED", "PRICE_CHANGED", "SOLD", "DONATED", "RETURNED", "TEST_PASSED", "TEST_FAILED", "IDENTIFICATION_CORRECTED"}


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain append-only BFG realized-outcome events.")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("append"); add.add_argument("--ledger", required=True, type=Path); add.add_argument("--input", required=True, type=Path)
    check = commands.add_parser("verify"); check.add_argument("--ledger", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = append(args.ledger, args.input) if args.command == "append" else verify(args.ledger)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, OutcomeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
