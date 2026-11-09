#!/usr/bin/env python3
"""Shared BFG v2.9 adaptive-age pricing and decision policy."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime
from typing import Any


POLICY_VERSION = "2.9.1-pilot"
AUTO_IDENTITIES = {"confirmed", "probable"}
UNAVAILABLE_MARKERS = ("unavailable", "sold out", "out of stock", "not available")


def _as_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _as_of(item: dict[str, Any]) -> date:
    explicit = _as_date(item.get("valuation_date") or item.get("research_date"))
    captures = [
        parsed
        for comp in item.get("pricing_comparables", [])
        if (parsed := _as_date(comp.get("captured_at"))) is not None
    ]
    return explicit or (max(captures) if captures else date.today())


def _months_between(later: date, earlier: date) -> float:
    return max(0.0, (later - earlier).days / 30.4375)


def _current_active(comp: dict[str, Any], as_of: date) -> bool:
    if str(comp.get("listing_status", "")).casefold() != "active":
        return False
    availability = str(comp.get("availability_status", "")).casefold()
    if availability and availability not in {"available", "active", "in_stock"}:
        return False
    title = str(comp.get("title", "")).casefold()
    if any(marker in title for marker in UNAVAILABLE_MARKERS):
        return False
    captured = _as_date(comp.get("captured_at"))
    return captured is None or _months_between(as_of, captured) <= 3


def _freshness(comp: dict[str, Any], *, as_of: date, rare: bool, current_active: bool) -> float:
    status = str(comp.get("listing_status", "")).casefold()
    if status == "active":
        return 1.0 if _current_active(comp, as_of) else 0.0
    if status not in {"sold", "completed"}:
        return 0.0
    sold = _as_date(comp.get("sale_date"))
    if sold is None:
        return 0.70  # legacy replay only; cannot earn the recent-sale route
    age = _months_between(as_of, sold)
    if age <= 12:
        return 1.0
    if age <= 24:
        return 0.90 if rare else 0.85
    if age <= 36:
        return 0.80 if rare else 0.70
    return 0.50 if rare and current_active else 0.0


def _base_weight(comp: dict[str, Any]) -> float:
    marketplace = str(comp.get("marketplace", "")).casefold()
    status = str(comp.get("listing_status", "")).casefold()
    if marketplace == "ebay" and status in {"sold", "completed"}:
        return 1.0
    if marketplace == "ebay" and status == "active":
        return 0.70
    if marketplace == "etsy" and status in {"sold", "completed"}:
        return 0.80
    if marketplace == "etsy" and status == "active":
        return 0.60
    return 0.0


def weighted_median(values: list[tuple[float, float]]) -> float:
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    if not ordered or total <= 0:
        raise ValueError("weighted median requires positive evidence weights")
    threshold = total / 2
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= threshold:
            return value
    return ordered[-1][0]


def _percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _round_price(value: float) -> float:
    if value < 50:
        return round(value, 2)
    if value < 100:
        return round(value)
    return round(value / 5) * 5.0


def _round_currency(value: float) -> float:
    """Round positive USD evidence to cents using ordinary half-up behavior."""
    return math.floor(value * 100 + 0.5) / 100


def _decision_floor(comps: list[dict[str, Any]], prices: list[float]) -> float:
    sold = any(str(comp.get("listing_status", "")).casefold() in {"sold", "completed"} for comp in comps)
    exact = sum(str(comp.get("comparability", "")).casefold() == "exact" for comp in comps)
    if sold:
        if len(prices) >= 3:
            return _percentile(prices, 0.25) * 0.95
        if len(prices) == 2:
            return min(prices) * 0.90
        return prices[0] * (0.80 if exact else 0.70)
    if len(prices) >= 3:
        return _percentile(prices, 0.25) * 0.90
    if len(prices) == 2:
        return min(prices) * (0.85 if exact else 0.80)
    return prices[0] * (0.70 if exact else 0.60)


def synthesize(item: dict[str, Any], *, safety_status: str = "CLEAR") -> dict[str, Any]:
    as_of = _as_of(item)
    rarity = str(item.get("rarity_assessment", {}).get("classification", "")).casefold()
    rare = rarity in {"scarce", "rare", "unique"}
    source = [comp for comp in item.get("pricing_comparables", []) if comp.get("included") is True]
    has_current_active = any(_current_active(comp, as_of) for comp in source)
    weighted: list[tuple[float, float]] = []
    included: list[dict[str, Any]] = []
    for comp in source:
        match = str(comp.get("comparability", "")).casefold()
        match_weight = 1.0 if match == "exact" else (0.85 if match == "near" else 0.0)
        weight = _base_weight(comp) * match_weight * _freshness(comp, as_of=as_of, rare=rare, current_active=has_current_active)
        if weight <= 0:
            continue
        included.append(comp)
        weighted.append((float(comp["normalized_unit_total_usd"]), weight))

    identity = str(item.get("identification_assessment", {}).get("confidence", "")).casefold()
    staff_boundary = bool(item.get("search_completion", {}).get("staff_boundary_decision"))
    empty_metrics = {
        "coefficient_of_variation": None, "high_low_ratio": None,
        "sold_count": 0, "recent_sold_count": 0, "exact_count": 0,
        "decision_floor": None, "excluded_pricing_comps": len(source) - len(included),
    }
    if not included:
        if staff_boundary and identity in AUTO_IDENTITIES and safety_status == "CLEAR":
            return {
                "price_type": "operational", "pricing_confidence": "low", "decision_confidence": "medium",
                "valuation_basis": "operational_staff_price", "market_value_low": 40.0,
                "market_value_mid": 45.0, "market_value_high": 49.99, "decision_basis_value": 45.0,
                "etsy_price": 45.0, "ebay_price": 45.0, "decision": "CONFIRM DONATION",
                "rationale": "$40-$50 STAFF DECISION: operational $45 handling price after eight searches; this is not a market-value claim. Confirm this item will not be sold before donation or rehoming.",
                "comp_count": 0, "decision_rule": "operational_staff_band", **empty_metrics,
            }
        return {
            "price_type": "unpriced", "pricing_confidence": "low", "decision_confidence": "low",
            "valuation_basis": "insufficient_evidence", "market_value_low": None,
            "market_value_mid": None, "market_value_high": None, "decision_basis_value": None,
            "etsy_price": None, "ebay_price": None, "decision": "REVIEW",
            "rationale": "No defensible direct-market price; specialist or staff pricing review required.",
            "comp_count": 0, "decision_rule": "unpriced_review", **empty_metrics,
        }

    prices = [value for value, _ in weighted]
    low, high = min(prices), max(prices)
    anchor = weighted_median(weighted)
    cv = statistics.pstdev(prices) / statistics.fmean(prices) if len(prices) > 1 else 0.0
    ratio = high / low if low else math.inf
    sold_comps = [comp for comp in included if str(comp.get("listing_status", "")).casefold() in {"sold", "completed"}]
    ebay_sold = sum(str(comp.get("marketplace", "")).casefold() == "ebay" for comp in sold_comps)
    recent_sold = sum(
        (sold_date := _as_date(comp.get("sale_date"))) is not None and _months_between(as_of, sold_date) <= 12
        for comp in sold_comps
    )
    exact = sum(str(comp.get("comparability", "")).casefold() == "exact" for comp in included)
    marketplaces = {str(comp.get("marketplace", "")).casefold() for comp in included}
    classic_high = len(included) >= 4 and ebay_sold >= 2 and cv <= 0.25 and ratio <= 1.75
    cross_market_high = (
        len(included) >= 3 and recent_sold >= 1 and exact >= 1
        and {"ebay", "etsy"}.issubset(marketplaces) and cv <= 0.25 and ratio <= 1.35
    )
    stable_medium = len(included) >= 3 and cv <= 0.25 and ratio <= 1.75
    close_exact_pair = len(included) == 2 and exact == 2 and ratio <= 1.35
    confidence = "high" if classic_high or cross_market_high else ("medium" if stable_medium or close_exact_pair else "low")

    etsy = min(max(_round_price(anchor * 0.95), low), high)
    ebay = min(max(_round_price(anchor * 1.05), low), high)
    floor = _decision_floor(included, prices)
    price_type = "market" if confidence in {"high", "medium"} else "provisional"
    eligible = identity in AUTO_IDENTITIES and safety_status == "CLEAR"
    rounded_floor_sell = len(included) >= 2 and floor >= 49.50 and ebay >= 50
    stable_two_comp_sell = (
        len(included) >= 2 and low >= 50 and cv <= 0.25 and ratio <= 1.75
    )
    active_comp_count = sum(
        str(comp.get("listing_status", "")).casefold() == "active" for comp in included
    )
    bracket_midpoint = _round_currency((low + high) / 2)
    controlled_active_bracket_sell = (
        len(included) == 2
        and active_comp_count == 2
        and 40 <= low < 50 <= high
        and bracket_midpoint >= 47.50
        and ratio <= 1.35
    )
    decision_rule = "review"
    if not eligible:
        decision, decision_confidence = "REVIEW", "low"
        reason = "Price issued, but identification or safety confidence requires review."
        decision_rule = "identity_or_safety_review"
    elif floor >= 55:
        decision = "SELL"
        decision_confidence = "high" if floor >= 65 and len(included) >= 2 else "medium"
        reason = f"Conservative decision floor ${floor:.2f} clears the $55 automatic-sale threshold."
        decision_rule = "decision_floor_55"
    elif rounded_floor_sell:
        decision, decision_confidence = "SELL", "medium"
        ebay = max(50.0, ebay)
        reason = (
            f"Conservative decision floor ${floor:.2f} rounds to the $50 sale boundary; "
            "list at $50 with human approval."
        )
        decision_rule = "rounded_floor_50"
    elif stable_two_comp_sell:
        decision, decision_confidence = "SELL", "medium"
        ebay = max(50.0, ebay)
        reason = (
            f"At least two stable direct prices have a $50-or-higher observed floor "
            f"(CV {cv:.3f}; ratio {ratio:.3f}); list at no less than $50 with human approval."
        )
        decision_rule = "stable_two_comp_floor_50"
    elif controlled_active_bracket_sell:
        decision, decision_confidence = "SELL", "medium"
        ebay = 50.0
        reason = (
            f"Two direct active prices tightly bracket $50 (midpoint ${bracket_midpoint:.2f}; "
            f"ratio {ratio:.3f}); use a controlled $50 test listing with human approval."
        )
        decision_rule = "controlled_active_bracket_50"
    elif confidence in {"high", "medium"} and high < 40:
        decision = "DONATE"
        decision_confidence = "high" if high < 35 else "medium"
        reason = "Stable evidence keeps the complete credible value range below $40."
        decision_rule = "stable_range_below_40"
    elif 40 <= ebay < 50:
        decision, decision_confidence = "CONFIRM DONATION", "medium"
        reason = "Recommended price is in the $40-$49.99 staff band. Confirm this item will not be sold before donation or rehoming."
        decision_rule = "staff_band_40_49_99"
    else:
        decision, decision_confidence = "REVIEW", "low"
        reason = f"Price issued, but conservative decision floor ${floor:.2f} does not safely resolve a disposition threshold."

    basis = "time_weighted_marketplace_prices" if sold_comps else "active_market_decision_floor"
    return {
        "price_type": price_type, "pricing_confidence": confidence,
        "decision_confidence": decision_confidence, "valuation_basis": basis,
        "market_value_low": low, "market_value_mid": anchor, "market_value_high": high,
        "decision_basis_value": ebay, "etsy_price": etsy, "ebay_price": ebay,
        "decision": decision, "rationale": reason, "comp_count": len(included),
        "coefficient_of_variation": cv, "high_low_ratio": ratio,
        "sold_count": len(sold_comps), "recent_sold_count": recent_sold,
        "exact_count": exact, "decision_floor": floor,
        "excluded_pricing_comps": len(source) - len(included),
        "decision_rule": decision_rule,
    }
