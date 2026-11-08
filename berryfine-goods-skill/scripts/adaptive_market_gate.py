#!/usr/bin/env python3
"""Validate the BFG v2.7 adaptive active/sold marketplace research pilot."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bfg_integrity import atomic_write_json, sha256_file


POLICY_VERSION = "2.7.0-pilot"
ALLOWED_STOPS = {6, 8, 10}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_IDENTIFICATION_CONFIDENCE = {"confirmed", "probable", "tentative", "unidentified"}
ALLOWED_COMPARABILITY = {"exact", "near", "broad"}
ALLOWED_LISTING_STATUS = {"active", "sold", "completed", "auction_result"}
PRICING_MARKETPLACES = {"etsy", "ebay"}
SEARCH_HOSTS = {"google.com", "www.google.com", "bing.com", "www.bing.com"}


class GateError(ValueError):
    pass


def valid_url(value: Any) -> bool:
    parsed = urlparse(str(value).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def direct_url(value: Any) -> bool:
    parsed = urlparse(str(value).strip())
    host = parsed.netloc.casefold()
    path = parsed.path.casefold().rstrip("/")
    if host in SEARCH_HOSTS:
        return False
    if "etsy." in host:
        return path.startswith("/listing/")
    if "ebay." in host:
        return path.startswith("/itm/") or path.startswith("/p/")
    return bool(path) and not any(token in path for token in ("/search", "/category", "/browse"))


def number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GateError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or result < 0:
        raise GateError(f"{label} must be finite and non-negative")
    return result


def iso_time(value: Any, label: str) -> str:
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"{label} must be ISO-8601") from exc
    return text


def disposition(low: float, high: float) -> str:
    if high < 40:
        return "DONATE"
    if low >= 50:
        return "SELL"
    if low >= 40 and high < 50:
        return "CONFIRM DONATION"
    return "REVIEW"


def boundary_distance(low: float, high: float) -> float:
    return min(abs(low - 40), abs(high - 40), abs(low - 50), abs(high - 50))


def read_ledger(path: Path, intake_id: str) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == intake_id]
    if not rows:
        raise GateError(f"ledger contains no rows for {intake_id}")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        item_id = str(row.get("item_id", "")).strip()
        if not item_id or item_id in result:
            raise GateError("ledger item IDs must be nonblank and unique")
        result[item_id] = row
    return result


def validate_attempts(item_id: str, attempts: Any, stop_tier: int) -> tuple[set[str], int]:
    if not isinstance(attempts, list) or len(attempts) != stop_tier:
        raise GateError(f"{item_id} must record exactly {stop_tier} search attempts")
    queries: set[str] = set()
    strategies: set[str] = set()
    opened: set[str] = set()
    surfaces: set[str] = set()
    ordered_surfaces: list[str] = []
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            raise GateError(f"{item_id} attempt {index} must be an object")
        query = " ".join(str(attempt.get("query", "")).casefold().split())
        strategy = str(attempt.get("strategy", "")).strip().casefold()
        surface = str(attempt.get("surface", "")).strip()
        search_url = attempt.get("search_url")
        urls = attempt.get("opened_urls")
        if not query or query in queries or not strategy or not surface or not valid_url(search_url):
            raise GateError(f"{item_id} attempt {index} lacks distinct query, strategy, surface, or URL")
        if not isinstance(urls, list):
            raise GateError(f"{item_id} attempt {index} opened_urls must be a list")
        iso_time(attempt.get("captured_at"), f"{item_id} attempt {index} captured_at")
        queries.add(query)
        strategies.add(strategy)
        surfaces.add(surface.casefold())
        ordered_surfaces.append(surface.casefold())
        opened.update(str(url).strip() for url in urls if valid_url(url))
    if len(strategies) < 3:
        raise GateError(f"{item_id} needs at least three search strategies")
    if not any("image" in value for value in strategies | surfaces):
        raise GateError(f"{item_id} needs an image-search attempt")
    approved_web_discovery = any(
        "google" in value or "integrated web search" in value
        for value in surfaces
    )
    if not approved_web_discovery:
        raise GateError(
            f"{item_id} needs Google or approved integrated web discovery"
        )
    if not any("etsy" in value for value in surfaces):
        raise GateError(f"{item_id} needs an Etsy-first marketplace search")
    if not any("ebay" in value for value in surfaces):
        raise GateError(f"{item_id} needs an eBay marketplace cross-check")
    first_etsy = next(index for index, value in enumerate(ordered_surfaces) if "etsy" in value)
    first_ebay = next(index for index, value in enumerate(ordered_surfaces) if "ebay" in value)
    if first_etsy > first_ebay:
        raise GateError(f"{item_id} must search Etsy before eBay")
    return opened, len(strategies)


def validate_comps(item_id: str, comps: Any) -> tuple[list[dict[str, Any]], list[float], Counter[str]]:
    if not isinstance(comps, list):
        raise GateError(f"{item_id} pricing_comparables must be a list")
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    included: list[dict[str, Any]] = []
    prices: list[float] = []
    sources: Counter[str] = Counter()
    for raw in comps:
        if not isinstance(raw, dict):
            raise GateError(f"{item_id} comparable must be an object")
        comp_id = str(raw.get("comp_id", "")).strip()
        url = str(raw.get("source_url", "")).strip()
        marketplace = str(raw.get("marketplace", "")).strip().casefold()
        status = str(raw.get("listing_status", "")).strip().casefold()
        comparability = str(raw.get("comparability", "")).strip().casefold()
        is_included = raw.get("included") is True
        if not comp_id or comp_id in seen_ids or not direct_url(url) or url in seen_urls:
            raise GateError(f"{item_id} comparables need unique IDs and direct unique URLs")
        if status not in ALLOWED_LISTING_STATUS or comparability not in ALLOWED_COMPARABILITY:
            raise GateError(f"{item_id}/{comp_id} has invalid status or comparability")
        if not str(raw.get("title", "")).strip() or not str(raw.get("include_reason", "")).strip():
            raise GateError(f"{item_id}/{comp_id} needs title and include_reason")
        iso_time(raw.get("captured_at"), f"{item_id}/{comp_id} captured_at")
        digest = str(raw.get("evidence_sha256", "")).strip().casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise GateError(f"{item_id}/{comp_id} needs a SHA-256 evidence digest")
        if is_included:
            if marketplace not in PRICING_MARKETPLACES:
                raise GateError(f"{item_id}/{comp_id} auction or non-marketplace evidence cannot price the item")
            if status == "auction_result":
                raise GateError(f"{item_id}/{comp_id} auction results are identification-only")
            if comparability == "broad":
                raise GateError(f"{item_id}/{comp_id} broad comparables cannot be included")
            if raw.get("direct_page_verified") is not True:
                raise GateError(f"{item_id}/{comp_id} direct page was not verified")
            raw_quantity = number(raw.get("quantity"), f"{item_id}/{comp_id} quantity")
            if not raw_quantity.is_integer() or raw_quantity < 1:
                raise GateError(f"{item_id}/{comp_id} quantity must be a positive integer")
            quantity = int(raw_quantity)
            host = urlparse(url).netloc.casefold()
            if marketplace not in host:
                raise GateError(f"{item_id}/{comp_id} marketplace does not match its direct URL")
            price = number(raw.get("normalized_unit_total_usd"), f"{item_id}/{comp_id} normalized price")
            included.append(raw)
            prices.append(price)
            sources[marketplace] += 1
        seen_ids.add(comp_id)
        seen_urls.add(url)
    return included, prices, sources


def validate_item(item: dict[str, Any], ledger: dict[str, str]) -> dict[str, Any]:
    item_id = str(item.get("item_id", "")).strip()
    stop = item.get("search_completion")
    if not isinstance(stop, dict):
        raise GateError(f"{item_id} lacks search_completion")
    stop_tier = int(number(stop.get("stop_tier"), f"{item_id} stop_tier"))
    if stop_tier not in ALLOWED_STOPS:
        raise GateError(f"{item_id} stop tier must be 6, 8, or 10")
    if not str(stop.get("stop_reason", "")).strip():
        raise GateError(f"{item_id} needs an item-specific stop reason")
    opened_urls, strategy_count = validate_attempts(item_id, item.get("search_attempts"), stop_tier)
    included, prices, sources = validate_comps(item_id, item.get("pricing_comparables"))
    for comp in included:
        if str(comp.get("source_url", "")).strip() not in opened_urls:
            raise GateError(f"{item_id}/{comp.get('comp_id')} included price was not opened during research")
    identification = item.get("identification_assessment")
    if not isinstance(identification, dict):
        raise GateError(f"{item_id} lacks identification_assessment")
    id_conf = str(identification.get("confidence", "")).strip().casefold()
    if id_conf not in ALLOWED_IDENTIFICATION_CONFIDENCE or not str(identification.get("basis", "")).strip():
        raise GateError(f"{item_id} identification confidence or basis is invalid")
    low = number(ledger.get("market_value_low"), f"{item_id} ledger low") if ledger.get("market_value_low") else 0.0
    mid = number(ledger.get("market_value_mid"), f"{item_id} ledger mid") if ledger.get("market_value_mid") else 0.0
    high = number(ledger.get("market_value_high"), f"{item_id} ledger high") if ledger.get("market_value_high") else 0.0
    basis = number(ledger.get("decision_basis_value"), f"{item_id} ledger basis") if ledger.get("decision_basis_value") else 0.0
    if prices and not (ledger.get("market_value_low") and ledger.get("market_value_high")):
        raise GateError(f"{item_id} included prices require a supported low and high range")
    decision = str(ledger.get("decision", "")).strip().upper()
    expected = disposition(low, high) if ledger.get("market_value_low") and ledger.get("market_value_high") else "REVIEW"
    if decision != expected:
        raise GateError(f"{item_id} decision {decision} does not match supported range ({expected})")
    if decision != "REVIEW" and len(included) < 3:
        raise GateError(f"{item_id} non-REVIEW decisions require at least three prices")
    synthesis = item.get("price_synthesis")
    if not isinstance(synthesis, dict):
        raise GateError(f"{item_id} lacks price_synthesis")
    cv = 0.0
    ratio = 1.0
    if prices:
        average = statistics.fmean(prices)
        highest = max(prices)
        cv = statistics.pstdev(prices) / average if len(prices) > 1 and average else 0.0
        ratio = highest / min(prices) if min(prices) else math.inf
        h80 = highest * 0.80
        anchor = min(max((average + h80) / 2, min(prices)), highest)
        checks = {
            "cleaned_average": average,
            "highest_cleaned_price": highest,
            "high_80": h80,
            "anchor": anchor,
            "etsy_price": anchor * 0.95,
            "ebay_price": anchor * 1.05,
        }
        for field, expected_value in checks.items():
            actual = number(synthesis.get(field), f"{item_id} synthesis {field}")
            if not math.isclose(actual, expected_value, abs_tol=0.02):
                raise GateError(f"{item_id} synthesis {field} is not reproducible")
    stable = len(included) >= 4 and cv <= 0.25 and ratio <= 1.75 and boundary_distance(low, high) >= 5
    adequate_three = len(included) >= 3 and cv <= 0.25 and ratio <= 1.75 and boundary_distance(low, high) >= 5
    if stop_tier == 6 and not stable:
        raise GateError(f"{item_id} may stop at six only with four stable prices and boundary buffer")
    low_boundary_stop = (
        stop_tier == 8
        and decision == "REVIEW"
        and high < 125
        and bool(stop.get("staff_boundary_decision"))
    )
    if stop_tier == 8 and not (stable or adequate_three or low_boundary_stop):
        raise GateError(f"{item_id} search-eight stop lacks three consistent prices, stability, or low-value staff boundary rule")
    if low_boundary_stop and "$40-$50 STAFF DECISION" not in str(ledger.get("decision_rationale", "")):
        raise GateError(f"{item_id} low-value boundary review lacks operational label")
    if low_boundary_stop and not prices and (low, mid, high, basis) != (40.0, 45.0, 50.0, 45.0):
        raise GateError(
            f"{item_id} zero-price staff boundary review must record the $40-$50 range with a $45 midpoint and basis"
        )
    confidence = str(item.get("pricing_confidence", "")).strip().casefold()
    if confidence not in ALLOWED_CONFIDENCE:
        raise GateError(f"{item_id} pricing_confidence is invalid")
    if confidence == "high" and not stable:
        raise GateError(f"{item_id} high pricing confidence is not supported")
    return {
        "item_id": item_id,
        "searches": stop_tier,
        "strategies": strategy_count,
        "opened_urls": len(opened_urls),
        "included_prices": len(included),
        "marketplaces": dict(sources),
        "coefficient_of_variation": round(cv, 6),
        "high_low_ratio": round(ratio, 6) if math.isfinite(ratio) else None,
        "identification_confidence": id_conf,
        "pricing_confidence": confidence,
        "decision": decision,
    }


def gate(args: argparse.Namespace) -> dict[str, Any]:
    audit = json.loads(args.research.read_text(encoding="utf-8-sig"))
    if audit.get("research_policy_version") != POLICY_VERSION:
        raise GateError(f"research policy must be {POLICY_VERSION}")
    if audit.get("client_id") != args.client_id or audit.get("intake_id") != args.intake_id:
        raise GateError("research client or intake does not match")
    ledger = read_ledger(args.ledger, args.intake_id)
    items = audit.get("items")
    if not isinstance(items, list):
        raise GateError("research audit lacks items")
    research_by_id = {str(item.get("item_id", "")).strip(): item for item in items if isinstance(item, dict)}
    if set(research_by_id) != set(ledger):
        raise GateError("research item IDs do not exactly match ledger item IDs")
    findings = [validate_item(research_by_id[item_id], row) for item_id, row in ledger.items()]
    return {
        "version": 2,
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
        "blockers": [],
    }


def main() -> int:
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
