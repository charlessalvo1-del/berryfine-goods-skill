#!/usr/bin/env python3
"""Replay BFG v2.8 pricing against sealed prior research without new searches."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from bfg_integrity import atomic_write_json, sha256_file
from inventory_ledger import FIELDS, atomic_write_csv, validate_row
from pricing_policy import POLICY_VERSION, synthesize


def text(value):
    return "" if value is None else str(value)


def replay(args):
    research = json.loads(args.research.read_text(encoding="utf-8-sig"))
    with args.ledger.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == args.intake_id]
    research_by_id = {item["item_id"]: item for item in research["items"]}
    if {row["item_id"] for row in source_rows} != set(research_by_id):
        raise ValueError("research and ledger item populations do not match")

    revised = []
    item_results = []
    for source in source_rows:
        row = {field: source.get(field, "") for field in FIELDS}
        result = synthesize(research_by_id[row["item_id"]], safety_status=row["safety_status"])
        row.update(
            price_type=result["price_type"],
            comp_count=text(result["comp_count"]),
            market_value_low=text(result["market_value_low"]),
            market_value_mid=text(result["market_value_mid"]),
            market_value_high=text(result["market_value_high"]),
            decision_basis_value=text(result["decision_basis_value"]),
            valuation_basis=result["valuation_basis"],
            valuation_confidence=result["pricing_confidence"],
            ebay_price=text(result["ebay_price"]),
            decision=result["decision"],
            decision_rationale=result["rationale"],
            donation_confirmation_status=("PENDING" if result["decision"] == "CONFIRM DONATION" else "NOT_REQUIRED"),
            donation_confirmed_by="",
            donation_confirmed_at="",
            listing_status="DRAFT",
            human_review_status="PENDING",
            triage_lane=(
                "Auction Candidate"
                if result["decision"] == "SELL" and float(result["ebay_price"] or 0) >= 125
                else ("Fixed Price Fast" if result["decision"] == "SELL" else "")
            ),
            notes=(source.get("notes", "") + f" Replayed under {POLICY_VERSION} without new research.").strip(),
        )
        validate_row(row, row["item_id"], enforce_current_policy=True)
        revised.append(row)
        item_results.append(
            {
                "item_id": row["item_id"],
                "prior_decision": source["decision"],
                "decision": row["decision"],
                "price_type": row["price_type"],
                "pricing_confidence": row["valuation_confidence"],
                "included_prices": result["comp_count"],
                "recommended_ebay_price": result["ebay_price"],
            }
        )

    atomic_write_csv(args.output_ledger, revised, FIELDS)
    decisions = Counter(row["decision"] for row in revised)
    price_types = Counter(row["price_type"] for row in revised)
    confidence = Counter(row["valuation_confidence"] for row in revised)
    sample_ids = set()
    for bucket in (0, 1, 2, 3, 4):
        candidates = [
            item for item in item_results
            if (item["included_prices"] if bucket < 4 else min(item["included_prices"], 4)) == bucket
        ]
        sample_ids.update(item["item_id"] for item in candidates[:5])
    sample_ids.update(item["item_id"] for item in item_results if item["price_type"] == "unpriced")
    comparison = {
        "version": 1,
        "policy_version": POLICY_VERSION,
        "replay_only": True,
        "new_research_performed": False,
        "source_research_sha256": sha256_file(args.research),
        "source_ledger_sha256": sha256_file(args.ledger),
        "intake_id": args.intake_id,
        "total_items": len(revised),
        "priced_items": sum(row["price_type"] != "unpriced" for row in revised),
        "unpriced_items": price_types["unpriced"],
        "decisions": dict(decisions),
        "needs_owner_attention": decisions["REVIEW"] + decisions["CONFIRM DONATION"],
        "human_review_pending": sum(row["human_review_status"] == "PENDING" for row in revised),
        "price_types": dict(price_types),
        "pricing_confidence": dict(confidence),
        "stratified_sample_item_ids": sorted(sample_ids),
        "stratified_sample_count": len(sample_ids),
        "items": item_results,
    }
    atomic_write_json(args.output_comparison, comparison)
    return comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--output-ledger", required=True, type=Path)
    parser.add_argument("--output-comparison", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(replay(args), indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
