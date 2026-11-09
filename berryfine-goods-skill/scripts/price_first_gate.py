#!/usr/bin/env python3
"""Validate BFG v2.9 adaptive-age research and ledger decisions."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from adaptive_market_gate import (
    GateError,
    iso_time,
    number,
    read_ledger,
    validate_attempts,
    validate_comps,
)
from bfg_integrity import atomic_write_json, sha256_file
from pricing_policy import POLICY_VERSION, synthesize


MAX_BULK_AVERAGE_SEARCHES = 972 / 115
MAX_BULK_TEN_SEARCH_SHARE = 0.2261


def same_number(actual, expected, label):
    if expected is None:
        if str(actual or "").strip():
            raise GateError(f"{label} must be blank")
        return
    value = number(actual, label)
    if not math.isclose(value, float(expected), abs_tol=0.02):
        raise GateError(f"{label} is not reproducible")


def validate_item(item, ledger):
    item_id = str(item.get("item_id", "")).strip()
    stop = item.get("search_completion")
    if not isinstance(stop, dict):
        raise GateError(f"{item_id} lacks search_completion")
    stop_tier = int(number(stop.get("stop_tier"), f"{item_id} stop tier"))
    if stop_tier not in {6, 8, 10}:
        raise GateError(f"{item_id} stop tier must be 6, 8, or 10")
    opened, strategies = validate_attempts(item_id, item.get("search_attempts"), stop_tier)
    included, _, sources = validate_comps(item_id, item.get("pricing_comparables"))
    for comp in included:
        if str(comp.get("source_url", "")).strip() not in opened:
            raise GateError(f"{item_id}/{comp.get('comp_id')} included price was not opened")
        iso_time(comp.get("captured_at"), f"{item_id}/{comp.get('comp_id')} captured_at")
        status = str(comp.get("listing_status", "")).casefold()
        if status == "active" and str(comp.get("availability_status", "")).casefold() != "available":
            raise GateError(f"{item_id}/{comp.get('comp_id')} active comp must be verified available")
        if status in {"sold", "completed"} and not str(comp.get("sale_date", "")).strip():
            raise GateError(f"{item_id}/{comp.get('comp_id')} sold comp requires sale_date")
        matched = comp.get("matched_attributes")
        if not isinstance(matched, list) or not matched:
            raise GateError(f"{item_id}/{comp.get('comp_id')} requires structured matched_attributes")
        if str(comp.get("comparability", "")).casefold() == "exact" and comp.get("mismatched_attributes"):
            raise GateError(f"{item_id}/{comp.get('comp_id')} exact comp cannot contain mismatched_attributes")
        if not str(comp.get("seller_key", "")).strip():
            raise GateError(f"{item_id}/{comp.get('comp_id')} requires seller_key for cross-list checking")

    expected = synthesize(item, safety_status=ledger.get("safety_status", "CLEAR"))
    if stop_tier == 6 and expected["pricing_confidence"] != "high" and expected["decision_confidence"] != "high":
        raise GateError(f"{item_id} may stop at six only with HIGH price or decision confidence")
    if stop_tier == 8 and len(included) < 2 and not stop.get("staff_boundary_decision") and expected["decision_confidence"] != "high":
        raise GateError(f"{item_id} search-eight stop needs two prices, HIGH decision confidence, or the staff-boundary rule")
    if str(item.get("pricing_confidence", "")).casefold() != expected["pricing_confidence"]:
        raise GateError(f"{item_id} pricing_confidence does not match v2.9 synthesis")

    synthesis = item.get("price_synthesis")
    if not isinstance(synthesis, dict) or synthesis.get("method") != "weighted_marketplace_median":
        raise GateError(f"{item_id} requires weighted_marketplace_median price_synthesis")
    for field in ("market_value_low", "market_value_mid", "market_value_high", "decision_basis_value", "etsy_price", "ebay_price"):
        same_number(synthesis.get(field), expected[field], f"{item_id} synthesis {field}")
    if synthesis.get("price_type") != expected["price_type"]:
        raise GateError(f"{item_id} synthesis price_type is not reproducible")
    same_number(synthesis.get("decision_floor"), expected["decision_floor"], f"{item_id} synthesis decision_floor")
    if synthesis.get("decision_confidence") != expected["decision_confidence"]:
        raise GateError(f"{item_id} synthesis decision_confidence is not reproducible")
    if synthesis.get("pricing_confidence") != expected["pricing_confidence"]:
        raise GateError(f"{item_id} synthesis pricing_confidence is not reproducible")

    for field in ("market_value_low", "market_value_mid", "market_value_high", "decision_basis_value", "ebay_price"):
        same_number(ledger.get(field), expected[field], f"{item_id} ledger {field}")
    if ledger.get("price_type") != expected["price_type"]:
        raise GateError(f"{item_id} ledger price_type does not match")
    if ledger.get("valuation_basis") != expected["valuation_basis"]:
        raise GateError(f"{item_id} ledger valuation_basis does not match")
    if ledger.get("valuation_confidence") != expected["pricing_confidence"]:
        raise GateError(f"{item_id} ledger valuation_confidence does not match")
    if ledger.get("decision_confidence") != expected["decision_confidence"]:
        raise GateError(f"{item_id} ledger decision_confidence does not match")
    if ledger.get("decision") != expected["decision"]:
        raise GateError(f"{item_id} ledger decision does not match v2.9 policy")
    if int(float(ledger.get("comp_count") or 0)) != expected["comp_count"]:
        raise GateError(f"{item_id} ledger comp_count does not match")
    return {
        "item_id": item_id,
        "searches": stop_tier,
        "strategies": strategies,
        "included_prices": len(included),
        "marketplaces": dict(sources),
        "price_type": expected["price_type"],
        "pricing_confidence": expected["pricing_confidence"],
        "decision_confidence": expected["decision_confidence"],
        "decision": expected["decision"],
    }


def gate(args):
    audit = json.loads(args.research.read_text(encoding="utf-8-sig"))
    if audit.get("research_policy_version") != POLICY_VERSION:
        raise GateError(f"research policy must be {POLICY_VERSION}")
    if audit.get("client_id") != args.client_id or audit.get("intake_id") != args.intake_id:
        raise GateError("research client or intake does not match")
    ledger = read_ledger(args.ledger, args.intake_id)
    research = {item["item_id"]: item for item in audit.get("items", [])}
    if set(research) != set(ledger):
        raise GateError("research item IDs do not exactly match ledger item IDs")
    findings = [validate_item(research[item_id], ledger[item_id]) for item_id in ledger]
    total_searches = sum(finding["searches"] for finding in findings)
    opened_pages = sum(
        len(attempt.get("opened_urls") or [])
        for item in research.values()
        for attempt in item.get("search_attempts", [])
    )
    average_searches = total_searches / len(findings)
    ten_search_share = sum(finding["searches"] == 10 for finding in findings) / len(findings)
    if len(findings) >= 20 and average_searches > MAX_BULK_AVERAGE_SEARCHES:
        raise GateError(f"search budget average {average_searches:.2f} exceeds {MAX_BULK_AVERAGE_SEARCHES:.2f}")
    if len(findings) >= 20 and ten_search_share > MAX_BULK_TEN_SEARCH_SHARE:
        raise GateError(f"ten-search share {ten_search_share:.4f} exceeds {MAX_BULK_TEN_SEARCH_SHARE:.4f}")
    return {
        "version": 4,
        "verification_mode": "current-research",
        "research_policy_version": POLICY_VERSION,
        "catalog_authorized": True,
        "listing_authorized": False,
        "client_id": args.client_id,
        "intake_id": args.intake_id,
        "status": "PASS",
        "research_sha256": sha256_file(args.research),
        "ledger_sha256": sha256_file(args.ledger),
        "item_count": len(findings),
        "finding_count": len(findings),
        "blocker_count": 0,
        "findings": findings,
        "search_budget": {
            "total_search_attempts": total_searches,
            "average_search_attempts": round(average_searches, 2),
            "maximum_search_attempts": max(finding["searches"] for finding in findings),
            "ten_search_items": sum(finding["searches"] == 10 for finding in findings),
            "ten_search_share": round(ten_search_share, 4),
            "average_opened_pages": round(opened_pages / len(findings), 2),
            "valid_comps_per_search": round(sum(finding["included_prices"] for finding in findings) / total_searches, 4),
        },
        "blockers": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = gate(args)
        atomic_write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, GateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
