#!/usr/bin/env python3
"""Prepare and verify a policy-only refresh of completed legacy catalog data."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, sha256_file
from inventory_ledger import FIELDS, InventoryError, load_payload, read_ledger, validate_row


WORKFLOW = "legacy-catalog-refresh"
CONFIRM_INSTRUCTION = (
    "Confirm this item will not be sold before donation or rehoming."
)


class LegacyRefreshError(ValueError):
    """Raised when a requested legacy refresh could rewrite appraisal facts."""


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyRefreshError(f"Invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacyRefreshError(f"{label.capitalize()} must be a JSON object")
    return value


def refuse_overwrite(*paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise LegacyRefreshError(
            "Refusing to overwrite protected refresh artifact(s): "
            + ", ".join(existing)
        )


def require_confirmed_preflight(
    path: Path,
    *,
    ledger_path: Path,
    source_intake_id: str,
    target_intake_id: str,
) -> dict[str, Any]:
    lock = read_json(path, "preflight lock")
    if lock.get("version") != 1 or lock.get("status") != "CONFIRMED":
        raise LegacyRefreshError("Legacy refresh requires a confirmed version 1 preflight")
    if lock.get("workflow") != WORKFLOW:
        raise LegacyRefreshError("Preflight workflow is not legacy-catalog-refresh")
    if lock.get("source_intake_id") != source_intake_id:
        raise LegacyRefreshError("Preflight source_intake_id does not match")
    if lock.get("intake_id") != target_intake_id:
        raise LegacyRefreshError("Preflight target intake_id does not match")
    if Path(str(lock.get("source_ledger", ""))).resolve() != ledger_path.resolve():
        raise LegacyRefreshError("Preflight source ledger path does not match")
    if lock.get("source_ledger_sha256") != sha256_file(ledger_path):
        raise LegacyRefreshError("Source ledger changed after preflight")
    if lock.get("catalog_rules", {}).get("legacy_refresh_listing_authorized") is not False:
        raise LegacyRefreshError("Preflight does not prohibit listing authorization")
    return lock


def decimal_value(row: dict[str, str]) -> float:
    try:
        return float(row.get("decision_basis_value") or 0)
    except ValueError as exc:
        raise LegacyRefreshError(
            f"{row.get('item_id')} has invalid decision_basis_value"
        ) from exc


def append_sentence(existing: str, sentence: str) -> str:
    text = existing.strip()
    if sentence.casefold() in text.casefold():
        return text
    return f"{text} {sentence}".strip()


def migrate_row(
    source: dict[str, str], target_intake_id: str
) -> tuple[dict[str, str], bool]:
    row = {field: source.get(field, "") for field in FIELDS}
    row["intake_id"] = target_intake_id

    # A catalog refresh can never create listing authorization.
    row["listing_status"] = "DRAFT"
    row["human_review_status"] = "PENDING"
    row["approved_by"] = ""
    row["approved_at"] = ""

    value = decimal_value(row)
    migrated = False
    if 40 <= value < 50 and row["decision"] == "DONATE":
        row["decision"] = "CONFIRM DONATION"
        row["decision_rationale"] = append_sentence(
            row["decision_rationale"], CONFIRM_INSTRUCTION
        )
        row["donation_confirmation_status"] = "PENDING"
        row["donation_confirmed_by"] = ""
        row["donation_confirmed_at"] = ""
        row["donation_confirmation_notes"] = (
            "Policy-only legacy catalog refresh; prior completed valuation was retained."
        )
        migrated = True
    elif row["decision"] == "CONFIRM DONATION":
        if not 40 <= value < 50:
            raise LegacyRefreshError(
                f"{row['item_id']} has CONFIRM DONATION outside the $40-$49.99 band"
            )
        row["decision_rationale"] = append_sentence(
            row["decision_rationale"], CONFIRM_INSTRUCTION
        )
        row["donation_confirmation_status"] = "PENDING"
        row["donation_confirmed_by"] = ""
        row["donation_confirmed_at"] = ""
    elif not 40 <= value < 50:
        row["donation_confirmation_status"] = "NOT_REQUIRED"
        row["donation_confirmed_by"] = ""
        row["donation_confirmed_at"] = ""
        row["donation_confirmation_notes"] = ""

    validate_row(row, f"legacy refresh item {row['item_id']}", enforce_current_policy=True)
    return row, migrated


def load_source_rows(ledger_path: Path, source_intake_id: str) -> list[dict[str, str]]:
    rows = [
        row for row in read_ledger(ledger_path)
        if row.get("intake_id") == source_intake_id
    ]
    if not rows:
        raise LegacyRefreshError(
            f"Ledger contains no rows for source intake {source_intake_id}"
        )
    ids = [row["item_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise LegacyRefreshError("Source intake contains duplicate item IDs")
    return rows


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    refuse_overwrite(args.batch_output, args.grouping_output, args.plan_output)
    lock = require_confirmed_preflight(
        args.preflight_lock,
        ledger_path=args.ledger,
        source_intake_id=args.source_intake_id,
        target_intake_id=args.target_intake_id,
    )
    records = Path(str(lock.get("deliverable_paths", {}).get("records", ""))).resolve()
    for path in (args.batch_output, args.grouping_output, args.plan_output):
        if path.resolve().parent != records:
            raise LegacyRefreshError(
                "Every legacy refresh artifact must be written in the confirmed records folder"
            )

    source_rows = load_source_rows(args.ledger, args.source_intake_id)
    target_rows: list[dict[str, str]] = []
    migrations: list[str] = []
    for source in source_rows:
        row, migrated = migrate_row(source, args.target_intake_id)
        target_rows.append(row)
        if migrated:
            migrations.append(row["item_id"])

    grouping = read_json(args.source_grouping, "source grouping")
    if grouping.get("intake_id") != args.source_intake_id:
        raise LegacyRefreshError("Source grouping intake_id does not match")
    groups = grouping.get("groups")
    if not isinstance(groups, list):
        raise LegacyRefreshError("Source grouping must contain a groups array")
    grouped_ids = [str(group.get("item_id", "")) for group in groups]
    target_ids = [row["item_id"] for row in target_rows]
    if set(grouped_ids) != set(target_ids) or len(grouped_ids) != len(set(grouped_ids)):
        raise LegacyRefreshError(
            "Source grouping item IDs do not exactly match the legacy source intake"
        )

    batch = {
        "client_id": target_rows[0]["client_id"],
        "client_name": target_rows[0]["client_name"],
        "intake_id": args.target_intake_id,
        "workflow": WORKFLOW,
        "source_intake_id": args.source_intake_id,
        "items": target_rows,
    }
    refreshed_grouping = {
        **grouping,
        "intake_id": args.target_intake_id,
        "workflow": WORKFLOW,
        "source_intake_id": args.source_intake_id,
        "source_grouping_sha256": sha256_file(args.source_grouping),
        "groups": groups,
    }
    atomic_write_json(args.batch_output, batch)
    atomic_write_json(args.grouping_output, refreshed_grouping)

    actions = Counter(row["decision"] for row in target_rows)
    plan = {
        "version": 1,
        "status": "PASS",
        "workflow": WORKFLOW,
        "client_id": target_rows[0]["client_id"],
        "source_intake_id": args.source_intake_id,
        "intake_id": args.target_intake_id,
        "source_ledger": str(args.ledger.resolve()),
        "source_ledger_sha256": sha256_file(args.ledger),
        "source_grouping": str(args.source_grouping.resolve()),
        "source_grouping_sha256": sha256_file(args.source_grouping),
        "preflight_lock_sha256": sha256_file(args.preflight_lock),
        "batch_sha256": sha256_file(args.batch_output),
        "grouping_sha256": sha256_file(args.grouping_output),
        "item_count": len(target_rows),
        "policy_migration_count": len(migrations),
        "policy_migrated_item_ids": migrations,
        "action_counts": dict(sorted(actions.items())),
        "research_reused": True,
        "research_rerun": False,
        "listing_authorized": False,
    }
    atomic_write_json(args.plan_output, plan)
    return plan


def verify(args: argparse.Namespace) -> dict[str, Any]:
    refuse_overwrite(args.output)
    lock = read_json(args.preflight_lock, "preflight lock")
    plan = read_json(args.plan, "legacy refresh plan")
    if lock.get("status") != "CONFIRMED" or lock.get("workflow") != WORKFLOW:
        raise LegacyRefreshError("Confirmed legacy refresh preflight is required")
    if plan.get("status") != "PASS" or plan.get("workflow") != WORKFLOW:
        raise LegacyRefreshError("A PASS legacy refresh plan is required")
    if plan.get("preflight_lock_sha256") != sha256_file(args.preflight_lock):
        raise LegacyRefreshError("Legacy refresh plan is stale for the preflight lock")
    if plan.get("batch_sha256") != sha256_file(args.batch):
        raise LegacyRefreshError("Legacy refresh plan is stale for the batch")

    batch_rows = load_payload(args.batch)
    intake_id = str(plan.get("intake_id", ""))
    ledger_rows = [
        row for row in read_ledger(args.ledger)
        if row.get("intake_id") == intake_id
    ]
    expected = {row["item_id"]: row for row in batch_rows}
    actual = {row["item_id"]: row for row in ledger_rows}
    if expected != actual:
        raise LegacyRefreshError(
            "Canonical ledger target rows do not exactly match the approved refresh batch"
        )

    result = {
        "version": 1,
        "status": "PASS",
        "verification_mode": WORKFLOW,
        "catalog_authorized": True,
        "listing_authorized": False,
        "client_id": plan.get("client_id", ""),
        "source_intake_id": plan.get("source_intake_id", ""),
        "intake_id": intake_id,
        "ledger_sha256": sha256_file(args.ledger),
        "batch_sha256": sha256_file(args.batch),
        "plan_sha256": sha256_file(args.plan),
        "preflight_lock_sha256": sha256_file(args.preflight_lock),
        "item_count": len(actual),
        "policy_migration_count": int(plan.get("policy_migration_count", 0)),
        "action_counts": plan.get("action_counts", {}),
        "research_reused": True,
        "research_rerun": False,
        "blocker_count": 0,
        "blockers": [],
    }
    atomic_write_json(args.output, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or verify a fail-closed legacy catalog refresh."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser(
        "prepare", help="Create a policy-only refresh batch and grouping"
    )
    prepare_parser.add_argument("--ledger", required=True, type=Path)
    prepare_parser.add_argument("--source-intake-id", required=True)
    prepare_parser.add_argument("--target-intake-id", required=True)
    prepare_parser.add_argument("--source-grouping", required=True, type=Path)
    prepare_parser.add_argument("--preflight-lock", required=True, type=Path)
    prepare_parser.add_argument("--batch-output", required=True, type=Path)
    prepare_parser.add_argument("--grouping-output", required=True, type=Path)
    prepare_parser.add_argument("--plan-output", required=True, type=Path)

    verify_parser = commands.add_parser(
        "verify", help="Verify the canonical ledger after refresh upsert"
    )
    verify_parser.add_argument("--ledger", required=True, type=Path)
    verify_parser.add_argument("--batch", required=True, type=Path)
    verify_parser.add_argument("--preflight-lock", required=True, type=Path)
    verify_parser.add_argument("--plan", required=True, type=Path)
    verify_parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else verify(args)
    except (
        LegacyRefreshError,
        InventoryError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "status",
                    "workflow",
                    "verification_mode",
                    "source_intake_id",
                    "intake_id",
                    "item_count",
                    "policy_migration_count",
                    "action_counts",
                    "listing_authorized",
                )
                if key in result
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
