#!/usr/bin/env python3
"""Shared BFG v2.8 price-first marketplace policy."""

from __future__ import annotations

import math
import statistics
from typing import Any


POLICY_VERSION = "2.8.0-pilot"
AUTO_IDENTITIES = {"confirmed", "probable"}


def _weight(comp: dict[str, Any]) -> float:
    marketplace = str(comp.get("marketplace", "")).casefold()
    status = str(comp.get("listing_status", "")).casefold()
    comparability = str(comp.get("comparability", "")).casefold()
    if marketplace == "ebay" and status in {"sold", "completed"}:
        base = 1.0
    elif marketplace == "ebay" and status == "active":
        base = 0.70
    elif marketplace == "etsy" and status == "active":
        base = 0.60
    elif marketplace == "etsy" and status in {"sold", "completed"}:
        base = 0.80
    else:
        return 0.0
    return base if comparability == "exact" else base * 0.85


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


def _round_price(value: float) -> float:
    if value < 50:
        return round(value, 2)
    if value < 100:
        return round(value)
    return round(value / 5) * 5.0


def synthesize(
    item: dict[str, Any],
    *,
    safety_status: str = "CLEAR",
) -> dict[str, Any]:
    included = [
        comp
        for comp in item.get("pricing_comparables", [])
        if comp.get("included") is True and _weight(comp) > 0
    ]
    identity = str(item.get("identification_assessment", {}).get("confidence", "")).casefold()
    staff_boundary = bool(item.get("search_completion", {}).get("staff_boundary_decision"))

    if not included:
        if staff_boundary and identity in AUTO_IDENTITIES and safety_status == "CLEAR":
            return {
                "price_type": "operational",
                "pricing_confidence": "low",
                "valuation_basis": "operational_staff_price",
                "market_value_low": 40.0,
                "market_value_mid": 45.0,
                "market_value_high": 49.99,
                "decision_basis_value": 45.0,
                "etsy_price": 45.0,
                "ebay_price": 45.0,
                "decision": "CONFIRM DONATION",
                "rationale": (
                    "$40-$50 STAFF DECISION: operational $45 handling price after eight "
                    "searches; this is not a market-value claim. Confirm this item will not "
                    "be sold before donation or rehoming."
                ),
                "comp_count": 0,
            }
        return {
            "price_type": "unpriced",
            "pricing_confidence": "low",
            "valuation_basis": "insufficient_evidence",
            "market_value_low": None,
            "market_value_mid": None,
            "market_value_high": None,
            "decision_basis_value": None,
            "etsy_price": None,
            "ebay_price": None,
            "decision": "REVIEW",
            "rationale": "No defensible direct-market price; specialist or staff pricing review required.",
            "comp_count": 0,
        }

    weighted = [
        (float(comp["normalized_unit_total_usd"]), _weight(comp))
        for comp in included
    ]
    prices = [value for value, _ in weighted]
    low, high = min(prices), max(prices)
    anchor = weighted_median(weighted)
    cv = statistics.pstdev(prices) / statistics.fmean(prices) if len(prices) > 1 else 0.0
    ratio = high / low if low else math.inf
    sold = sum(
        str(comp.get("marketplace", "")).casefold() == "ebay"
        and str(comp.get("listing_status", "")).casefold() in {"sold", "completed"}
        for comp in included
    )
    exact = sum(str(comp.get("comparability", "")).casefold() == "exact" for comp in included)
    if len(included) >= 4 and sold >= 2 and cv <= 0.25 and ratio <= 1.75:
        confidence = "high"
    elif len(included) >= 3 or (
        len(included) == 2 and exact == 2 and ratio <= 1.35
    ):
        confidence = "medium"
    else:
        confidence = "low"

    etsy = min(max(anchor * 0.95, low), high)
    ebay = min(max(anchor * 1.05, low), high)
    etsy = min(max(_round_price(etsy), low), high)
    ebay = min(max(_round_price(ebay), low), high)
    price_type = "market" if confidence in {"high", "medium"} else "provisional"
    eligible_identity = identity in AUTO_IDENTITIES and safety_status == "CLEAR"
    if not eligible_identity:
        decision = "REVIEW"
        reason = "Price issued, but identification or safety confidence requires review."
    elif confidence == "low":
        if 40 <= ebay < 50:
            decision = "CONFIRM DONATION"
            reason = (
                "Low-confidence provisional price is in the staff band. Confirm this item "
                "will not be sold before donation or rehoming."
            )
        else:
            decision = "REVIEW"
            reason = "Provisional price issued; evidence is too weak for automatic sale or donation."
    elif high < 40:
        decision = "DONATE"
        reason = "Medium/high-confidence evidence keeps the credible upper value below $40."
    elif 40 <= ebay < 50:
        decision = "CONFIRM DONATION"
        reason = (
            "Recommended price is in the $40-$49.99 staff band. Confirm this item will not "
            "be sold before donation or rehoming."
        )
    elif ebay >= 55:
        decision = "SELL"
        reason = "Medium/high-confidence recommended price clears the $50 floor by at least $5."
    else:
        decision = "REVIEW"
        reason = "Recommended price is $50-$54.99 and does not clear the required $5 sell buffer."

    return {
        "price_type": price_type,
        "pricing_confidence": confidence,
        "valuation_basis": "weighted_marketplace_prices",
        "market_value_low": low,
        "market_value_mid": anchor,
        "market_value_high": high,
        "decision_basis_value": ebay,
        "etsy_price": etsy,
        "ebay_price": ebay,
        "decision": decision,
        "rationale": reason,
        "comp_count": len(included),
        "coefficient_of_variation": cv,
        "high_low_ratio": ratio,
        "sold_count": sold,
        "exact_count": exact,
    }
