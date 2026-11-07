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
    "sampled_item_ids": ["BFG-20260802-0001"],
    "findings": [
      {
        "item_id": "BFG-20260802-0001",
        "outcome": "correction_found",
        "opened_urls": ["https://example.com/completed-sale"],
        "summary": "Challenge found a missed completed transaction; it was integrated before gating."
      }
    ],
    "corrections_integrated": true
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
          "result_urls": ["https://example.com/reference"],
          "opened_urls": ["https://example.com/reference"],
          "outcome": "candidate_found",
          "captured_at": "2026-08-02T13:40:00-04:00"
        },
        {
          "attempt_id": "BFG-20260802-0001-s2",
          "query": "Fiesta Copco persimmon metal teapot sold",
          "strategy": "marketplace_sold",
          "surface": "eBay sold and general web search",
          "search_url": "https://www.ebay.com/sch/i.html?_nkw=Fiesta+Copco+persimmon+teapot&LH_Sold=1",
          "result_count": 6,
          "result_urls": ["https://example.com/completed-sale"],
          "opened_urls": ["https://example.com/completed-sale"],
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
          "condition": "Used, complete",
          "comparability": "near",
          "included": true,
          "include_reason": "Same model and similar condition",
          "captured_at": "2026-08-02T14:00:00-04:00"
        }
      ]
    }
  ]
}
```

Use `exact`, `near`, or `broad` for comparability. Keep excluded candidates in the audit with `included=false` and an explicit reason. Never convert an active or unsold listing into completed-sale evidence.

## Search-attempt rules

Each item must have at least two distinct, item-specific search attempts using at least two strategies. At least one query must contain a discriminating word from the photographed item's identification or a visible marking. Allowed strategies are:

- `marking_exact`
- `visual_attributes`
- `image_search`
- `category_synonym`
- `marketplace_sold`
- `regional_language`
- `candidate_confirmation`

Allowed outcomes are `candidate_found`, `comp_found`, `no_useful_result`, `rejected_mismatch`, and `blocked`.

Every attempt must store a reproducible `search_url`, the returned `result_urls`, and the subset actually opened in `opened_urls`. A nonzero result count requires at least one opened result. `candidate_found` and `comp_found` require opened evidence. An item for which all attempts claim zero results is a blocker rather than acceptable research exhaustion; diagnose search access or revise the queries.

For a visually distinctive or unmarked item, use image search as an identification lead. Search results and active listings may establish vocabulary, candidate maker/model, and distinctive construction, but only completed transactions may be included as sold comparables.

An item with no included comparable must remain `REVIEW` and must record at least four distinct query formulations, including both `image_search` and `marketplace_sold`, across at least two search surfaces. It must also include:

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

## Independent challenge review

When a batch contains ten or more zero-comp items, independently challenge at least ten of the most searchable items before authorization. Prefer visible brands, titles, ISBNs, UPCs, model numbers, named makers, and distinctive Japanese or collectible forms. The challenge context must not assume the first pass is correct. Record one finding per sampled item with `confirmed_exhaustion`, `correction_found`, or `not_searchable`, plus every opened URL. Integrate every correction before setting `corrections_integrated=true`. A missing challenge, a sample below ten, or unintegrated corrections blocks the batch.
