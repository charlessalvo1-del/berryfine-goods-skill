# Structured research audit

Use schema version 2. Store one object per inventory item, every search attempt, and every candidate completed-sale comparable. The research gate reconciles included comparables to the canonical ledger, rejects category-comp shortcuts, and blocks `REVIEW` rows that have not exhausted a reasonable item-specific search.

```json
{
  "version": 2,
  "client_id": "client-2026-001",
  "intake_id": "intake-2026-001",
  "challenge_review": {
    "review_run_id": "independent-challenge-001",
    "created_at": "2026-08-02T16:00:00-04:00",
    "reviewer": "independent research context",
    "independent_context": true,
    "first_pass_zero_comp_item_ids": ["BFG-20260802-0001"],
    "sampled_item_ids": ["BFG-20260802-0001"],
    "findings": [
      {
        "item_id": "BFG-20260802-0001",
        "outcome": "correction_found",
        "opened_urls": ["https://example.com/completed-sale"],
        "summary": "Challenge found a missed completed transaction; it was integrated before gating."
      }
    ],
    "corrections_integrated": true,
    "expanded_to_all_first_pass_zero_comp": true
  },
  "items": [
    {
      "item_id": "BFG-20260802-0001",
      "search_attempts": [
        {
          "attempt_id": "BFG-20260802-0001-s1",
          "query": "orange enamel metal teapot ring handle concentric ridges",
          "strategy": "visual_attributes",
          "surface": "Google web search",
          "search_url": "https://www.google.com/search?q=orange+enamel+metal+teapot+ring+handle",
          "result_count": 18,
          "result_count_basis": "observed",
          "result_urls": ["https://example.com/reference"],
          "opened_urls": ["https://example.com/reference"],
          "outcome": "candidate_found",
          "captured_at": "2026-08-02T13:40:00-04:00"
        },
        {
          "attempt_id": "BFG-20260802-0001-s2",
          "query": "orange enamel metal teapot reverse image",
          "strategy": "image_search",
          "surface": "Google Images",
          "search_url": "https://www.google.com/search?tbm=isch&q=orange+enamel+metal+teapot",
          "result_count": 8,
          "result_count_basis": "observed",
          "result_urls": ["https://example.com/image-reference"],
          "opened_urls": ["https://example.com/image-reference"],
          "outcome": "candidate_found",
          "captured_at": "2026-08-02T13:43:00-04:00"
        },
        {
          "attempt_id": "BFG-20260802-0001-s3",
          "query": "Fiesta Copco persimmon teapot construction",
          "strategy": "candidate_confirmation",
          "surface": "Google web search",
          "search_url": "https://www.google.com/search?q=Fiesta+Copco+persimmon+construction",
          "result_count": 4,
          "result_count_basis": "observed",
          "result_urls": ["https://example.com/confirmation-reference"],
          "opened_urls": ["https://example.com/confirmation-reference"],
          "outcome": "candidate_found",
          "captured_at": "2026-08-02T13:44:00-04:00"
        },
        {
          "attempt_id": "BFG-20260802-0001-s4",
          "query": "Fiesta Copco persimmon metal teapot sold completed",
          "strategy": "marketplace_sold",
          "surface": "Google completed-sale and auction search",
          "search_url": "https://www.google.com/search?q=Fiesta+Copco+persimmon+teapot+sold",
          "result_count": 3,
          "result_count_basis": "observed",
          "result_urls": ["https://example.com/completed-sale", "https://example.com/completed-sale-2", "https://example.com/completed-sale-3"],
          "opened_urls": ["https://example.com/completed-sale", "https://example.com/completed-sale-2", "https://example.com/completed-sale-3"],
          "outcome": "comp_found",
          "captured_at": "2026-08-02T13:45:00-04:00"
        }
      ],
      "identification_candidates": [
        {
          "name": "Fiesta/Homer Laughlin persimmon enamel-on-metal teapot by Copco",
          "source_url": "https://example.com/reference",
          "match_basis": "Ring handle, concentric ridges, metal rim, lid hardware, and color match",
          "status": "accepted"
        }
      ],
      "comparables": [
        {
          "comp_id": "BFG-20260802-0001-c1",
          "marketplace": "eBay",
          "source_url": "https://example.com/completed-sale",
          "title": "Fiesta persimmon enamel-on-metal teapot by Copco",
          "transaction_status": "sold",
          "sale_date": "2026-07-15",
          "sold_price": 75,
          "shipping": 12,
          "currency": "USD",
          "normalized_total_usd": 87,
          "normalization_note": "USD sale; sold price plus displayed shipping.",
          "condition": "Used, complete",
          "comparability": "near",
          "included": true,
          "include_reason": "Same model and similar condition",
          "evidence_method": "direct_transaction_page",
          "evidence_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "price_verified": true,
          "sale_date_verified": true,
          "quantity": 1,
          "lot_allocation_note": "Single-item transaction; no allocation required.",
          "captured_at": "2026-08-02T14:00:00-04:00"
        },
        {
          "comp_id": "BFG-20260802-0001-c2",
          "marketplace": "Example Auction House",
          "source_url": "https://example.com/completed-sale-2",
          "title": "Fiesta Copco persimmon teapot",
          "transaction_status": "auction_result",
          "sale_date": "2026-06-20",
          "sold_price": 75,
          "shipping": 0,
          "currency": "USD",
          "normalized_total_usd": 75,
          "normalization_note": "USD sale; no displayed shipping.",
          "condition": "Used, light wear",
          "comparability": "near",
          "included": true,
          "include_reason": "Same model and comparable wear",
          "evidence_method": "direct_transaction_page",
          "evidence_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "price_verified": true,
          "sale_date_verified": true,
          "quantity": 1,
          "lot_allocation_note": "Single-item transaction; no allocation required.",
          "captured_at": "2026-08-02T14:02:00-04:00"
        },
        {
          "comp_id": "BFG-20260802-0001-c3",
          "marketplace": "Example Marketplace",
          "source_url": "https://example.com/completed-sale-3",
          "title": "Fiesta Copco enamel-on-metal teapot",
          "transaction_status": "sold",
          "sale_date": "2026-05-11",
          "sold_price": 82,
          "shipping": 0,
          "currency": "USD",
          "normalized_total_usd": 82,
          "normalization_note": "USD sale; no displayed shipping.",
          "condition": "Used, complete",
          "comparability": "exact",
          "included": true,
          "include_reason": "Exact model with similar completeness",
          "evidence_method": "direct_transaction_page",
          "evidence_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "price_verified": true,
          "sale_date_verified": true,
          "quantity": 1,
          "lot_allocation_note": "Single-item transaction; no allocation required.",
          "captured_at": "2026-08-02T14:04:00-04:00"
        }
      ],
      "price_synthesis": {
        "method": "median",
        "comp_ids": ["BFG-20260802-0001-c1", "BFG-20260802-0001-c2", "BFG-20260802-0001-c3"],
        "raw_median": 82,
        "adjusted_mid": 70,
        "adjustment_reason": "Subject has more visible wear than the median-condition comparable."
      },
      "search_completion": {
        "status": "evidence_sufficient",
        "stop_reason": "Five exact or near completed transactions support the full disposition range."
      }
    }
  ]
}
```

Use `exact`, `near`, or `broad` for comparability. Keep excluded candidates in the audit with `included=false` and an explicit reason. Never convert an active or unsold listing into completed-sale evidence.

## Search-attempt rules

Each item must have at least four distinct, item-specific search attempts using at least three strategies. The set must include Google web or image discovery, `image_search`, and `marketplace_sold`. Open at least four unique direct result pages. At least one query must contain a discriminating word from the photographed item's identification or a visible marking. Allowed strategies are:

- `marking_exact`
- `visual_attributes`
- `image_search`
- `category_synonym`
- `marketplace_sold`
- `regional_language`
- `candidate_confirmation`

Allowed outcomes are `candidate_found`, `comp_found`, `no_useful_result`, `rejected_mismatch`, and `blocked`.

Every attempt must store a reproducible `search_url`, the returned `result_urls`, and the subset actually opened in `opened_urls`. Set `result_count_basis=observed` only when the surface displayed or returned the count. When it did not, use `result_count_basis=not_displayed` and `result_count=null`; never manufacture a count. A nonzero observed result count requires at least one opened result. `candidate_found` and `comp_found` require opened evidence. An item for which all observed attempts claim zero results is a blocker rather than acceptable research exhaustion; diagnose search access or revise the queries.

Every item also requires `search_completion` with status `evidence_sufficient`, `saturated`, or `blocked` and an item-specific `stop_reason`. Four queries are the minimum coverage requirement, not an automatic stop condition.

For a visually distinctive or unmarked item, use image search as an identification lead. Search results and active listings may establish vocabulary, candidate maker/model, and distinctive construction, but only completed transactions may be included as sold comparables.

An item with fewer than three included comparables must remain `REVIEW` and must record at least four distinct query formulations, including both `image_search` and `marketplace_sold`, across at least two search surfaces. It must open at least four unique direct result pages, including one reached through image search and one direct completed-sale or auction candidate. Search results, category indexes, pricing pages, and storefront pages are not direct evidence. It must also include:

```json
"exhaustion": {
  "reason_code": "no_completed_sales",
  "summary": "Identification candidate found, but no completed transaction could be verified.",
  "next_evidence": "Photograph the underside maker mark and measure capacity.",
  "closest_candidate_urls": ["https://example.com/active-identification-lead"],
  "candidate_identifications_considered": ["Candidate A", "Candidate B"]
}
```

Allowed `reason_code` values are `no_candidates`, `no_completed_sales`, `conflicting_identity`, `inaccessible_sold_data`, and `insufficient_photo_detail`.

Do not reuse one sold URL as support for more than three different inventory items. At least one included comparable for a non-`REVIEW` disposition must be `exact` or `near`; broad category comps alone cannot authorize sale or disposal.

For a non-`REVIEW` disposition, include at least three unique completed-sale URLs and require at least three exact or near matches. Require five unique completed transactions when the supported value range touches $30 through $65. Every included comparable must be represented in direct opened evidence and include `evidence_method`, `evidence_sha256`, verified price/date flags, quantity, lot-allocation treatment, and normalization provenance. Foreign currency also requires `exchange_rate`, `exchange_rate_date`, and `exchange_rate_source`. Synthesize price with a `price_synthesis` object using the median of the included USD-normalized totals. The recorded median must be reproducible, and the adjusted midpoint must match the ledger midpoint and decision-basis value.

## Independent challenge review

When a batch contains ten or more zero-comp items, store every first-pass zero-comp item ID and independently challenge the complete population before authorization. Prefer visible brands, titles, ISBNs, UPCs, model numbers, named makers, and distinctive Japanese or collectible forms first, then review the remainder. The challenge context must not assume the first pass is correct. Record one finding per item with `confirmed_exhaustion`, `correction_found`, or `not_searchable`, plus every direct opened URL. Integrate every correction, set `expanded_to_all_first_pass_zero_comp=true`, and make `sampled_item_ids` exactly match `first_pass_zero_comp_item_ids`. A partial challenge or unintegrated correction blocks the batch.
