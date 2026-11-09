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


REQUIRED_RESEARCH_POLICY_VERSION = "2.9.1-pilot"


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
    supported_range = (
        f"{row['market_value_low']}-{row['market_value_high']}"
        if row.get("market_value_low") and row.get("market_value_high")
        else "not established"
    )
    sections = [
        f"{row['decision']}. {row['identified_name']}.",
        f"Condition: {row['condition_grade']}; {row['condition_notes']}",
        f"Identification: {row['identification_confidence']}; {row['identification_basis']}",
        f"Valuation: price type {row.get('price_type') or 'legacy'}; pricing confidence {row.get('valuation_confidence') or 'not recorded'}; decision confidence {row.get('decision_confidence') or 'not recorded'}. {row['comp_summary']} Supported range {row['currency']} {supported_range}; eBay {row.get('ebay_price') or 'n/a'}, local {row.get('local_price') or 'n/a'}, quick sale {row.get('quick_sale_price') or 'n/a'}.",
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


def research_tables(
    rows: list[dict[str, str]], audit_path: Path | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if audit_path is None:
        return [], []
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    audit_items = audit.get("items", [])
    if not isinstance(audit_items, list):
        raise CatalogPayloadError("Research audit items must be a list")
    by_id = {str(item.get("item_id", "")): item for item in audit_items}
    if set(by_id) != {row["item_id"] for row in rows}:
        raise CatalogPayloadError("Research audit item IDs do not match the current ledger")
    review: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row in rows:
        item = by_id[row["item_id"]]
        comps = item.get("pricing_comparables", [])
        attempts = item.get("search_attempts", [])
        review.append({
            "item_id": row["item_id"],
            "description": row["identified_name"],
            "identification_confidence": row["identification_confidence"],
            "pricing_confidence": row.get("valuation_confidence", ""),
            "decision_confidence": row.get("decision_confidence", ""),
            "recommended_action": row["decision"],
            "recommended_price": float(row["ebay_price"]) if row.get("ebay_price") else None,
            "supported_range": (
                f"${float(row['market_value_low']):.2f}-${float(row['market_value_high']):.2f}"
                if row.get("market_value_low") and row.get("market_value_high") else "Not established"
            ),
            "comparable_count": sum(comp.get("included") is True for comp in comps),
            "search_count": len(attempts),
            "evidence_status": "Needs review" if row["decision"] in {"REVIEW", "CONFIRM DONATION"} else "Validated",
            "review_reason": row.get("decision_rationale", ""),
            "reviewer_decision": "",
            "reviewer_notes": "",
        })
        for comp in comps:
            evidence.append({
                "item_id": row["item_id"],
                "comp_id": comp.get("comp_id", ""),
                "marketplace": comp.get("marketplace", ""),
                "listing_status": comp.get("listing_status", ""),
                "comparability": comp.get("comparability", ""),
                "price_usd": comp.get("normalized_unit_total_usd"),
                "sale_date": comp.get("sale_date", ""),
                "capture_date": comp.get("captured_at", ""),
                "included": "YES" if comp.get("included") is True else "NO",
                "exclusion_reason": comp.get("exclude_reason", ""),
                "source_url": comp.get("source_url", ""),
                "notes": comp.get("include_reason", "") or comp.get("match_differences", ""),
            })
    return review, evidence


def build(args: argparse.Namespace) -> dict[str, Any]:
    verification = json.loads(args.research_verification.read_text(encoding="utf-8-sig"))
    if verification.get("status") != "PASS" or verification.get("intake_id") != args.intake_id:
        raise CatalogPayloadError("A current PASS research verification is required")
    verification_mode = verification.get("verification_mode", "current-research")
    if verification_mode not in {"current-research", "policy-replay", "legacy-catalog-refresh"}:
        raise CatalogPayloadError("Unsupported research verification mode")
    if (
        verification_mode in {"current-research", "policy-replay"}
        and verification.get("research_policy_version") != REQUIRED_RESEARCH_POLICY_VERSION
    ):
        raise CatalogPayloadError(
            f"Current research must pass policy version {REQUIRED_RESEARCH_POLICY_VERSION}"
        )
    if verification.get("catalog_authorized") is False:
        raise CatalogPayloadError("Research verification does not authorize catalog creation")
    if verification_mode == "policy-replay" and verification.get("listing_authorized") is not False:
        raise CatalogPayloadError("Policy replay must explicitly prohibit listing authorization")
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
    research_review, research_evidence = research_tables(rows, args.research_audit)
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
            "estimated_value": (
                float(row["decision_basis_value"])
                if row.get("decision_basis_value")
                else None
            ),
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
        "research_review": research_review,
        "research_evidence": research_evidence,
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
        "--research-audit",
        type=Path,
        help="Optional structured research audit used to build reviewer hyperlinks and evidence tabs",
    )
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
