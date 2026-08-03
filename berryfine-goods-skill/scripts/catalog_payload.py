#!/usr/bin/env python3
"""Build deterministic catalog and exception row payloads from validated BFG records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bfg_integrity import atomic_write_json, sha256_file, sha256_json
from inventory_ledger import InventoryError, read_ledger, validate_row


class CatalogPayloadError(ValueError):
    """Raised when catalog source records are incomplete or stale."""


def read_rows(path: Path, intake_id: str) -> list[dict[str, str]]:
    rows = [row for row in read_ledger(path) if row.get("intake_id") == intake_id]
    if not rows:
        raise CatalogPayloadError(f"Ledger has no rows for intake {intake_id}")
    for index, row in enumerate(rows, start=1):
        validate_row(row, f"catalog item {index}", enforce_current_policy=True)
    return rows


def load_grouping(path: Path, intake_id: str) -> tuple[dict[str, dict[str, str]], str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("intake_id") != intake_id or not isinstance(payload.get("groups"), list):
        raise CatalogPayloadError("Grouping file does not match intake or lacks groups")
    mapping: dict[str, dict[str, str]] = {}
    for group in payload["groups"]:
        item_id = str(group.get("item_id", "")).strip()
        sku = str(group.get("sku", "")).strip()
        group_id = str(group.get("group_id", "")).strip()
        if not item_id or not sku or not group_id or item_id in mapping:
            raise CatalogPayloadError("Every grouping row requires unique item_id, sku, and group_id")
        mapping[item_id] = {"sku": sku, "group_id": group_id}
    return mapping, sha256_file(path)


def history(row: dict[str, str]) -> str:
    sections = [
        f"{row['decision']}. {row['identified_name']}.",
        f"Condition: {row['condition_grade']}; {row['condition_notes']}",
        f"Identification: {row['identification_confidence']}; {row['identification_basis']}",
        f"Valuation: {row['comp_summary']} Supported range {row['currency']} {row['market_value_low']}-{row['market_value_high']}; eBay {row.get('ebay_price') or 'n/a'}, local {row.get('local_price') or 'n/a'}, quick sale {row.get('quick_sale_price') or 'n/a'}.",
    ]
    if row.get("testing_status") == "PLANNED":
        sections.append(f"Testing planned: tested-working value {row['value_if_tested_working']}; untested value {row['value_if_untested']}. {row['testing_notes']}")
    if row.get("variant"):
        sections.append(f"Variant/collector note: {row['variant']}")
    sections.append(row["decision_rationale"])
    return " ".join(section.strip() for section in sections if section.strip())


def exception_for(row: dict[str, str], identity: dict[str, str]) -> dict[str, str] | None:
    decision = row["decision"]
    needs_exception = decision in {"REVIEW", "CONFIRM DONATION"} or row["safety_status"] != "CLEAR" or row["listing_status"] in {"NEEDS_PHOTOS", "NEEDS_RESEARCH"}
    if not needs_exception:
        return None
    if decision == "CONFIRM DONATION":
        category = "Donation confirmation"
        required = "Confirm this item will not be sold before donation or rehoming."
    elif row["safety_status"] != "CLEAR":
        category = "Safety / policy"
        required = "Resolve safety, recall, authenticity, legality, or marketplace-policy status before listing or disposition."
    elif row["listing_status"] == "NEEDS_PHOTOS":
        category = "Missing photographs"
        required = row.get("missing_evidence") or "Obtain the photographs needed for defensible identification and condition review."
    else:
        category = "Identification / valuation uncertainty"
        required = row.get("missing_evidence") or "Resolve the documented identification or valuation uncertainty."
    issue = "; ".join(value for value in (row.get("missing_evidence", ""), row.get("policy_flags", ""), row.get("decision_rationale", "")) if value)
    return {
        "sku": identity["sku"],
        "item_id": row["item_id"],
        "photo_references": row["photo_refs"],
        "description": row["identified_name"],
        "exception_category": category,
        "issue": issue,
        "required_action": required,
        "status": "OPEN",
        "resolution_notes": "",
        "resolution_date": "",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    verification = json.loads(args.research_verification.read_text(encoding="utf-8-sig"))
    if verification.get("status") != "PASS" or verification.get("intake_id") != args.intake_id:
        raise CatalogPayloadError("A current PASS research verification is required")
    verification_mode = verification.get("verification_mode", "current-research")
    if verification_mode not in {"current-research", "legacy-catalog-refresh"}:
        raise CatalogPayloadError("Unsupported research verification mode")
    if verification.get("catalog_authorized") is False:
        raise CatalogPayloadError("Research verification does not authorize catalog creation")
    if verification_mode == "legacy-catalog-refresh":
        if verification.get("listing_authorized") is not False:
            raise CatalogPayloadError(
                "Legacy catalog refresh must explicitly prohibit listing authorization"
            )
        if not args.preflight_lock or not args.preflight_lock.is_file():
            raise CatalogPayloadError(
                "Legacy catalog refresh requires its confirmed preflight lock"
            )
        preflight = json.loads(args.preflight_lock.read_text(encoding="utf-8-sig"))
        if (
            preflight.get("status") != "CONFIRMED"
            or preflight.get("workflow") != "legacy-catalog-refresh"
            or preflight.get("intake_id") != args.intake_id
        ):
            raise CatalogPayloadError(
                "Legacy catalog refresh preflight is not confirmed or does not match"
            )
        if verification.get("preflight_lock_sha256") != sha256_file(args.preflight_lock):
            raise CatalogPayloadError("Legacy refresh verification is stale for preflight")
    if verification.get("ledger_sha256") != sha256_file(args.ledger):
        raise CatalogPayloadError("Research verification is stale for the ledger")
    rows = read_rows(args.ledger, args.intake_id)
    mapping, grouping_hash = load_grouping(args.grouping, args.intake_id)
    if set(mapping) != {row["item_id"] for row in rows}:
        raise CatalogPayloadError("Grouping item IDs do not exactly match current-intake ledger item IDs")
    catalog_rows = []
    exceptions = []
    for row in rows:
        identity = mapping[row["item_id"]]
        catalog_rows.append({
            "sku": identity["sku"],
            "item_id": row["item_id"],
            "group_id": identity["group_id"],
            "description": row["identified_name"],
            "location": "Storage",
            "quantity": int(float(row["quantity"])),
            "estimated_value": float(row.get("decision_basis_value") or 0),
            "consign_length": "",
            "history_info": history(row),
            "column_i": "",
            "recommended_action": row["decision"],
        })
        exception = exception_for(row, identity)
        if exception:
            exceptions.append(exception)
    payload: dict[str, Any] = {
        "version": 1,
        "client_name": args.client_name,
        "client_id": rows[0]["client_id"],
        "intake_id": args.intake_id,
        "ledger_sha256": sha256_file(args.ledger),
        "grouping_sha256": grouping_hash,
        "research_verification_sha256": sha256_file(args.research_verification),
        "verification_mode": verification_mode,
        "listing_authorized": False,
        "catalog_rows": catalog_rows,
        "exceptions": exceptions,
        "summary": {
            "item_count": len(catalog_rows),
            "exception_count": len(exceptions),
            "sell": sum(row["recommended_action"] == "SELL" for row in catalog_rows),
            "donate": sum(row["recommended_action"] == "DONATE" for row in catalog_rows),
            "confirm_donation": sum(row["recommended_action"] == "CONFIRM DONATION" for row in catalog_rows),
            "review": sum(row["recommended_action"] == "REVIEW" for row in catalog_rows),
        },
    }
    payload["payload_digest"] = sha256_json(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Create validated catalog/exceptions row payloads.")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--grouping", required=True, type=Path)
    parser.add_argument("--research-verification", required=True, type=Path)
    parser.add_argument(
        "--preflight-lock",
        type=Path,
        help="Required for legacy-catalog-refresh verification mode",
    )
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = build(args)
        atomic_write_json(args.output, payload)
        print(json.dumps(payload["summary"], indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, InventoryError, CatalogPayloadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
