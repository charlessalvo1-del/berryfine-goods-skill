#!/usr/bin/env python3
"""Fail closed when item-specific research is absent, shallow, or unreconciled."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bfg_integrity import atomic_write_json, sha256_file


class ResearchError(ValueError):
    """Raised when valuation evidence is malformed or unsafe."""


REQUIRED_COMP_FIELDS = {
    "comp_id", "title", "marketplace", "source_url", "transaction_status",
    "sale_date", "sold_price", "shipping", "currency", "condition",
    "comparability", "included", "include_reason", "captured_at",
}
REQUIRED_ATTEMPT_FIELDS = {
    "attempt_id", "query", "strategy", "surface", "search_url", "result_count",
    "result_urls", "opened_urls", "outcome", "captured_at",
}
REQUIRED_EXHAUSTION_FIELDS = {
    "reason_code", "summary", "next_evidence", "closest_candidate_urls",
    "candidate_identifications_considered",
}
COMPARABILITY_WEIGHTS = {"exact": 1.0, "near": 0.75, "broad": 0.4}
ALLOWED_STRATEGIES = {
    "marking_exact", "visual_attributes", "image_search", "category_synonym",
    "marketplace_sold", "regional_language", "candidate_confirmation",
}
ALLOWED_OUTCOMES = {
    "candidate_found", "comp_found", "no_useful_result", "rejected_mismatch", "blocked",
}
ALLOWED_EXHAUSTION_REASONS = {
    "no_candidates", "no_completed_sales", "conflicting_identity",
    "inaccessible_sold_data", "insufficient_photo_detail",
}
ALLOWED_CHALLENGE_OUTCOMES = {"confirmed_exhaustion", "correction_found", "not_searchable"}
GENERIC_NAME_WORDS = {
    "a", "an", "and", "assorted", "black", "blue", "box", "brown", "ceramic",
    "clear", "collection", "decorative", "glass", "green", "item", "lot", "metal",
    "mixed", "orange", "pair", "plastic", "red", "round", "set", "silver", "small",
    "the", "vintage", "white", "wood", "wooden", "yellow",
}
PLACEHOLDER_MARKINGS = {
    "visible photographed form, decoration, materials and any legible product wording used; no hidden mark was inferred.",
    "none visible",
    "no visible markings",
}
SEARCH_HOSTS = {
    "bing.com", "www.bing.com", "google.com", "www.google.com",
    "images.google.com", "search.yahoo.com",
}
MIN_SEARCH_QUERIES = 4
MIN_SEARCH_STRATEGIES = 3
MIN_DIRECT_OPENED_PAGES = 4
MIN_COMPLETED_COMPS = 3
BORDERLINE_COMPLETED_COMPS = 5
RESEARCH_POLICY_VERSION = "2.5.0"


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def direct_evidence_url(value: str) -> bool:
    """Return true only for an opened result page, not a search/category page."""
    parsed = urlparse(value)
    host = parsed.netloc.casefold()
    path = parsed.path.casefold().rstrip("/")
    if host in SEARCH_HOSTS:
        return False
    if host in {"ebay.com", "ebay.co.uk"} or host.endswith((".ebay.com", ".ebay.co.uk")):
        return path.startswith("/itm/")
    if host == "mercari.com" or host.endswith(".mercari.com"):
        return path.startswith("/us/item/")
    if host == "etsy.com" or host.endswith(".etsy.com"):
        return path.startswith("/listing/")
    if any(marker in path for marker in ("/search", "/category/", "/categories/", "/pricing/", "/collections/", "/browse/")):
        return False
    return bool(path)


def number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or result < 0:
        raise ResearchError(f"{label} must be a finite non-negative number")
    return result


def integer(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"{label} must be an integer") from exc
    if result < 0:
        raise ResearchError(f"{label} must be non-negative")
    return result


def iso_timestamp(value: Any, label: str) -> str:
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchError(f"{label} must be an ISO-8601 timestamp") from exc
    return text


def normalize_query(value: Any) -> str:
    return " ".join(str(value).casefold().split())


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
    if not str(raw["title"]).strip():
        raise ResearchError(f"{item_id}/{comp_id} has blank title")
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
    if not isinstance(raw["included"], bool):
        raise ResearchError(f"{item_id}/{comp_id} included must be boolean")
    iso_timestamp(raw["captured_at"], f"{item_id}/{comp_id} captured_at")
    sold_price = number(raw["sold_price"], f"{item_id}/{comp_id} sold_price")
    shipping = number(raw["shipping"], f"{item_id}/{comp_id} shipping")
    normalized_total_usd: float | None = sold_price + shipping if currency == "USD" else None
    if currency != "USD" and raw.get("normalized_total_usd") not in (None, ""):
        normalized_total_usd = number(raw["normalized_total_usd"], f"{item_id}/{comp_id} normalized_total_usd")
        if not str(raw.get("normalization_note", "")).strip():
            raise ResearchError(f"{item_id}/{comp_id} foreign-currency normalization requires normalization_note")
    return {
        **raw, "comp_id": comp_id, "source_url": source_url,
        "transaction_status": status, "currency": currency,
        "comparability": comparability,
        "sold_price": sold_price, "shipping": shipping,
        "normalized_total_usd": normalized_total_usd,
    }


def validate_attempt(raw: Any, item_id: str, seen: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ResearchError(f"{item_id} search attempt must be an object")
    missing = sorted(REQUIRED_ATTEMPT_FIELDS - set(raw))
    if missing:
        raise ResearchError(f"{item_id} search attempt is missing: {', '.join(missing)}")
    attempt_id = str(raw["attempt_id"]).strip()
    if not attempt_id or attempt_id in seen:
        raise ResearchError(f"{item_id} has blank or duplicate attempt_id {attempt_id!r}")
    seen.add(attempt_id)
    query = normalize_query(raw["query"])
    if not query:
        raise ResearchError(f"{item_id}/{attempt_id} has blank query")
    strategy = str(raw["strategy"]).strip().casefold()
    if strategy not in ALLOWED_STRATEGIES:
        raise ResearchError(f"{item_id}/{attempt_id} has unsupported strategy {strategy!r}")
    surface = str(raw["surface"]).strip()
    if not surface:
        raise ResearchError(f"{item_id}/{attempt_id} has blank surface")
    search_url = str(raw["search_url"]).strip()
    if not valid_url(search_url):
        raise ResearchError(f"{item_id}/{attempt_id} has invalid search_url")
    result_count = integer(raw["result_count"], f"{item_id}/{attempt_id} result_count")
    result_urls = raw["result_urls"]
    opened_urls = raw["opened_urls"]
    if not isinstance(result_urls, list) or any(not valid_url(str(url)) for url in result_urls):
        raise ResearchError(f"{item_id}/{attempt_id} result_urls must be a list of HTTP(S) URLs")
    if not isinstance(opened_urls, list) or any(not valid_url(str(url)) for url in opened_urls):
        raise ResearchError(f"{item_id}/{attempt_id} opened_urls must be a list of HTTP(S) URLs")
    if result_count < len(result_urls):
        raise ResearchError(f"{item_id}/{attempt_id} result_count is smaller than result_urls")
    if not set(opened_urls).issubset(set(result_urls)):
        raise ResearchError(f"{item_id}/{attempt_id} opened_urls must also appear in result_urls")
    if result_count == 0 and (result_urls or opened_urls):
        raise ResearchError(f"{item_id}/{attempt_id} zero results cannot include result URLs")
    if result_count > 0 and not opened_urls:
        raise ResearchError(f"{item_id}/{attempt_id} must open at least one returned result")
    outcome = str(raw["outcome"]).strip().casefold()
    if outcome not in ALLOWED_OUTCOMES:
        raise ResearchError(f"{item_id}/{attempt_id} has unsupported outcome {outcome!r}")
    if outcome in {"candidate_found", "comp_found"} and not opened_urls:
        raise ResearchError(f"{item_id}/{attempt_id} {outcome} requires opened evidence")
    return {
        **raw, "attempt_id": attempt_id, "query": query, "strategy": strategy,
        "surface": surface, "search_url": search_url, "result_urls": result_urls,
        "opened_urls": opened_urls, "outcome": outcome, "result_count": result_count,
        "captured_at": iso_timestamp(raw["captured_at"], f"{item_id}/{attempt_id} captured_at"),
    }


def validate_exhaustion(raw: Any, item_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ResearchError(f"{item_id} exhaustion must be an object")
    missing = sorted(REQUIRED_EXHAUSTION_FIELDS - set(raw))
    if missing:
        raise ResearchError(f"{item_id} exhaustion is missing: {', '.join(missing)}")
    reason = str(raw["reason_code"]).strip().casefold()
    if reason not in ALLOWED_EXHAUSTION_REASONS:
        raise ResearchError(f"{item_id} has unsupported exhaustion reason {reason!r}")
    if not str(raw["summary"]).strip() or not str(raw["next_evidence"]).strip():
        raise ResearchError(f"{item_id} exhaustion summary and next_evidence must be nonblank")
    urls = raw["closest_candidate_urls"]
    candidates = raw["candidate_identifications_considered"]
    if not isinstance(urls, list) or any(not valid_url(str(url)) for url in urls):
        raise ResearchError(f"{item_id} closest_candidate_urls must be a list of HTTP(S) URLs")
    if not isinstance(candidates, list) or any(not str(candidate).strip() for candidate in candidates):
        raise ResearchError(f"{item_id} candidate_identifications_considered must be a list of nonblank strings")
    return {**raw, "reason_code": reason}


def validate_price_synthesis(
    raw: Any,
    item_id: str,
    usable: list[dict[str, Any]],
    normalized_totals: list[float],
    ledger_mid: float,
    decision_basis: float,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ResearchError(f"{item_id} price_synthesis must be an object")
    required = {"method", "comp_ids", "raw_median", "adjusted_mid", "adjustment_reason"}
    missing = sorted(required - set(raw))
    if missing:
        raise ResearchError(f"{item_id} price_synthesis is missing: {', '.join(missing)}")
    if str(raw["method"]).strip().casefold() != "median":
        raise ResearchError(f"{item_id} price_synthesis method must be median")
    comp_ids = raw["comp_ids"]
    expected_ids = {comp["comp_id"] for comp in usable}
    if not isinstance(comp_ids, list) or len(comp_ids) != len(set(comp_ids)) or set(comp_ids) != expected_ids:
        raise ResearchError(f"{item_id} price_synthesis comp_ids must exactly match included comparables")
    if not usable or len(normalized_totals) != len(usable):
        raise ResearchError(f"{item_id} cannot synthesize price until every included comp is USD-normalized")
    calculated_median = statistics.median(normalized_totals)
    recorded_median = number(raw["raw_median"], f"{item_id} price_synthesis raw_median")
    adjusted_mid = number(raw["adjusted_mid"], f"{item_id} price_synthesis adjusted_mid")
    if not math.isclose(recorded_median, calculated_median, abs_tol=0.01):
        raise ResearchError(f"{item_id} recorded raw median does not match included comparable totals")
    if not math.isclose(adjusted_mid, ledger_mid, abs_tol=0.01) or not math.isclose(adjusted_mid, decision_basis, abs_tol=0.01):
        raise ResearchError(f"{item_id} adjusted median must match ledger mid and decision-basis values")
    reason = str(raw["adjustment_reason"]).strip()
    if not math.isclose(adjusted_mid, recorded_median, abs_tol=0.01) and not reason:
        raise ResearchError(f"{item_id} price adjustment requires a nonblank reason")
    return {
        "method": "median",
        "raw_median": recorded_median,
        "adjusted_mid": adjusted_mid,
        "adjusted": not math.isclose(adjusted_mid, recorded_median, abs_tol=0.01),
    }


def discriminating_tokens(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", name.casefold()) if len(token) >= 3 and token not in GENERIC_NAME_WORDS}


def read_ledger(path: Path, intake_id: str) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("intake_id") == intake_id]
    if not rows:
        raise ResearchError(f"Ledger contains no rows for intake {intake_id}")
    by_id = {row.get("item_id", ""): row for row in rows}
    if "" in by_id or len(by_id) != len(rows):
        raise ResearchError("Ledger has blank or duplicate current-intake item IDs")
    return by_id


def add_blocker(entries: list[dict[str, str]], item_id: str, code: str, message: str) -> None:
    entries.append({"item_id": item_id, "code": code, "message": message})


def validate_challenge(raw: Any, ledger_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ResearchError("challenge_review must be an object")
    required = {
        "review_run_id", "created_at", "reviewer", "independent_context",
        "first_pass_zero_comp_item_ids", "sampled_item_ids", "findings",
        "corrections_integrated", "expanded_to_all_first_pass_zero_comp",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ResearchError(f"challenge_review is missing: {', '.join(missing)}")
    if not str(raw["review_run_id"]).strip() or not str(raw["reviewer"]).strip():
        raise ResearchError("challenge_review run ID and reviewer must be nonblank")
    iso_timestamp(raw["created_at"], "challenge_review created_at")
    if raw["independent_context"] is not True:
        raise ResearchError("challenge_review must declare independent_context=true")
    if raw["corrections_integrated"] is not True:
        raise ResearchError("challenge_review corrections must be integrated before authorization")
    sampled = raw["sampled_item_ids"]
    first_pass = raw["first_pass_zero_comp_item_ids"]
    findings = raw["findings"]
    if not isinstance(sampled, list) or len(sampled) != len(set(sampled)):
        raise ResearchError("challenge_review sampled_item_ids must be a unique list")
    if not isinstance(first_pass, list) or not first_pass or len(first_pass) != len(set(first_pass)):
        raise ResearchError("challenge_review first_pass_zero_comp_item_ids must be a nonempty unique list")
    if not set(sampled).issubset(ledger_ids):
        raise ResearchError("challenge_review contains an unknown sampled item ID")
    if not set(first_pass).issubset(ledger_ids):
        raise ResearchError("challenge_review contains an unknown first-pass zero-comp item ID")
    if set(sampled) != set(first_pass):
        raise ResearchError("challenge_review must sample every first-pass zero-comp item")
    if raw["expanded_to_all_first_pass_zero_comp"] is not True:
        raise ResearchError("challenge_review must expand to all first-pass zero-comp items")
    if not isinstance(findings, list):
        raise ResearchError("challenge_review findings must be a list")
    finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ResearchError("challenge_review finding must be an object")
        item_id = str(finding.get("item_id", "")).strip()
        outcome = str(finding.get("outcome", "")).strip().casefold()
        summary = str(finding.get("summary", "")).strip()
        urls = finding.get("opened_urls")
        if not item_id or item_id in finding_ids or outcome not in ALLOWED_CHALLENGE_OUTCOMES or not summary:
            raise ResearchError("challenge_review finding has blank, duplicate, or invalid fields")
        if not isinstance(urls, list) or any(not valid_url(str(url)) for url in urls):
            raise ResearchError(f"challenge_review/{item_id} opened_urls must contain valid HTTP(S) URLs")
        if outcome != "not_searchable" and not urls:
            raise ResearchError(f"challenge_review/{item_id} requires opened evidence")
        if outcome != "not_searchable" and not any(direct_evidence_url(str(url)) for url in urls):
            raise ResearchError(f"challenge_review/{item_id} requires a direct opened result page")
        finding_ids.add(item_id)
    if finding_ids != set(sampled):
        raise ResearchError("challenge_review findings must exactly match sampled_item_ids")
    return {
        "sampled": set(sampled),
        "first_pass": set(first_pass),
        "correction_count": sum(
            str(finding.get("outcome", "")).strip().casefold() == "correction_found"
            for finding in findings
        ),
    }


def gate(research_path: Path, ledger_path: Path, intake_id: str) -> dict[str, Any]:
    payload = json.loads(research_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ResearchError("Research file must contain an items array")
    if payload.get("version") != 2:
        raise ResearchError("Current research must use research audit schema version 2")
    if payload.get("intake_id") != intake_id:
        raise ResearchError("Research intake_id does not match requested intake")
    ledger = read_ledger(ledger_path, intake_id)
    seen_items: set[str] = set()
    seen_comps: set[str] = set()
    seen_attempts: set[str] = set()
    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    included_url_items: dict[str, set[str]] = defaultdict(set)
    zero_comp_item_ids: set[str] = set()
    exhaustion_summaries: dict[str, list[str]] = defaultdict(list)

    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise ResearchError("Research item must be an object")
        item_id = str(raw_item.get("item_id", "")).strip()
        if not item_id or item_id in seen_items or item_id not in ledger:
            raise ResearchError(f"Research has blank, duplicate, or unknown item_id {item_id!r}")
        seen_items.add(item_id)
        attempts = [validate_attempt(value, item_id, seen_attempts) for value in raw_item.get("search_attempts", [])]
        comps = [validate_comp(value, item_id, seen_comps) for value in raw_item.get("comparables", [])]
        usable = [comp for comp in comps if comp["included"]]
        totals = [comp["normalized_total_usd"] for comp in usable if comp["normalized_total_usd"] is not None]
        for comp in usable:
            included_url_items[comp["source_url"]].add(item_id)

        queries = {attempt["query"] for attempt in attempts}
        strategies = {attempt["strategy"] for attempt in attempts}
        surfaces = {attempt["surface"].casefold() for attempt in attempts}
        direct_opened = {
            url for attempt in attempts for url in attempt["opened_urls"]
            if direct_evidence_url(str(url))
        }
        image_opened = {
            url for attempt in attempts if attempt["strategy"] == "image_search"
            for url in attempt["opened_urls"] if direct_evidence_url(str(url))
        }
        sold_opened = {
            url for attempt in attempts if attempt["strategy"] == "marketplace_sold"
            for url in attempt["opened_urls"] if direct_evidence_url(str(url))
        }
        google_used = any("google." in urlparse(attempt["search_url"]).netloc.casefold() for attempt in attempts)
        if (
            len(queries) < MIN_SEARCH_QUERIES
            or len(strategies) < MIN_SEARCH_STRATEGIES
            or "image_search" not in strategies
            or "marketplace_sold" not in strategies
            or len(surfaces) < 2
            or not google_used
        ):
            add_blocker(
                blockers, item_id, "INSUFFICIENT_SEARCH_COVERAGE",
                "Every item requires four distinct queries, at least three strategies, Google web/image discovery, marketplace-sold research, and at least two surfaces.",
            )
        if len(direct_opened) < MIN_DIRECT_OPENED_PAGES or not image_opened or not sold_opened:
            add_blocker(
                blockers, item_id, "SHALLOW_RESEARCH",
                "Every item requires at least four unique direct opened pages, including image-search evidence and completed-sale or auction evidence.",
            )
        if sum(attempt["result_count"] for attempt in attempts) == 0:
            add_blocker(blockers, item_id, "NO_SEARCH_RESULTS", "All recorded searches returned zero results; research cannot be authorized without opened web evidence or a documented access failure.")
        name_tokens = discriminating_tokens(ledger[item_id].get("identified_name", ""))
        if name_tokens and not any(name_tokens & set(query.split()) for query in queries):
            add_blocker(blockers, item_id, "NON_SPECIFIC_SEARCH", "No recorded query contains a discriminating token from the identified item name.")

        row = ledger[item_id]
        markings = normalize_query(row.get("visible_markings", ""))
        if markings in PLACEHOLDER_MARKINGS or markings.startswith("visible photographed form"):
            add_blocker(blockers, item_id, "PLACEHOLDER_VISIBLE_MARKINGS", "Visible markings must transcribe actual evidence or remain blank; boilerplate is not acceptable.")
        reported_count = int(float(row.get("comp_count") or 0))
        ledger_urls = {url.strip() for url in (row.get("comp_urls") or "").split(";") if url.strip()}
        usable_urls = {comp["source_url"] for comp in usable}
        if reported_count != len(usable) or ledger_urls != usable_urls:
            add_blocker(blockers, item_id, "COMP_RECONCILIATION", "Ledger comp_count/comp_urls do not exactly match included structured comparables.")

        basis = row.get("valuation_basis", "")
        confidence = row.get("valuation_confidence", "").casefold()
        decision = row.get("decision", "").upper()
        exact_or_near_count = sum(comp["comparability"] in {"exact", "near"} for comp in usable)
        unsupported = basis == "insufficient_evidence" or confidence not in {"medium", "high"} or not usable
        if decision != "REVIEW" and unsupported:
            add_blocker(blockers, item_id, "UNSUPPORTED_DISPOSITION", "A non-REVIEW decision requires usable evidence, a supported basis, and medium or high confidence.")
        unique_usable_urls = {comp["source_url"] for comp in usable}
        if decision != "REVIEW" and len(unique_usable_urls) < MIN_COMPLETED_COMPS:
            add_blocker(blockers, item_id, "INSUFFICIENT_COMPLETED_COMPS", "A non-REVIEW decision requires at least three unique completed-sale transactions.")
        if decision != "REVIEW" and exact_or_near_count < MIN_COMPLETED_COMPS:
            add_blocker(blockers, item_id, "INSUFFICIENT_NEAR_COMPS", "At least three included comparables must be exact or near matches before disposition.")
        if decision != "REVIEW" and not unique_usable_urls.issubset(direct_opened):
            add_blocker(blockers, item_id, "UNOPENED_COMPARABLE", "Every included comparable must appear in the item's direct opened evidence.")
        if decision != "REVIEW" and len(totals) != len(usable):
            add_blocker(blockers, item_id, "UNNORMALIZED_CURRENCY", "Non-USD completed sales require a documented USD-normalized value before disposition.")

        price_synthesis: dict[str, Any] | None = None
        raw_values = [row.get(name) for name in ("market_value_low", "market_value_mid", "market_value_high", "decision_basis_value")]
        if decision != "REVIEW" or any(str(value or "").strip() for value in raw_values):
            try:
                low = number(row.get("market_value_low"), f"{item_id} market_value_low")
                mid = number(row.get("market_value_mid"), f"{item_id} market_value_mid")
                high = number(row.get("market_value_high"), f"{item_id} market_value_high")
                basis_value = number(row.get("decision_basis_value"), f"{item_id} decision_basis_value")
                if not low <= mid <= high or not low <= basis_value <= high:
                    add_blocker(blockers, item_id, "INVALID_VALUE_RANGE", "Low, mid, high, and decision-basis values must form one ordered supported range.")
                boundary_zone = high >= 30 and low <= 65
                if decision != "REVIEW" and boundary_zone and len(unique_usable_urls) < BORDERLINE_COMPLETED_COMPS:
                    add_blocker(blockers, item_id, "BORDERLINE_RESEARCH_TOO_SHALLOW", "A value range touching $30-$65 requires at least five unique completed-sale transactions.")
                if decision == "DONATE" and high >= 40:
                    add_blocker(blockers, item_id, "RANGE_CROSSES_DISPOSITION_BOUNDARY", "DONATE is allowed only when the supported high value is below $40.")
                elif decision == "CONFIRM DONATION" and not (low >= 40 and high < 50):
                    add_blocker(blockers, item_id, "RANGE_CROSSES_DISPOSITION_BOUNDARY", "CONFIRM DONATION requires the entire supported range to remain from $40 through $49.99.")
                elif decision == "SELL" and low < 50:
                    add_blocker(blockers, item_id, "RANGE_CROSSES_DISPOSITION_BOUNDARY", "SELL requires the supported low value to be at least $50; otherwise use REVIEW.")
                if decision != "REVIEW":
                    try:
                        price_synthesis = validate_price_synthesis(
                            raw_item.get("price_synthesis"), item_id, usable, totals, mid, basis_value
                        )
                    except ResearchError as exc:
                        add_blocker(blockers, item_id, "INVALID_PRICE_SYNTHESIS", str(exc))
            except ResearchError as exc:
                add_blocker(blockers, item_id, "INVALID_VALUE_RANGE", str(exc))

        exhausted = False
        if decision == "REVIEW" and len(usable) < MIN_COMPLETED_COMPS:
            try:
                exhaustion = validate_exhaustion(raw_item.get("exhaustion"), item_id)
                exhaustion_summaries[normalize_query(exhaustion["summary"])].append(item_id)
                exhausted = True
            except ResearchError as exc:
                add_blocker(blockers, item_id, "MISSING_EXHAUSTION_RECORD", str(exc))
        if not usable:
            zero_comp_item_ids.add(item_id)
            if decision != "REVIEW":
                add_blocker(blockers, item_id, "ZERO_COMP_DISPOSITION", "An item with no usable completed-sale comparable must remain REVIEW.")
            if len(queries) < MIN_SEARCH_QUERIES or "image_search" not in strategies or "marketplace_sold" not in strategies or len(surfaces) < 2:
                add_blocker(blockers, item_id, "SEARCH_NOT_EXHAUSTED", "Zero-comp REVIEW requires four distinct queries, image search, marketplace sold search, and at least two surfaces.")
            if len(direct_opened) < MIN_DIRECT_OPENED_PAGES or not image_opened or not sold_opened:
                add_blocker(
                    blockers, item_id, "SHALLOW_ZERO_COMP_RESEARCH",
                    "Zero-comp REVIEW requires at least four unique direct opened result pages, including opened image-search and completed-sale/auction evidence.",
                )

        findings.append({
            "item_id": item_id, "search_attempt_count": len(attempts),
            "search_query_count": len(queries), "search_strategy_count": len(strategies),
            "search_surface_count": len(surfaces), "search_exhausted": exhausted,
            "direct_opened_page_count": len(direct_opened),
            "included_comparable_count": len(usable),
            "excluded_comparable_count": len(comps) - len(usable),
            "normalized_total_low": min(totals) if totals else None,
            "normalized_total_median": statistics.median(totals) if totals else None,
            "normalized_total_high": max(totals) if totals else None,
            "price_synthesis": price_synthesis,
        })

    for item_id in sorted(set(ledger) - seen_items):
        add_blocker(blockers, item_id, "MISSING_RESEARCH_ITEM", "No structured research record exists for this ledger item.")
    for url, item_ids in sorted(included_url_items.items()):
        if len(item_ids) > 3:
            for item_id in sorted(item_ids):
                add_blocker(blockers, item_id, "OVERUSED_COMPARABLE", f"Comparable URL is reused across {len(item_ids)} items: {url}")
    for summary, item_ids in sorted(exhaustion_summaries.items()):
        if summary and len(item_ids) > 3:
            for item_id in item_ids:
                add_blocker(blockers, item_id, "BOILERPLATE_EXHAUSTION", f"The same exhaustion summary is reused across {len(item_ids)} items; each conclusion must be item-specific.")

    challenge_sample_count = 0
    challenge_correction_count = 0
    if len(zero_comp_item_ids) >= 10:
        if not isinstance(payload.get("challenge_review"), dict):
            add_blocker(blockers, "*", "MISSING_CHALLENGE_REVIEW", "Ten or more zero-comp items require an independent challenge of the entire first-pass zero-comp population.")
        else:
            challenge = validate_challenge(payload["challenge_review"], set(ledger))
            challenge_sample_count = len(challenge["sampled"])
            challenge_correction_count = challenge["correction_count"]
            if not zero_comp_item_ids.issubset(challenge["first_pass"]):
                add_blocker(blockers, "*", "INCOMPLETE_ZERO_COMP_CHALLENGE", "Every current zero-comp item must appear in the independently challenged first-pass population.")

    return {
        "version": 2, "verification_mode": "current-research",
        "research_policy_version": RESEARCH_POLICY_VERSION,
        "catalog_authorized": not blockers, "listing_authorized": False,
        "client_id": payload.get("client_id", ""), "intake_id": intake_id,
        "status": "PASS" if not blockers else "FAIL",
        "research_sha256": sha256_file(research_path), "ledger_sha256": sha256_file(ledger_path),
        "item_count": len(ledger), "finding_count": len(findings),
        "blocker_count": len(blockers), "challenge_sample_count": challenge_sample_count,
        "challenge_correction_count": challenge_correction_count,
        "findings": findings, "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate item-specific search and completed-sale evidence against a BFG ledger.")
    parser.add_argument("--research", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = gate(args.research, args.ledger, args.intake_id)
        atomic_write_json(args.output, result)
        print(json.dumps({key: result[key] for key in ("status", "item_count", "finding_count", "blocker_count")}, indent=2))
        for entry in result["blockers"][:20]:
            print(f"error: {entry['item_id']} {entry['code']}: {entry['message']}", file=sys.stderr)
        if len(result["blockers"]) > 20:
            print(f"error: {len(result['blockers']) - 20} additional blockers are recorded in {args.output}", file=sys.stderr)
        return 0 if result["status"] == "PASS" else 2
    except (OSError, ValueError, json.JSONDecodeError, ResearchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
