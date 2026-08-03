#!/usr/bin/env python3
"""Validate one-record-per-comparable research evidence against the inventory ledger."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bfg_integrity import atomic_write_json, sha256_file


class ResearchError(ValueError):
    """Raised when valuation evidence is incomplete, contradictory, or unsafe."""


REQUIRED_COMP_FIELDS = {
    "comp_id",
    "marketplace",
    "source_url",
    "transaction_status",
    "sale_date",
    "sold_price",
    "shipping",
    "currency",
    "condition",
    "comparability",
    "included",
    "include_reason",
    "captured_at",
}
COMPARABILITY_WEIGHTS = {"exact": 1.0, "near": 0.75, "broad": 0.4}


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or result < 0:
        raise ResearchError(f"{label} must be a finite non-negative number")
    return result


def validate_comp(raw: Any, item_id: str, seen: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ResearchError(f"{item_id} comparable must be an object")
    missing = sorted(REQUIRED_COMP_FIELDS - set(raw))
    if missing:
        raise ResearchError(f"{item_id} comparable is missing: {', '.join(missing)}")
    comp_id = str(raw["comp_id"]).strip()
    if not comp_id or comp_id in seen:
        raise ResearchError(f"{item_id} has blank or duplicate comp_id {comp_id!r}")
    seen.add(comp_id)
    status = str(raw["transaction_status"]).strip().casefold()
    if status not in {"sold", "completed", "auction_result"}:
        raise ResearchError(f"{item_id}/{comp_id} is not verified completed-sale evidence")
    source_url = str(raw["source_url"]).strip()
    if not valid_url(source_url):
        raise ResearchError(f"{item_id}/{comp_id} has invalid source_url")
    try:
        date.fromisoformat(str(raw["sale_date"]))
    except ValueError as exc:
        raise ResearchError(f"{item_id}/{comp_id} sale_date must use YYYY-MM-DD") from exc
    comparability = str(raw["comparability"]).strip().casefold()
    if comparability not in COMPARABILITY_WEIGHTS:
        raise ResearchError(f"{item_id}/{comp_id} comparability must be exact, near, or broad")
    currency = str(raw["currency"]).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ResearchError(f"{item_id}/{comp_id} currency must be a three-letter code")
    included = raw["included"]
    if not isinstance(included, bool):
        raise ResearchError(f"{item_id}/{comp_id} included must be boolean")
    return {
        **raw,
        "comp_id": comp_id,
        "source_url": source_url,
        "transaction_status": status,
        "currency": currency,
        "comparability": comparability,
        "sold_price": number(raw["sold_price"], f"{item_id}/{comp_id} sold_price"),
        "shipping": number(raw["shipping"], f"{item_id}/{comp_id} shipping"),
    }


def read_ledger(path: Path, intake_id: str) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == intake_id]
    if not rows:
        raise ResearchError(f"Ledger contains no rows for intake {intake_id}")
    by_id = {row.get("item_id", ""): row for row in rows}
    if "" in by_id or len(by_id) != len(rows):
        raise ResearchError("Ledger has blank or duplicate current-intake item IDs")
    return by_id


def gate(research_path: Path, ledger_path: Path, intake_id: str) -> dict[str, Any]:
    payload = json.loads(research_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ResearchError("Research file must contain an items array")
    if payload.get("intake_id") != intake_id:
        raise ResearchError("Research intake_id does not match requested intake")
    ledger = read_ledger(ledger_path, intake_id)
    seen_items: set[str] = set()
    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    seen_comps: set[str] = set()
    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise ResearchError("Research item must be an object")
        item_id = str(raw_item.get("item_id", "")).strip()
        if not item_id or item_id in seen_items or item_id not in ledger:
            raise ResearchError(f"Research has blank, duplicate, or unknown item_id {item_id!r}")
        seen_items.add(item_id)
        comps = [validate_comp(comp, item_id, seen_comps) for comp in raw_item.get("comparables", [])]
        usable = [comp for comp in comps if comp["included"]]
        totals = [comp["sold_price"] + comp["shipping"] for comp in usable]
        row = ledger[item_id]
        reported_count = int(float(row.get("comp_count") or 0))
        ledger_urls = {url.strip() for url in (row.get("comp_urls") or "").split(";") if url.strip()}
        usable_urls = {comp["source_url"] for comp in usable}
        if reported_count != len(usable) or ledger_urls != usable_urls:
            blockers.append({"item_id": item_id, "code": "COMP_RECONCILIATION", "message": "Ledger comp_count/comp_urls do not exactly match included structured comparables."})
        basis = row.get("valuation_basis", "")
        confidence = row.get("valuation_confidence", "")
        decision = row.get("decision", "")
        basis_value = float(row.get("decision_basis_value") or 0)
        threshold_distance = min(abs(basis_value - 40), abs(basis_value - 50))
        unsupported = basis == "insufficient_evidence" or confidence == "low" or not usable
        if decision != "REVIEW" and unsupported and (decision in {"DONATE", "CONFIRM DONATION"} or threshold_distance <= 15):
            blockers.append({"item_id": item_id, "code": "UNSUPPORTED_DISPOSITION", "message": "Insufficient or low-confidence evidence cannot authorize a disposal-sensitive disposition; use REVIEW until supported."})
        findings.append({
            "item_id": item_id,
            "included_comparable_count": len(usable),
            "excluded_comparable_count": len(comps) - len(usable),
            "normalized_total_low": min(totals) if totals else None,
            "normalized_total_median": statistics.median(totals) if totals else None,
            "normalized_total_high": max(totals) if totals else None,
        })
    missing_items = sorted(set(ledger) - seen_items)
    for item_id in missing_items:
        blockers.append({"item_id": item_id, "code": "MISSING_RESEARCH_ITEM", "message": "No structured research record exists for this ledger item."})
    return {
        "version": 1,
        "verification_mode": "current-research",
        "catalog_authorized": not blockers,
        "listing_authorized": False,
        "client_id": payload.get("client_id", ""),
        "intake_id": intake_id,
        "status": "PASS" if not blockers else "FAIL",
        "research_sha256": sha256_file(research_path),
        "ledger_sha256": sha256_file(ledger_path),
        "item_count": len(ledger),
        "finding_count": len(findings),
        "blocker_count": len(blockers),
        "findings": findings,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate structured completed-sale evidence against a BFG ledger.")
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = gate(args.research, args.ledger, args.intake_id)
        atomic_write_json(args.output, result)
        print(json.dumps({key: result[key] for key in ("status", "item_count", "finding_count", "blocker_count")}, indent=2))
        for blocker in result["blockers"][:20]:
            print(f"error: {blocker['item_id']} {blocker['code']}: {blocker['message']}", file=sys.stderr)
        if len(result["blockers"]) > 20:
            print(f"error: {len(result['blockers']) - 20} additional blockers are recorded in {args.output}", file=sys.stderr)
        return 0 if result["status"] == "PASS" else 2
    except (OSError, ValueError, json.JSONDecodeError, ResearchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
