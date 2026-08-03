#!/usr/bin/env python3
"""Create and update client inventory ledgers and listing queues."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bfg_integrity import sha256_json


FIELDS = [
    "client_id",
    "client_name",
    "intake_id",
    "item_id",
    "parent_item_id",
    "project_id",
    "quantity",
    "category",
    "identified_name",
    "maker",
    "model",
    "variant",
    "identification_confidence",
    "identification_basis",
    "visible_markings",
    "missing_evidence",
    "condition_grade",
    "condition_notes",
    "testing_status",
    "value_if_tested_working",
    "value_if_untested",
    "testing_notes",
    "photo_refs",
    "storage_location",
    "dimensions",
    "materials",
    "comp_count",
    "comp_summary",
    "comp_urls",
    "currency",
    "market_value_low",
    "market_value_mid",
    "market_value_high",
    "decision_basis_value",
    "valuation_basis",
    "valuation_confidence",
    "ebay_price",
    "local_price",
    "quick_sale_price",
    "decision",
    "decision_rationale",
    "decision_override_reason",
    "donation_confirmation_status",
    "donation_confirmed_by",
    "donation_confirmed_at",
    "donation_confirmation_notes",
    "triage_lane",
    "listing_title",
    "listing_description",
    "listing_status",
    "human_review_status",
    "approved_by",
    "approved_at",
    "safety_status",
    "policy_flags",
    "research_date",
    "notes",
]

REQUIRED = {
    "client_id",
    "intake_id",
    "item_id",
    "quantity",
    "category",
    "identified_name",
    "identification_confidence",
    "identification_basis",
    "condition_grade",
    "condition_notes",
    "photo_refs",
    "comp_count",
    "comp_summary",
    "currency",
    "decision",
    "decision_rationale",
    "listing_status",
    "human_review_status",
    "safety_status",
    "research_date",
}

ENUMS = {
    "identification_confidence": {
        "confirmed",
        "probable",
        "tentative",
        "unidentified",
    },
    "condition_grade": {
        "new",
        "excellent",
        "good",
        "fair",
        "poor",
        "parts",
        "unknown",
    },
    "decision": {"SELL", "DONATE", "REVIEW", "CONFIRM DONATION"},
    "donation_confirmation_status": {
        "",
        "NOT_REQUIRED",
        "PENDING",
        "CONFIRMED",
        "DECLINED",
    },
    "listing_status": {
        "READY",
        "NEEDS_PHOTOS",
        "NEEDS_RESEARCH",
        "DRAFT",
        "DO_NOT_LIST",
    },
    "human_review_status": {"PENDING", "APPROVED", "REJECTED"},
    "safety_status": {"CLEAR", "REVIEW_REQUIRED", "PROHIBITED"},
    "valuation_basis": {
        "",
        "sold_comparables",
        "auction_results",
        "active_listings",
        "price_guide",
        "expert_reference",
        "insufficient_evidence",
    },
    "valuation_confidence": {"", "low", "medium", "high"},
    "triage_lane": {
        "",
        "Auction Candidate",
        "Fixed Price Fast",
        "Local Sale",
        "Bundle / Lot",
        "Donate / Rehome / Recycle",
    },
    "testing_status": {"", "NOT_REQUIRED", "PLANNED", "PASSED", "FAILED"},
}

NUMERIC_FIELDS = {
    "quantity",
    "comp_count",
    "market_value_low",
    "market_value_mid",
    "market_value_high",
    "decision_basis_value",
    "ebay_price",
    "local_price",
    "quick_sale_price",
    "value_if_tested_working",
    "value_if_untested",
}

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
READY_VALUATION_BASES = {"sold_comparables", "auction_results", "expert_reference"}
NON_SELL_CONFIRMATION = "confirm this item will not be sold"
NEW_OPTIONAL_FIELDS = {
    "testing_status",
    "value_if_tested_working",
    "value_if_untested",
    "testing_notes",
    "donation_confirmation_status",
    "donation_confirmed_by",
    "donation_confirmed_at",
    "donation_confirmation_notes",
}


class InventoryError(ValueError):
    """Raised for invalid inventory data."""


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ";".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def load_payload(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    defaults: dict[str, Any] = {}
    if isinstance(payload, dict):
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise InventoryError("JSON object must contain an 'items' array")
        defaults = {
            key: payload.get(key, "")
            for key in ("client_id", "client_name", "intake_id")
        }
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raise InventoryError("Input must be a JSON array or an object with 'items'")

    rows: list[dict[str, str]] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise InventoryError(f"Item {index} is not an object")
        unknown = sorted(set(raw) - set(FIELDS))
        if unknown:
            raise InventoryError(
                f"Item {index} has unknown field(s): {', '.join(unknown)}"
            )
        merged = {field: text_value(raw.get(field, defaults.get(field, ""))) for field in FIELDS}
        validate_row(merged, f"item {index}", enforce_current_policy=True)
        rows.append(merged)
    if not rows:
        raise InventoryError("Input contains no items")
    return rows


def validate_row(
    row: dict[str, str], label: str, *, enforce_current_policy: bool = True
) -> None:
    missing = sorted(field for field in REQUIRED if not row.get(field, "").strip())
    if missing:
        raise InventoryError(f"{label} is missing required field(s): {', '.join(missing)}")

    for field, allowed in ENUMS.items():
        value = row[field]
        if value not in allowed:
            raise InventoryError(
                f"{label} has invalid {field}={value!r}; use {', '.join(sorted(allowed))}"
            )

    for field in FIELDS:
        if field not in NUMERIC_FIELDS and row.get(field, "").startswith(FORMULA_PREFIXES):
            raise InventoryError(
                f"{label} {field} begins with a spreadsheet formula prefix"
            )

    numbers: dict[str, float] = {}
    for field in NUMERIC_FIELDS:
        value = row.get(field, "")
        if not value:
            continue
        try:
            number = float(value)
        except ValueError as exc:
            raise InventoryError(f"{label} has non-numeric {field}={value!r}") from exc
        if not math.isfinite(number):
            raise InventoryError(f"{label} has non-finite {field}={value!r}")
        if number < 0:
            raise InventoryError(f"{label} has negative {field}={value!r}")
        numbers[field] = number

    if float(row["quantity"]) <= 0:
        raise InventoryError(f"{label} quantity must be greater than zero")
    if numbers["quantity"] != int(numbers["quantity"]):
        raise InventoryError(f"{label} quantity must be a whole number")
    if "comp_count" in numbers and numbers["comp_count"] != int(numbers["comp_count"]):
        raise InventoryError(f"{label} comp_count must be a whole number")

    currency = row["currency"]
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        raise InventoryError(f"{label} currency must be a three-letter uppercase code")
    try:
        date.fromisoformat(row["research_date"])
    except ValueError as exc:
        raise InventoryError(f"{label} research_date must use YYYY-MM-DD") from exc
    if row["decision"] in {"SELL", "DONATE", "CONFIRM DONATION"}:
        missing_values = [
            field
            for field in (
                "market_value_low",
                "market_value_mid",
                "market_value_high",
                "decision_basis_value",
            )
            if not row.get(field)
        ]
        if missing_values:
            raise InventoryError(
                f"{label} requires value estimates for {row['decision']}: "
                f"{', '.join(missing_values)}"
            )

    value_fields = ("market_value_low", "market_value_mid", "market_value_high")
    if all(field in numbers for field in value_fields):
        if not (
            numbers["market_value_low"]
            <= numbers["market_value_mid"]
            <= numbers["market_value_high"]
        ):
            raise InventoryError(f"{label} market values must satisfy low <= mid <= high")
    if "decision_basis_value" in numbers and all(
        field in numbers for field in ("market_value_low", "market_value_high")
    ):
        if not (
            numbers["market_value_low"]
            <= numbers["decision_basis_value"]
            <= numbers["market_value_high"]
        ):
            raise InventoryError(
                f"{label} decision_basis_value must fall within the market range"
            )

    basis_value = numbers.get("decision_basis_value")
    if row["decision"] == "SELL" and basis_value is not None and basis_value < 40:
        if not row["decision_override_reason"]:
            raise InventoryError(
                f"{label} SELL below $40 requires decision_override_reason"
            )
    if row["decision"] == "DONATE" and basis_value is not None and basis_value >= 50:
        raise InventoryError(
            f"{label} DONATE is invalid when decision_basis_value is $50 or more"
        )
    if enforce_current_policy and basis_value is not None and 40 <= basis_value < 50:
        confirmation_status = row["donation_confirmation_status"]
        if row["decision"] == "CONFIRM DONATION":
            if NON_SELL_CONFIRMATION not in row["decision_rationale"].casefold():
                raise InventoryError(
                    f"{label} CONFIRM DONATION must state: "
                    "Confirm this item will not be sold before donation or rehoming."
                )
            if confirmation_status != "PENDING":
                raise InventoryError(
                    f"{label} CONFIRM DONATION requires donation_confirmation_status PENDING"
                )
            if row["donation_confirmed_by"] or row["donation_confirmed_at"]:
                raise InventoryError(
                    f"{label} pending donation confirmation cannot have confirmer metadata"
                )
            if row["listing_status"] != "DRAFT" or row["human_review_status"] != "PENDING":
                raise InventoryError(
                    f"{label} CONFIRM DONATION must remain DRAFT and PENDING"
                )
        elif row["decision"] == "DONATE":
            require_donation_resolution(row, label, expected="CONFIRMED")
            if row["listing_status"] != "DO_NOT_LIST":
                raise InventoryError(
                    f"{label} confirmed donation requires listing_status DO_NOT_LIST"
                )
        elif row["decision"] == "SELL":
            require_donation_resolution(row, label, expected="DECLINED")
            if not row["decision_override_reason"]:
                raise InventoryError(
                    f"{label} SELL in the $40-through-$49.99 band requires decision_override_reason"
                )
        elif row["decision"] == "REVIEW":
            uncertainty_is_documented = (
                row["identification_confidence"] in {"tentative", "unidentified"}
                or row["valuation_confidence"] == "low"
                or row["valuation_basis"] == "insufficient_evidence"
                or row["safety_status"] != "CLEAR"
                or bool(row["missing_evidence"] or row["policy_flags"])
            )
            if not uncertainty_is_documented:
                raise InventoryError(
                    f"{label} supported $40-through-$49.99 value requires CONFIRM DONATION; "
                    "use REVIEW only for documented independent uncertainty"
                )
        else:
            raise InventoryError(
                f"{label} $40-through-$49.99 item requires CONFIRM DONATION until BFG resolves it"
            )
    elif enforce_current_policy and row["decision"] == "CONFIRM DONATION":
        raise InventoryError(
            f"{label} CONFIRM DONATION is only valid from $40 through $49.99"
        )

    if enforce_current_policy and not (basis_value is not None and 40 <= basis_value < 50):
        if row["donation_confirmation_status"] not in {"", "NOT_REQUIRED"}:
            raise InventoryError(
                f"{label} donation confirmation state is only valid in the $40-through-$49.99 band"
            )
        if row["donation_confirmed_by"] or row["donation_confirmed_at"]:
            raise InventoryError(
                f"{label} donation confirmer metadata is only valid in the $40-through-$49.99 band"
            )

    if row["testing_status"] == "PLANNED":
        testing_missing = [
            field
            for field in ("value_if_tested_working", "value_if_untested", "testing_notes")
            if not row.get(field)
        ]
        if testing_missing:
            raise InventoryError(
                f"{label} planned testing is missing: {', '.join(testing_missing)}"
            )
        if basis_value is None or not math.isclose(
            basis_value, numbers["value_if_tested_working"], abs_tol=0.01
        ):
            raise InventoryError(
                f"{label} planned testing must use value_if_tested_working as decision_basis_value"
            )
        if row["listing_status"] != "DRAFT":
            raise InventoryError(f"{label} planned testing requires listing_status DRAFT")

    if row["listing_status"] == "READY":
        ready_missing = [
            field
            for field in ("listing_title", "listing_description")
            if not row.get(field)
        ]
        if not row.get("ebay_price") and not row.get("local_price"):
            ready_missing.append("ebay_price or local_price")
        if row["decision"] != "SELL":
            ready_missing.append("decision SELL")
        if row["human_review_status"] != "APPROVED":
            ready_missing.append("human_review_status APPROVED")
        if row["safety_status"] != "CLEAR":
            ready_missing.append("safety_status CLEAR")
        if row["identification_confidence"] not in {"confirmed", "probable"}:
            ready_missing.append("confirmed or probable identification")
        if row["condition_grade"] == "unknown":
            ready_missing.append("known condition")
        if row["testing_status"] not in {"", "NOT_REQUIRED", "PASSED"}:
            ready_missing.append("testing completed or not required")
        if row["valuation_basis"] not in READY_VALUATION_BASES:
            ready_missing.append("completed-sale, auction, or expert valuation evidence")
        if row["valuation_confidence"] not in {"medium", "high"}:
            ready_missing.append("medium or high valuation confidence")
        if numbers.get("comp_count", 0) < 1 or not row["comp_urls"]:
            ready_missing.append("at least one cited comparable")
        if not row["approved_by"] or not row["approved_at"]:
            ready_missing.append("approved_by and approved_at")
        elif not valid_timestamp(row["approved_at"]):
            ready_missing.append("valid ISO approved_at timestamp")
        if row["comp_urls"] and not all(
            valid_http_url(url) for url in row["comp_urls"].split(";") if url.strip()
        ):
            ready_missing.append("valid http(s) comparable URLs")
        if ready_missing:
            raise InventoryError(
                f"{label} is READY but missing: {', '.join(ready_missing)}"
            )


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def require_donation_resolution(
    row: dict[str, str], label: str, *, expected: str
) -> None:
    if row["donation_confirmation_status"] != expected:
        raise InventoryError(
            f"{label} requires donation_confirmation_status {expected}"
        )
    if not row["donation_confirmed_by"] or not row["donation_confirmed_at"]:
        raise InventoryError(
            f"{label} requires donation_confirmed_by and donation_confirmed_at"
        )
    if not valid_timestamp(row["donation_confirmed_at"]):
        raise InventoryError(f"{label} donation_confirmed_at must be a valid ISO timestamp")


def read_ledger(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        unknown = sorted(set(fieldnames) - set(FIELDS))
        missing_required_columns = sorted(
            set(FIELDS) - set(fieldnames) - NEW_OPTIONAL_FIELDS
        )
        if unknown or missing_required_columns:
            raise InventoryError(
                "Ledger columns do not match the canonical schema; "
                f"unknown={unknown}, missing={missing_required_columns}"
            )
        rows = [{field: text_value(row.get(field, "")) for field in FIELDS} for row in reader]
    for index, row in enumerate(rows, start=2):
        validate_row(row, f"ledger row {index}", enforce_current_policy=False)
    return rows


def atomic_write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def append_revision_log(path: Path, revisions: list[dict[str, str]]) -> None:
    existing = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    previous_digest = ""
    if existing:
        previous = json.loads(existing[-1])
        previous_digest = str(previous.get("revision_digest", ""))
    encoded = list(existing)
    for revision in revisions:
        event = {**revision, "previous_revision_digest": previous_digest}
        event["revision_digest"] = sha256_json(event)
        previous_digest = event["revision_digest"]
        encoded.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(encoded) + "\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def upsert(ledger_path: Path, input_path: Path, audit_log: Path | None = None) -> None:
    current = read_ledger(ledger_path)
    incoming = load_payload(input_path)

    client_ids = {row["client_id"] for row in current + incoming}
    if len(client_ids) != 1:
        raise InventoryError(
            "A ledger must contain exactly one client_id; cross-client merge rejected"
        )

    duplicate_ids = find_duplicates(row["item_id"] for row in incoming)
    if duplicate_ids:
        raise InventoryError(
            f"Input repeats item_id(s): {', '.join(sorted(duplicate_ids))}"
        )

    by_id = {row["item_id"]: row for row in current}
    added = 0
    updated = 0
    revisions: list[dict[str, str]] = []
    for row in incoming:
        previous = by_id.get(row["item_id"])
        if row["item_id"] in by_id:
            updated += 1
        else:
            added += 1
        by_id[row["item_id"]] = row
        revisions.append({
            "client_id": row["client_id"],
            "intake_id": row["intake_id"],
            "item_id": row["item_id"],
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "operation": "UPDATE" if previous else "CREATE",
            "previous_row_digest": sha256_json(previous) if previous else "",
            "new_row_digest": sha256_json(row),
            "source_batch_sha256": sha256_json(incoming),
        })

    rows = list(by_id.values())
    rows.sort(key=lambda row: (row["intake_id"], row["item_id"]))
    atomic_write_csv(ledger_path, rows, FIELDS)
    if audit_log:
        append_revision_log(audit_log, revisions)
    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "client_id": next(iter(client_ids)),
                "added": added,
                "updated": updated,
                "total": len(rows),
            },
            indent=2,
        )
    )


def find_duplicates(values: Any) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def listing_queue(ledger_path: Path, output_path: Path) -> None:
    rows = read_ledger(ledger_path)
    queue = [
        row
        for row in rows
        if row["decision"] == "SELL"
        and row["listing_status"] == "READY"
        and row["human_review_status"] == "APPROVED"
        and row["safety_status"] == "CLEAR"
    ]
    queue.sort(
        key=lambda row: (
            row["listing_status"] != "READY",
            -float(row["market_value_mid"] or 0),
            row["item_id"],
        )
    )
    queue_fields = [
        "client_id",
        "intake_id",
        "item_id",
        "identified_name",
        "listing_status",
        "listing_title",
        "listing_description",
        "ebay_price",
        "local_price",
        "quick_sale_price",
        "currency",
        "condition_notes",
        "photo_refs",
        "comp_urls",
        "notes",
    ]
    atomic_write_csv(output_path, queue, queue_fields)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "approved_ready_items": len(queue),
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain one canonical CSV inventory ledger per client."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    upsert_parser = subparsers.add_parser(
        "upsert", help="Create or update a client ledger from a JSON batch"
    )
    upsert_parser.add_argument("--ledger", required=True, type=Path)
    upsert_parser.add_argument("--input", required=True, type=Path)
    upsert_parser.add_argument("--audit-log", type=Path, help="Append immutable item revision events")

    queue_parser = subparsers.add_parser(
        "listing-queue", help="Export SELL items for listing work"
    )
    queue_parser.add_argument("--ledger", required=True, type=Path)
    queue_parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "upsert":
            upsert(args.ledger, args.input, args.audit_log)
        elif args.command == "listing-queue":
            listing_queue(args.ledger, args.output)
    except (InventoryError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
