# Research and valuation

## Evidence order

Prefer:

1. Direct completed or sold marketplace records for the same item
2. Auction-house realized results with buyer's premium treatment understood
3. Specialist dealer sold archives or reputable collector databases
4. Broad category comps adjusted for known differences
5. Active asking prices only as a labeled last-resort context signal

Record the evidence class in `valuation_basis`. Only `sold_comparables`,
`auction_results`, or a documented `expert_reference` can support `READY`.
Active listings and price guides may inform a provisional range, but must remain
`NEEDS_RESEARCH` or `REVIEW`.

Use current web research for every valuation request. Do not reuse old prices without refreshing them.

## Search construction

Start with confirmed maker, model, pattern, model number, material, size, edition, and key accessories. Remove uncertain attributes rather than baking them into a search.

For an unidentified object, search visible markings and distinctive construction first. Use image similarity as a lead, not proof.

Treat identification and valuation as two linked but separate searches. First determine the best item vocabulary and candidate identity; then search completed sales for that candidate. Do not skip identification because a generic category comp is available.

Build a visual search fingerprint from all photographs before searching: object type, likely material, construction, silhouette, color, handle/hinge/lid/spout/hardware geometry, decoration, markings, and apparent era. If the first results disagree with the initial category or material, correct the identification and search again. For example, visible screws, a rolled metal rim, and a black metal interior outweigh a superficial "ceramic teapot" impression.

Use this query ladder. Every item must record at least four distinct queries across at least three strategies and open at least four unique direct pages:

1. exact visible maker/model/marking in quotes
2. distinctive visual fingerprint without an assumed maker
3. image search using the clearest full-object image and, when useful, a crop of the mark or distinctive hardware
4. candidate maker/model plus a feature that can falsify the match
5. candidate identity plus `sold`, `completed`, or an auction-results surface
6. synonyms, regional terms, translated markings, and alternate spellings when the first language or category vocabulary fails

Google or another general web/image search is appropriate for identification leads. Marketplace sold filters and auction archives are required for valuation evidence. Record the actual query, reproducible search URL, search surface, returned URLs, URLs actually opened, result count, outcome, and time in the research audit. Query text without opened evidence does not prove that a search occurred.

Do not use a fixed category-comparable library as a substitute for item-level research. One completed-sale URL may support at most three genuinely similar items, and each item still needs its own search log and comparability analysis.

## Comp capture

For each candidate comp, capture:

- direct URL
- marketplace or auction house
- sale or close date
- item title
- sold or realized price
- shipping when shown
- currency
- condition and completeness
- match differences
- include/exclude decision

Write these fields as one structured comparable object using [research-audit-schema.md](research-audit-schema.md). Run `research_gate.py` before catalog generation. A narrative list of URLs does not substitute for structured evidence or exact ledger reconciliation.

Do not claim a price is completed merely because a search result says "sold" without opening enough evidence to verify the transaction state.

## Comparability

Prioritize, in order:

1. exact model or pattern
2. same variant, size, material, and production era
3. similar condition and tested status
4. same included accessories, packaging, and quantity
5. recent date and relevant buyer geography

Use older sales for rare items when necessary and say why.

## Price synthesis

Remove false matches first. Explain meaningful outliers instead of mechanically averaging them.

Require three unique, directly opened completed transactions before any non-`REVIEW` disposition. Require five when the supported range touches $30 through $65. When enough comps exist:

- use the lower comparable cluster for `market_value_low`
- use the median normalized total of the best matches for `market_value_mid`; do not use a simple mean with only three comps
- use the upper defensible cluster for `market_value_high`
- set `ebay_price` near the upper-middle of the supported range when normal negotiation is expected
- set `local_price` for local demand, pickup convenience, and avoided shipping/fees
- set `quick_sale_price` below the central estimate, normally near the low end

Adjust for condition, completeness, testing, authenticity confidence, seasonality, shipping difficulty, and lot size. State material adjustments.

Record a `price_synthesis` object containing `method=median`, every included comp ID, the raw median, the adjusted midpoint, and the adjustment reason. The adjusted midpoint must match both the ledger midpoint and decision-basis value. If a non-USD sale is included, normalize it to USD with a dated exchange-rate note before synthesis.

Do not apply a universal percentage formula when the evidence suggests marketplace-specific demand.

## Insufficient evidence

Use `REVIEW` when identification or value uncertainty could change the decision across the $40 donation-confirmation band or $50 sell threshold, or when collector significance is plausible. When the value is sufficiently supported and `decision_basis_value` is $40 through $49.99, use `CONFIRM DONATION`, not `REVIEW`. Do not mark the initial record `DONATE` or `SELL`; state `Confirm this item will not be sold before donation or rehoming.` in the decision rationale, client-facing history, and Exceptions row. Keep it pending until BFG records whether donation was confirmed or declined.

Document:

- searches attempted
- closest evidence found
- why it is not directly comparable
- the next photo, measurement, test, or expert needed

If a provisional range is still useful, label it as low confidence.
Set `valuation_basis` to `insufficient_evidence` when no defensible source
class applies.

`REVIEW` is an outcome after research, not a shortcut around research. Before assigning it for missing identity or comps, complete at least four distinct query formulations across at least two surfaces, including image search and a completed-sale search. Open at least four unique direct result pages, including a result reached through image search and a direct completed-sale or auction candidate. Search pages, category indexes, pricing pages, and storefront pages do not count. Record the closest candidates, why each failed, and the exact next evidence needed. A generic sentence such as "item-specific comparables needed" is not research exhaustion, and the same exhaustion text may not be copied across unrelated items.

Apply disposition thresholds to uncertainty ranges. `DONATE` requires a high bound below $40; `CONFIRM DONATION` requires the entire range to remain within $40-$49.99; `SELL` requires a low bound of at least $50. A range crossing either threshold remains `REVIEW` even when its midpoint falls cleanly into one band.

Do not claim a 90%-97.8% identification or pricing accuracy rate from process compliance alone. Validate identification against independently confirmed labels or experts, validate pricing against realized outcomes, and report price-range coverage plus median absolute percentage error on a held-out sample.

For a batch with ten or more zero-comp items, record the entire first-pass zero-comp population and independently challenge every item before accepting the conclusions. Prioritize visible identifiers, named titles, brands, models, and distinctive forms, then continue through the remaining population. Integrate every missed identity or valid completed sale. Preserve the full challenge population, report, direct opened evidence, correction count, and explicit expansion status in the structured audit.

## Items planned for testing

Do not use `REVIEW` solely because BFG plans to test an item. Research both:

- the value if tested and working as expected
- the value sold untested or as-is

Use the supported tested-working value for the primary response and `decision_basis_value`. Record the untested/as-is value and dollar difference in `testing_notes`, and keep the listing in `DRAFT` while `testing_status` is `PLANNED`.

If the item fails testing, refresh the valuation for the observed condition before sale or donation. Identification, authenticity, safety, or valuation uncertainty may still require `REVIEW` independently of testing.

## Marketplace and safety guardrails

Do not recommend routine listing for:

- recalled or unsafe products
- suspected counterfeit goods
- weapons, regulated goods, hazardous materials, or prohibited wildlife products
- items with unresolved title, ownership, or authenticity concerns
- personal data-bearing electronics that have not been wiped

Flag the issue and request manual policy or specialist review. Do not provide legal or authentication guarantees.

Use `safety_status` `REVIEW_REQUIRED` while any concern is unresolved and
`PROHIBITED` for a known prohibited item. Neither status may enter the listing
queue.
