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

When enough comps exist:

- use the lower comparable cluster for `market_value_low`
- use the central tendency of the best matches for `market_value_mid`
- use the upper defensible cluster for `market_value_high`
- set `ebay_price` near the upper-middle of the supported range when normal negotiation is expected
- set `local_price` for local demand, pickup convenience, and avoided shipping/fees
- set `quick_sale_price` below the central estimate, normally near the low end

Adjust for condition, completeness, testing, authenticity confidence, seasonality, shipping difficulty, and lot size. State material adjustments.

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
