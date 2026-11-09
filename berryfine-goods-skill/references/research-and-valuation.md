# Research and valuation

## Evidence order

Prefer:

1. Direct exact or near Etsy active listings
2. Direct exact or near eBay sold/Product Research records
3. Direct exact or near eBay active listings
4. General web, image, specialist, and auction references for identification only

Etsy is the preferred pricing surface and eBay is the cross-check. Active and sold prices may be combined when every included page is direct, current, exact or near, normalized to a one-item USD total, and deduplicated. Label active listings as asking prices and sold listings as realized transactions. Auction prices are never valuation inputs; use auction evidence only to identify the object or detect collector significance.

Record the evidence class in `valuation_basis`. Under v2.9, pricing confidence and decision confidence are separate: a wide range may produce an imprecise provisional price while its conservative floor still supports SELL.

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

Use eBay Product Research as the preferred sold source when available because it exposes actual accepted Best Offer prices, date ranges through three years, seller counts, trends, price ranges, and recent sell-through. Treat one Product Research query and its captured rows/metrics as one search attempt. Etsy and eBay active listings are current asking-market evidence, not realized sales. Do not scrape restricted sold-data interfaces; use a human-authenticated research session and capture visible evidence.

At attempt six, stop when HIGH pricing confidence or HIGH decision confidence resolves the outcome. Otherwise continue to eight. At eight, stop when the conservative floor or ceiling resolves the threshold, or use `$40-$50 STAFF DECISION` when the item is low value and further research is unlikely to improve the staff decision. Continue to ten only for plausible high-value, rare, collector-significant, regulated, or materially misidentified items. Never search merely to improve numeric precision after disposition is already decisive. Record `search_completion.stop_tier`, `stop_reason`, and the boundary flag.

Track search cost separately from evidence processing. Exactly 6, 8, or 10 submitted queries count as search attempts. Opening, validating, time-weighting, deduplicating, or calculating from a captured result does not create another search. Report total and average attempts, maximum attempts, ten-search count/share, average pages opened, and valid comps per search. On the 115-item Rothschild regression set, fail the comparison if attempts exceed 972 total, 8.45 average, or 26 ten-search items.

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

## Adaptive-age price and decision synthesis

Remove false matches first. Explain meaningful outliers instead of mechanically averaging them.

Before calculation, reject unavailable pages, false semantic matches, duplicate or cross-listed inventory, wrong quantities, and unverified transaction states. Each included comp records availability, seller key, matched attributes, mismatched attributes, and a direct evidence hash. `exact` permits no material mismatch.

Assign source weights after cleaning: eBay sold/completed `1.00`, eBay active `0.70`, Etsy sold/completed `0.80`, and Etsy active `0.60`; multiply near matches by `0.85`. Apply time weights to sold evidence: `1.00` through 12 months, `0.85` for 13-24 months, and `0.70` for 25-36 months. Evidence-based scarce/vintage items use `0.90` and `0.80` in the latter bands. A sale older than 36 months receives `0.50` only for a scarce/rare/unique item with current active corroboration; otherwise it is identification-only. Auction, broad, category, search, and snippet evidence receives zero pricing weight.

Use the weighted median as the anchor. Clamp Etsy at `anchor * 0.95` and eBay at `anchor * 1.05` to the defensible included-price interval. Record the raw interval, anchor, recommendations, evidence counts, and price type.

- `market` / HIGH: four stable prices including at least two eBay sold/completed records, or three stable cross-market prices with an exact match and a dated sale within 12 months
- `market` / MEDIUM: at least three direct prices with CV at most 0.25 and ratio at most 1.75, or two exact prices within 35%
- `provisional` / LOW: one direct price or a weaker/dispersed set; issue the price but do not automatically sell or donate outside the staff band
- `operational` / LOW: zero prices, confirmed/probable common low-value identity, and an eight-search boundary stop; record $40/$45/$49.99 and state that $45 is operational rather than market value
- `unpriced` / LOW: no defensible price and no safe operational fallback

Calculate a conservative decision floor independently from the recommended list price. One active exact comp uses 70% of price; one near comp uses 60%. Two active comps use 85% of the lower price when both are exact and 80% otherwise. Three or more active comps use 90% of the lower quartile. Sold evidence uses 80%/70% for one comp, 90% of the lower for two, and 95% of the lower quartile for three or more. Automatic SELL normally requires the floor to reach $55, medium/high decision confidence, confirmed/probable identity, and safety clearance—even when numeric pricing confidence remains LOW. The controlled $50 exception applies only to confirmed/probable, safety-clear items and passes when at least two direct prices produce a floor of at least $49.50; when at least two stable direct prices have a low value of at least $50, CV at most 0.25, and ratio at most 1.75; or when exactly two active direct prices bracket $50, have a half-up rounded midpoint at least $47.50, and ratio at most 1.35. The last route uses a $50 controlled test listing. Zero-comp operational prices never qualify. Automatic DONATE still requires a stable market interval wholly below $40. CONFIRM DONATION covers an eligible $40-$49.99 recommendation or the operational $45 handling price.

The v2.7 cleaned-average formula is retained only for validating sealed v2.7 records. New work uses `scripts/price_first_gate.py` and `research_policy_version=2.9.1-pilot`.

Adjust for positively evidenced condition differences, completeness, testing, authenticity confidence, seasonality, shipping difficulty, and lot size. Do not discount for hypothetical damage or missing condition detail. State material adjustments.

Record a reproducible `price_synthesis` object containing method, price type, raw low/mid/high interval, weighted-median anchor, Etsy and eBay recommendations, conservative decision floor, pricing confidence, decision confidence, age bands, and included/excluded comp IDs. If a non-USD listing is included, normalize it to USD with a dated exchange-rate note before synthesis.

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

Keep the raw comparable interval visible, but use the v2.9 price type, pricing confidence, decision confidence, identity, safety status, and conservative floor for disposition. Donation remains conservative: only a medium/high-confidence market interval wholly below $40 may auto-donate.

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
