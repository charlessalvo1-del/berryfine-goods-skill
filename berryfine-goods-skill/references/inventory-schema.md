# Inventory schema

Use one row per independently sellable item or intentional lot. Store the canonical client inventory as UTF-8 CSV and use JSON as the batch interchange format.

## Batch JSON

Accept either a JSON array of item objects or:

```json
{
  "client_id": "client-2026-001",
  "client_name": "Example Client",
  "intake_id": "intake-2026-07-26-a",
  "items": []
}
```

Top-level client and intake values fill missing item values. Item-level values take precedence.

## Canonical fields

| Field | Requirement | Meaning |
|---|---|---|
| `client_id` | required | Privacy-safe stable client key |
| `client_name` | optional | Client display name |
| `intake_id` | required | Batch or intake key |
| `item_id` | required | Stable unique key within the client ledger |
| `parent_item_id` | optional | Related lot, set, or source-item key |
| `project_id` | optional | Berryfine client project or catalog key |
| `quantity` | required | Count represented by the row; default `1` |
| `category` | required | Broad inventory category |
| `identified_name` | required | Narrowest defensible item name |
| `maker` | optional | Manufacturer, artist, or brand |
| `model` | optional | Model or pattern |
| `variant` | optional | Edition, size, colorway, material, or issue |
| `identification_confidence` | required | `confirmed`, `probable`, `tentative`, or `unidentified` |
| `identification_basis` | required | Visible facts and reasoning supporting the ID |
| `visible_markings` | optional | Transcribed labels, marks, and codes |
| `missing_evidence` | optional | Photos, tests, or documentation still needed |
| `condition_grade` | required | `new`, `excellent`, `good`, `fair`, `poor`, `parts`, or `unknown` |
| `condition_notes` | required | Specific wear, damage, function, and completeness |
| `testing_status` | optional | `NOT_REQUIRED`, `PLANNED`, `PASSED`, or `FAILED` |
| `value_if_tested_working` | conditional | Supported value if tested and working; required when testing is planned |
| `value_if_untested` | conditional | Supported as-is value; required when testing is planned |
| `testing_notes` | conditional | State the two values, dollar difference, and planned test |
| `photo_refs` | required | Semicolon-separated photo names or stable references |
| `storage_location` | optional | Storage unit, zone, bin, rack, or staging position |
| `dimensions` | optional | Verified item measurements |
| `materials` | optional | Visible or verified materials |
| `comp_count` | required | Number of usable completed-sale comps |
| `comp_summary` | required | Compact synthesis of relevant sold evidence |
| `comp_urls` | optional | Semicolon-separated direct evidence URLs |
| `currency` | required | ISO currency code; default `USD` |
| `market_value_low` | conditional | Supported lower market estimate; required for `SELL`, `DONATE`, or `CONFIRM DONATION` |
| `market_value_mid` | conditional | Supported central market estimate; required for `SELL`, `DONATE`, or `CONFIRM DONATION` |
| `market_value_high` | conditional | Supported upper market estimate; required for `SELL`, `DONATE`, or `CONFIRM DONATION` |
| `decision_basis_value` | conditional | Supported value used for the $40 donation-confirmation band and $50 sell threshold |
| `valuation_basis` | conditional | Evidence class used for valuation |
| `valuation_confidence` | conditional | `low`, `medium`, or `high` |
| `ebay_price` | optional | Recommended initial eBay price |
| `local_price` | optional | Recommended local-market price |
| `quick_sale_price` | optional | Recommended fast-sale price |
| `decision` | required | `SELL`, `DONATE`, `REVIEW`, or `CONFIRM DONATION` |
| `decision_rationale` | required | Threshold, rarity, costs, and uncertainty reasoning |
| `decision_override_reason` | optional | Human-readable justification for a collector-value exception |
| `donation_confirmation_status` | conditional | `NOT_REQUIRED`, `PENDING`, `CONFIRMED`, or `DECLINED` |
| `donation_confirmed_by` | conditional | Human identity resolving `CONFIRM DONATION` |
| `donation_confirmed_at` | conditional | ISO timestamp resolving `CONFIRM DONATION` |
| `donation_confirmation_notes` | optional | Operational context for the confirmation decision |
| `triage_lane` | optional | Operational route distinct from the SELL/DONATE decision |
| `listing_title` | optional | Factual search-oriented title |
| `listing_description` | optional | Accurate condition-forward copy |
| `listing_status` | required | `READY`, `NEEDS_PHOTOS`, `NEEDS_RESEARCH`, `DRAFT`, or `DO_NOT_LIST` |
| `human_review_status` | required | `PENDING`, `APPROVED`, or `REJECTED` |
| `approved_by` | conditional | Human reviewer identity; required for `READY` |
| `approved_at` | conditional | Human approval timestamp; required for `READY` |
| `safety_status` | required | `CLEAR`, `REVIEW_REQUIRED`, or `PROHIBITED` |
| `policy_flags` | optional | Safety, legal, authenticity, recall, or marketplace concerns |
| `research_date` | required | Valuation date in `YYYY-MM-DD` |
| `notes` | optional | Other operational notes |

## Data rules

- Use plain decimal numbers without currency symbols in numeric price fields.
- Use `0` only when zero is the actual value; leave unknown numeric values empty.
- Separate multiple URLs and photo references with semicolons in CSV.
- Keep newlines out of compact fields where practical; the CSV writer will quote them when needed.
- Do not store image binaries or private contact data in the ledger.
- Do not reuse an `item_id` for a different physical item.
- Use the same `item_id` to revise research, condition, or listing status.
- For newly created or reappraised rows with supported values, use `SELL` at $50 or more, `CONFIRM DONATION` from $40 through $49.99, and `DONATE` below $40. Use `REVIEW` only for identification, authenticity, safety, policy, grouping, or valuation uncertainty independent of the supported-value band. Grandfather retained historical decisions until they are explicitly reappraised.
- A new `CONFIRM DONATION` row must use confirmation status `PENDING`, include `Confirm this item will not be sold before donation or rehoming.` in `decision_rationale`, and remain `DRAFT` and human-review `PENDING`.
- Resolve the band to `DONATE` only with status `CONFIRMED`, `donation_confirmed_by`, a valid ISO `donation_confirmed_at`, and `listing_status=DO_NOT_LIST`. Resolve it to `SELL` only with status `DECLINED`, the same human record, and an explicit `decision_override_reason`.
- Keep the $50 sell threshold separate from the $125 auction-candidate routing rule.
- Do not use `REVIEW` solely because `testing_status` is `PLANNED`.
- For planned testing, use `value_if_tested_working` as `decision_basis_value`, describe the untested value and difference in `testing_notes`, and keep `listing_status` `DRAFT`.

## Suggested item IDs

For Berryfine-owned IDs, prefer `BFG-YYYYMMDD-####`. For a client-specific intake, use the approved client/project prefix plus date and sequence. For split items, add a stable suffix such as `-a` or `-part-1`.

## Minimum evidence for READY

Require:

- confidence is `confirmed` or `probable`
- condition is not `unknown`
- at least one cited comparable
- valuation basis is `sold_comparables`, `auction_results`, or `expert_reference`
- valuation confidence is `medium` or `high`
- a recommended price
- title and description
- `safety_status` is `CLEAR`
- a human has set `human_review_status` to `APPROVED` and recorded who and when

AI-created rows must default to `PENDING`; the skill cannot approve its own
work. The listing queue is a review artifact only and never authorizes or
performs publication to an external marketplace.

## Realized outcomes

Do not overwrite the original appraisal with operational results. Append testing, listing, price-change, sold, donated, returned, and identification-correction events to the hash-chained outcome ledger with `scripts/outcome_ledger.py`. Sold events require channel, sold price, and currency; donation events require a destination.
