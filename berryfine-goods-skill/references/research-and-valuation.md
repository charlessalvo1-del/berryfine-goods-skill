# Research and valuation

## Evidence order

Prefer:

1. Direct exact or near Etsy active listings
2. Direct exact or near eBay sold/Product Research records
3. Direct exact or near eBay active listings
4. General web, image, specialist, and auction references for identification only

Etsy is the preferred pricing surface and eBay is the cross-check. Active and sold prices may be combined when every included page is direct, current, exact or near, normalized to a one-item USD total, and deduplicated. Label active listings as asking prices and sold listings as realized transactions. Auction prices are never valuation inputs; use auction evidence only to identify the object or detect collector significance.

Record the evidence class in `valuation_basis`. Only a qualifying direct Etsy/eBay price set may support a non-`REVIEW` decision under the v2.7 pilot.

Use current web research for every valuation request. Do not reuse old prices without refreshing them.

## Search construction

Start with confirmed maker, model, pattern, model number, material, size, edition, and key accessories. Remove uncertain attributes rather than baking them into a search.

For an unidentified object, search visible markings and distinctive construction first. Use image similarity as a lead, not proof.

Treat identification and valuation as two linked but separate searches. First determine the best item vocabulary and candidate identity; then search completed sales for that candidate. Do not skip identification because a generic category comp is available.

Build a visual search fingerprint from all photographs before searching: object type, likely material, construction, silhouette, color, handle/hinge/lid/spout/hardware geometry, decoration, markings, and apparent era. If the first results disagree with the initial category or material, correct the identification and search again. For example, visible screws, a rolled metal rim, and a black metal interior outweigh a superficial "ceramic teapot" impression.

Use this adaptive query ladder. Every item records exactly 6, 8, or 10 distinct attempts across at least three strategies:

1. exact visible maker/model/marking in quotes
2. distinctive visual fingerprint without an assumed maker
3. image search using the clearest full-object image and, when useful, a crop of the mark or distinctive hardware
4. candidate maker/model plus a feature that can falsify the match
5. candidate identity on Etsy, then eBay active and sold/Product Research surfaces
6. synonyms, regional terms, translated markings, and alternate spellings when the first language or category vocabulary fails

Google or the approved integrated web/image search is appropriate for identification leads. Record the actual query, reproducible search URL, search surface, URLs actually opened, outcome, and time. Label the surface honestly. Query text without opened evidence does not prove that a candidate page was verified.

Do not use a fixed category-comparable library as a substitute for item-level research. One direct comparable URL may support at most three genuinely similar items, and each item still needs its own search log and comparability analysis.

## Comp capture

For each candidate pricing comp, capture:

- direct URL
- marketplace or auction house
- listing status and capture date; sale date when applicable
- item title
- displayed active or realized price
- shipping when shown
- currency
- condition and completeness
- match differences
- include/exclude decision
- evidence method and SHA-256 of the screenshot, HAR, WACZ, or equivalent capture
- explicit confirmation that the direct page and displayed price were visible in the captured evidence
- lot quantity and any per-unit allocation
- original currency plus dated exchange-rate source when conversion is required

Write these fields as one structured comparable object using [research-audit-schema.md](research-audit-schema.md). Run `research_gate.py` before catalog generation. A narrative list of URLs does not substitute for structured evidence or exact ledger reconciliation.

Do not claim a price is completed merely because a search result says "sold" without opening enough evidence to verify the transaction state. Do not call an active asking price a sale.

Use eBay Product Research as the preferred eBay sold source when available because it exposes accepted Best Offer prices and a longer history than ordinary sold search. Etsy active prices are the preferred current-market anchor; eBay active and sold prices cross-check it. Do not scrape restricted sold-data interfaces; use a human-authenticated research session and capture visible evidence.

At attempt six, stop only with four stable included prices and a range at least $5 away from both decision boundaries. Otherwise continue to eight. At eight, three consistent prices may authorize medium-confidence disposition when coefficient of variation is at most 0.25, highest-to-lowest ratio is at most 1.75, and the range has a $5 boundary buffer. Otherwise use `$40-$50 STAFF DECISION` when the item is low value, the high bound is below $125, and further research is unlikely to improve the staff decision. Continue to ten only for plausible high-value, rare, collector-significant, regulated, or materially misidentified items. Record `search_completion.stop_tier`, `stop_reason`, and the boundary flag where applicable.

## Standard saleable condition assumption

Unless positive photographic or owner-supplied evidence shows otherwise, value the subject as complete, functional, suitable for sale, and in typical good used condition. Missing close-ups or physical inspection do not justify damaged, parts-only, poor, fair, incomplete, or unsuitable-for-sale assumptions and do not independently cause `REVIEW`.

Record the default as `condition_basis=assumed_standard_saleable`, `condition_grade=good`, and `Assumed complete, functional, saleable, and in typical good used condition; not physically inspected.` Use normal saleable-condition comps and exclude damaged, repair, incomplete, parts-only, or unusually poor-condition transactions. Visible defects may override the default; identify the evidence and the adjustment. Safety, legality, authenticity, recall, and marketplace-policy uncertainty remain separate review grounds.

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

Require three unique, directly opened exact or near Etsy/eBay prices before any non-`REVIEW` disposition and target four. When enough comps exist:

- `A` is the arithmetic mean of cleaned normalized prices
- `H80` is 80% of the highest cleaned price
- `B` is `(A + H80) / 2`, clamped to the cleaned price range
- Etsy recommendation is `B * 0.95`
- eBay recommendation is `B * 1.05`
- use the defensible cleaned cluster for `market_value_low` and `market_value_high`
- set local and quick-sale prices separately for pickup convenience and speed

Adjust for positively evidenced condition differences, completeness, testing, authenticity confidence, seasonality, shipping difficulty, and lot size. Do not discount for hypothetical damage or missing condition detail. State material adjustments.

Record a reproducible `price_synthesis` object containing the cleaned average, highest cleaned price, `H80`, clamped anchor, Etsy price, and eBay price. A four-price set is stable only when coefficient of variation is at most 0.25 and highest-to-lowest ratio is at most 1.75. If a non-USD listing is included, normalize it to USD with a dated exchange-rate note before synthesis.

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

`REVIEW` is an outcome after research, not a shortcut around research. Before assigning it for missing identity or comps, complete the applicable 8- or 10-attempt ladder, including image discovery, Etsy, and eBay. Search pages, category indexes, pricing pages, storefront pages, and auction prices do not count as included pricing evidence. Record the closest candidates, why each failed, and the exact next evidence needed. A generic sentence such as "item-specific comparables needed" is not research exhaustion, and the same exhaustion text may not be copied across unrelated items.

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
