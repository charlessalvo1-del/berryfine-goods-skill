---
name: berryfine-goods-skill
description: Process single items or large client photo folders into fail-closed consignment inventory; validate real image content, reconcile blind grouping reviews, identify photographed goods, audit structured Etsy and eBay marketplace evidence, estimate resale prices, recommend SELL, DONATE, REVIEW, or CONFIRM DONATION, generate paired client workbooks, preserve template colors and locations, hash-seal intake evidence, and track testing and realized outcomes. Use for pre-BFG intake, day-long bulk photo sessions, hundreds of item photos, resumable estate or consignment processing, catalog creation, inventory updates, valuation refreshes, delivery audits, and listing preparation.
---

# Berryfine Goods Skill

Turn photographed goods into an evidence-backed, client-specific inventory. Keep identification certainty, market evidence, pricing judgment, and listing readiness separate.

## Load the right references

- Read [references/inventory-schema.md](references/inventory-schema.md) before creating, merging, or exporting an inventory.
- Read [references/research-and-valuation.md](references/research-and-valuation.md) before researching comps or assigning prices.
- Read [references/research-audit-schema.md](references/research-audit-schema.md) before writing direct marketplace evidence.
- Read [references/bulk-photo-intake.md](references/bulk-photo-intake.md) before processing a folder or producing a template-matched client catalog.
- Run `scripts/inventory_ledger.py --help` when managing a persistent client ledger or listing queue.
- Run `scripts/photo_manifest.py --help` before scanning a large photo folder.
- Run `scripts/preflight_lock.py --help` before every new intake or retest.
- Run `scripts/sequence_review_gate.py --help` before grouping a flat, unnumbered camera roll.
- Run `scripts/research_gate.py --help` only when validating a retained legacy v2.6 research audit.
- Run `scripts/price_first_gate.py --help` for v2.9 adaptive-age research. Use `adaptive_market_gate.py` only for sealed v2.7 records.
- Use `scripts/pricing_policy.py` as the shared price/disposition calculation and `scripts/pricing_replay.py` only for hash-bound, non-destructive policy comparisons against sealed evidence.
- Run `scripts/delivery_gate.py --help` before reporting a batch complete.
- Run `scripts/catalog_gate.py --help` after spreadsheet authoring and before the delivery gate.
- Run `scripts/bfg.py doctor` after installation and `scripts/bfg.py audit` before reporting any intake complete.

## Establish the job

Confirm or infer:

- `client_id` and client display name
- intake or batch ID
- main client folder or existing client ledger
- whether the request covers identification only, valuation, inventory update, or listing preparation
- currency and target market; default to USD and the item's apparent region
- valuation date
- source photo folder; use its outermost/main folder name as the client display name and workbook name unless the user explicitly overrides it
- supplied `.xlsx` catalog template and main-client-folder deliverable paths
- centralized audit-record root; default to `C:\BFG Bulk Import Records`
- client records folder `<records-root>\<Client Folder Name>` and iteration records folder `<records-root>\<Client Folder Name>\<intake-id>`

If a name is unavailable, use a privacy-safe ID such as `client-2026-001`. Never put sensitive client contact details in the inventory unless explicitly requested.

## Require a clean-run preflight and confirmation

Before starting every new intake or retest, perform a read-only preflight and pause for explicit user confirmation. Do not create a manifest, organize photos, research items, or write deliverables before confirmation.

Report:

- the exact active photo-folder path, image count, extension counts, and whether it is flat or nested
- the exact catalog-template path, SHA-256 hash, worksheet names, used dimensions, and detected header row
- every sibling archive, prior-test, categorized-output, manifest, catalog, and exception artifact that will be excluded
- the count of exact duplicate hash groups, the canonical file retained for each group, and every redundant path that will be automatically excluded without deleting source files
- the proposed client name, intake ID, intake method, deliverable names, dated categorized-folder name, and centralized iteration records folder
- the complete catalog rules for this run: preserve every pre-populated row and its existing `LOCATION`; write `Storage` only for newly appended rows; keep detailed responses in H; preserve I; add `RECOMMENDED ACTION` in J and `RESEARCH REVIEW` in K; apply the current-row fill rules; and use the v2.9.1 adaptive-age policy with the primary conservative $55 SELL decision floor, the controlled $50 exception, conservative DONATE evidence, $40-$49.99 or operational-$45 CONFIRM DONATION, and priced REVIEW rows when decision confidence is insufficient

For a fresh test, create a new intake ID and manifest. Never resume, copy, seed, or treat a prior test manifest, categorized folder, catalog, exception workbook, item assignment, identification, or valuation as the current result. Prior-run information may be consulted only after the independent review is complete, unless the user explicitly authorizes a baseline-assisted run. Pass every prior-run directory to `photo_manifest.py` with a separate exact `--ignore-dir` argument.

Create `preflight-lock.json` with `scripts/preflight_lock.py create`, then report the preflight and explicitly ask the user to confirm both the selected inputs/exclusions and the stated catalog rules. A generic request that omits the catalog rules is insufficient. After the user confirms, run `scripts/preflight_lock.py confirm` with the human identity and exact required confirmation text. Treat this confirmation as a hard gate. Never invent `confirmed_by`, and never edit a confirmed lock. If a photo, template, exclusion rule, deliverable path, or catalog rule changes, create and confirm a new lock.

## Refresh a completed legacy catalog without rerunning research

Use the explicit `legacy-catalog-refresh` workflow only when the user says the prior identification, valuation, and research are complete and requests a catalog-only policy or formatting correction. Do not run the current-intake research gate retroactively against completed legacy rows merely because the older audit used a previous evidence schema. Do not silently relabel those rows `REVIEW`.

Require a new intake ID, a new centralized records folder, the untouched original catalog template, the canonical ledger, the completed source intake ID, the completed source grouping, and the source intake's categorized photo set. Do not rerun photo grouping or AI review. Run `categorized_inventory_gate.py` once to verify the existing categorized set, including legacy manifests that predate per-photo hashes. This immutable verification is the only legacy-refresh audit artifact permitted before the preflight because it reads and seals existing evidence without changing it. Put or promote the set directly under the main client folder as `Categorized Inventory <YYYY-MM-DD>`. Create the preflight with `--workflow legacy-catalog-refresh`, `--source-ledger`, `--source-intake-id`, `--categorized-verification`, and `--categorized-output`. Bind the source-ledger hash and categorized verification before changing the ledger or client workbooks.

After confirmation, use `scripts/legacy_catalog_refresh.py prepare`. It must preserve every identification, condition, price, research date, comp field, photo reference, and stable item ID; create a new target-intake revision; keep all rows `DRAFT` and human-review `PENDING`; and apply only deterministic current-policy migrations. The permitted automatic migration is a completed legacy `DONATE` row with `decision_basis_value` from $40 through $49.99 to `CONFIRM DONATION`, including the required confirmation instruction. Preserve existing `SELL`, supported below-$40 `DONATE`, and independently uncertain `REVIEW` decisions. Any other decision change is a blocker.

Upsert the prepared batch with the normal hash-chained item revision log, then run `scripts/legacy_catalog_refresh.py verify`. Use its PASS verification with `catalog_payload.py --preflight-lock`. A legacy-refresh verification may authorize catalog generation only; it must state `listing_authorized=false` and can never replace current research for a listing queue, `READY` status, or marketplace publication.

Build the paired workbooks from the untouched original template, not from the prior generated catalog. Run `catalog_gate.py`, then run `delivery_gate.py --workflow legacy-catalog-refresh --intake-id <new-intake-id> --manifest <source-manifest> --categorized <main-client-categorized-folder> --categorized-verification <verification>`. The gate must validate the confirmed preflight, template, current ledger revision, exact paired workbook paths and hashes, the catalog verification, and the bound categorized-photo delivery without claiming that photos were reprocessed. Never report completion when the categorized set exists only inside a test/archive subfolder.

## Group photos into items

Treat photo grouping as a required intake step.

1. Preserve the user's stated item groupings.
2. Assign one `item_id` per independently sellable unit or intentional lot.
3. Do not merge adjacent objects merely because they appear in one photo.
4. Do not split a set that buyers normally expect together without noting the missing pieces.
5. Record every source photo name or stable reference in `photo_refs`.
6. Flag ambiguous groupings as `REVIEW` and explain what must be separated or photographed again.

For batches, create an intake manifest before deep research. Process every item row, including unidentified and low-value items, so nothing silently disappears.

## Process a large photo folder

Do not require hundreds of chat uploads. Ask the user to place the photo session in one accessible client folder and provide its filesystem path. Follow [references/bulk-photo-intake.md](references/bulk-photo-intake.md).

Create or refresh the resumable manifest:

```powershell
python scripts/photo_manifest.py scan --photos <client-photo-folder> --output "<records-root>\<Client Folder Name>\<intake-id>\intake-manifest.json" --client-id <client-id> --client-name "<client-name>" --intake-id <intake-id> --catalog-template <template.xlsx> --preflight-lock "<records-root>\<Client Folder Name>\<intake-id>\preflight-lock.json" --intake-method auto
```

Before confirmation, resolve exact duplicate image content deterministically across the selected source folder. Keep one canonical path per SHA-256 hash, prefer a filename without a copy-style suffix, then use natural path order as the tie-breaker. Record each redundant path, its canonical path, and its hash in the preflight; exclude the redundant path from the active manifest without deleting or renaming any source file. Bind the resolution digest and counts into the confirmed preflight. Any added, removed, renamed, or changed duplicate after confirmation requires a new preflight.

Immediately run `scripts/photo_quality_gate.py`. Do not begin grouping or identification unless every included photo has a valid image signature, byte count, and SHA-256 match and the active manifest contains no repeated content hash. Treat an unresolved exact duplicate as a hard blocker, not a warning.

When the client folder also contains archives, earlier tests, exports, or unrelated material, add one repeatable `--ignore-dir <name-or-relative-path>` argument per excluded directory. Use repeatable `--ignore-file <filename-or-relative-glob>` arguments for known screenshots or other image files that are not inventory evidence. Prefer exact filenames to broad globs. Confirm all exclusion counts and paths in the manifest before analyzing photos. Never depend on filename extensions alone to exclude an archive or screenshot that contains images.

Support flat, unnumbered camera rolls as a first-class BFG intake method. Do not require the user to create item folders, rename photos, add separator cards, or manually confirm item boundaries. Treat folder-per-item intake as an optional source of proposed boundaries when folders already exist.

Sort all photos naturally and case-insensitively, preserve the resulting manifest sequence, and never use timestamps alone to decide a boundary. When folders exist, sort them naturally so `2 - Chair` precedes `10 - Lamp`, treat each immediate child folder as a proposed group, and still verify visual cohesion.

For a flat sequence, perform the automated review protocol below before identification or valuation. Separator cards may strengthen evidence when present but are never required.

## Reconcile a flat sequence automatically

Perform all passes without prior-run assignments, identifications, or values:

1. Review forward in overlapping windows of at most 18 new photos plus up to three photos of context on each side. Record each proposed split with the left identity, right identity, confidence, and visual reason.
2. Review the same originals independently in reverse order. Do not show the reverse pass the forward boundaries.
3. Compare the two boundary sets. Reinspect every disagreement at original resolution and create an automated adjudication record. Join a disputed boundary only with high confidence and a written `lot_rationale` explaining why both sides are one sellable unit.
4. Review each provisional group's first, middle, and last images at original resolution for within-group cohesion. Add a split whenever product type, model, character, packaging identity, dinnerware piece type, shape, or intended buyer changes.
5. Run `scripts/sequence_review_gate.py` to reconcile the passes deterministically. When adjudication is missing or remains uncertain, default to a split and mark both adjacent groups `REVIEW`; never default to a merge.

Before reconciliation, run `scripts/review_provenance_gate.py`. Require different forward and reverse run IDs, opposite declared input order, a model and prompt hash, and blind isolated contexts. A pass that declares it saw another pass is invalid.

Do not ask the user to review boundaries during routine intake. Keep all automated results `DRAFT` and `PENDING` so uncertainty cannot become a live listing.

Treat shared brand, sports team, pattern, color, or photo-session proximity as insufficient evidence for a lot. Require a consistent sellable-unit identity or an explicit high-confidence `lot_rationale`. Never allow prior-run data to merge or split the locked result; after the lock, use prior data only to create discrepancy warnings.

Require every forward, reverse, cohesion, and adjudication JSON to include the manifest's exact `manifest_photo_digest`. Reject a pass created from a different or changed photo set even when its `photo_count` matches.

Analyze no more than 24 photos or 24 candidate objects in one AI pass. Commit results to the manifest and client ledger after every batch so the job can resume without repeating completed work. Keep a reconciliation count:

`photos discovered = photos assigned + separator photos + excluded photos + unresolved photos`

Never silently discard a blurry, duplicate, unsupported, or unassigned image. Record its status and reason. Keep exact duplicate source files untouched and retain their canonical-path mapping in the preflight and manifest audit records.

After grouping is locked, create an identity map containing one stable `item_id`, catalog `sku`, and Windows-safe `group_id` per ordinal. Run `scripts/apply_grouping.py` to bind the final grouping into the manifest and create `grouping-reconciliation.json`. Do not hand-edit assignments after this step.

## Store audit records outside the client delivery folder

Use `C:\BFG Bulk Import Records` as the default centralized audit-record root. Create one permanent folder per client and one immutable subfolder per intake iteration:

```text
C:\BFG Bulk Import Records\
└── <Client Folder Name>\
    ├── client-inventory.csv
    ├── <intake-id>\
    │   ├── preflight-lock.json
    │   ├── intake-manifest.json
    │   ├── photo-quality-verification.json
    │   ├── review-provenance.json
    │   ├── independent-review-lock.json
    │   ├── final-grouping.json
    │   ├── grouping-reconciliation.json
    │   ├── research-audit.json
    │   ├── research-verification.json
    │   ├── catalog-payload.json
    │   ├── catalog-builder-verification.json
    │   └── catalog-verification.json
    └── <later-intake-id>\
```

Keep the canonical `client-inventory.csv` at the client-records level so it spans every catalog revision. Store the preflight lock, manifest, review lock, grouping decisions, reconciliation, research audit, catalog verification, batch payloads, and listing queue inside the applicable intake-ID folder. Never place these internal files in the main client intake or delivery folder.

Treat an existing intake-ID folder as protected history. Do not overwrite or replace it. Resume it only when the user explicitly confirms that the same intake is continuing; otherwise create a new intake ID and folder.

After all included photos are assigned, create the client-facing categorized photo set:

```powershell
python scripts/organize_photos.py --manifest <intake-manifest.json> --output "<client-folder>\Categorized Inventory <YYYY-MM-DD>"
```

Use the intake or processing date in ISO format for the categorized-folder suffix. Before organizing photos, set each final manifest `group_id` to the unique Windows-safe catalog identity `<SKU> - <DESCRIPTION>` using the exact column B SKU and a concise form of the column C description. Use that `group_id` as the categorized item-folder name. Never use column D `LOCATION` as the item-folder name; retained rows keep their original locations and new rows use `Storage`. Copy photos; never move or rename the originals. Stop if a group ID is blank or duplicated, any photo remains unassigned, an active SHA-256 hash appears more than once, or a destination contains a conflicting file. Dated `Categorized Inventory` folders are ignored by later manifest scans to prevent duplicate counting. Include this directory with the catalog and exception workbook in every completed batch handoff.

## Inspect and identify

Inspect the full image and then zoom into:

- maker's marks, logos, labels, model numbers, serial or date codes
- measurements, materials, construction, hardware, and connectors
- included accessories and missing components
- condition, damage, repairs, alterations, and safety concerns
- variant indicators such as edition, colorway, production location, or packaging

Create a visual search fingerprint from every usable view before assigning an identity: object type, likely material, silhouette, construction, color, decoration, markings, and distinctive handle, hinge, lid, spout, foot, fastener, or connector geometry. Resolve contradictions between the proposed identity and visible construction. Do not carry a material guess such as ceramic, sterling, or solid wood into search merely because it appeared in an earlier boundary label.

State identification at the narrowest defensible level. Never call a make or model exact from visual similarity alone.

Use these confidence levels:

- `confirmed`: decisive label, mark, or model evidence is visible and consistent
- `probable`: multiple visual attributes match but a decisive identifier is missing
- `tentative`: category or maker family is plausible but alternatives remain
- `unidentified`: evidence is insufficient

Record `identification_basis`, `visible_markings`, and `missing_evidence`. Request close-ups when they can materially change value. Do not invent text hidden by blur, glare, cropping, or resolution.

Use the standing BFG condition assumption for valuation: unless positive photographic or owner-supplied evidence shows otherwise, treat the item as complete, functional, suitable for sale, and in typical good used condition. Record `condition_basis=assumed_standard_saleable`, `condition_grade=good`, and state that physical inspection was not performed. Missing condition detail alone must not cause `REVIEW`, a low-grade classification, or a damage discount. Use `observed` or `owner_reported` only when positive evidence supports a different condition. Keep safety, legality, authenticity, recall, and marketplace-policy uncertainty separate from condition grade.

## Research identity and market price

Follow [references/research-and-valuation.md](references/research-and-valuation.md). Keep identification confidence separate from pricing confidence: a confirmed object may still have low-confidence pricing, and a strong price cluster does not prove the proposed identity.

Use an adaptive `6 / 8 / 10` search ladder for every item. The first six attempts must include general web discovery, image search, Etsy-first marketplace discovery, an eBay Product Research or active-market cross-check, and at least three materially different strategies. Stop at six when either pricing confidence or decision confidence is HIGH. Otherwise continue to eight. Capture sold dates, availability, seller identity, and match attributes from the same search results; these checks must not create extra searches.

At eight attempts, three direct prices support MEDIUM pricing confidence only when coefficient of variation is at most 0.25 and highest-to-lowest ratio is at most 1.75; two exact prices within 35% may also support MEDIUM. One price or a dispersed set produces a LOW-confidence provisional price but may still yield a confident disposition when its conservative decision floor clears a threshold. A zero-comp confirmed/probable common low-value item may receive the exact operational label `$40-$50 STAFF DECISION` and a $45 operational handling price, explicitly not a market-value claim. Continue to ten only for a plausible high-value, rare, collector-significant, regulated, or materially misidentified item. Never exceed ten attempts.

Etsy remains a current-market surface; use eBay sold/Product Research across its available three years as the preferred realized-price source and eBay active as a cross-check. A Product Research query may capture multiple transactions and metrics without counting each row as another search. Included pricing evidence may be current active or completed/sold listings only when the evidence is opened or captured directly, availability is verified, the item is exact or near by structured attributes, the seller/listing is unique, the price is normalized to a one-item USD total, and the evidence hash is unique. Do not call an active price a realized sale.

Auction data is identification-only. It can establish maker, model, age, terminology, or collector significance, but it must never enter the price calculation. Category pages, search pages, storefronts, snippets, price guides, sponsored results, and broad analogues cannot be included as pricing comps.

For included prices, calculate a weighted-median anchor. Weight eBay sold/completed `1.00`, eBay active `0.70`, Etsy sold/completed `0.80`, and Etsy active `0.60`; multiply near matches by `0.85`. Apply sold-age weights of `1.00` through 12 months, `0.85` for 13-24 months, and `0.70` for 25-36 months. Scarce/vintage evidence uses `0.90` and `0.80` in the latter bands; older evidence receives `0.50` only with current active corroboration. Clamp Etsy at 5% below and eBay at 5% above the anchor to the defensible included-price interval.

Keep pricing confidence separate from decision confidence. HIGH pricing requires either four stable prices including two eBay sold records, or a stable three-price eBay/Etsy set with an exact match and a dated sold record within 12 months. MEDIUM requires stable dispersion or two exact prices within 35%. Calculate a conservative decision floor: one active exact price receives a 30% haircut, two active prices use at least a 15% haircut from the lower price, and three or more use 90% of the lower quartile; sold evidence uses smaller documented haircuts. SELL normally requires the conservative decision floor to reach $55 plus confirmed/probable identity and safety clearance. A controlled $50 exception may also authorize SELL when at least two direct prices produce a floor of at least $49.50, when at least two stable direct prices have a $50 observed floor (CV at most 0.25 and ratio at most 1.75), or when exactly two active direct prices tightly bracket $50 with a rounded midpoint at least $47.50 and ratio at most 1.35. Zero-comp operational $45 items never qualify for this exception. DONATE still requires a medium/high-confidence complete range below $40.

Record search-budget metrics for every batch: total, average, maximum, ten-search count/share, average direct pages opened, and valid comps per search. Processing, time weighting, seller deduplication, and semantic comparison do not count as searches. On the Rothschild regression population, do not exceed the sealed baseline of 972 total attempts, 8.45 average, or 26 ten-search items.

Use Google web/image discovery when available. The approved integrated web/image search may substitute for Google discovery when browser access cannot scale, but label the surface honestly. Do not claim a Google search that was not performed. Never scrape a restricted eBay interface; capture visible evidence from an authorized session.

Store the v2.9 pilot audit in the structured format defined by [references/research-audit-schema.md](references/research-audit-schema.md), then run `scripts/price_first_gate.py`. The gate must reconcile the exact research population to the ledger and fail closed on missing attempts, unavailable listings, missing sold dates, missing match attributes or seller keys, auction pricing, non-reproducible formulas, unsupported confidence, or a search-budget violation.

## Value and decide

Normalize comps to the same currency and note whether shipping is included. Compare like-for-like condition and completeness using normal saleable-condition transactions. Exclude damaged, repair, incomplete, parts-only, or unusually poor-condition sales unless positive evidence shows that the subject shares that condition.

Produce:

- `market_value_low`, `market_value_mid`, and `market_value_high`
- `decision_basis_value`, which must fall inside the supported range
- `valuation_basis` and `valuation_confidence`
- `ebay_price`: reasonable initial list price, not an inflated anchor
- `local_price`: Facebook Marketplace or local pickup price when local demand and shipping friction make it appropriate
- `quick_sale_price`: price intended to move quickly
- `decision`: `SELL`, `DONATE`, `REVIEW`, or `CONFIRM DONATION`

Use the v2.9 adaptive-age rule:

- `SELL` when the conservative decision floor is at least $55, or the controlled $50 exception passes, with medium/high decision confidence, confirmed/probable identity, and safety clearance; numeric pricing confidence may remain LOW when the disposition is nevertheless decisive
- `DONATE` only for `market` pricing whose credible high value is below $40
- `CONFIRM DONATION` for an eligible recommended price from $40 through $49.99 or a clearly labeled operational $45 staff price
- use `REVIEW` when the conservative floor or ceiling crosses a decision threshold, unusual collector value remains unresolved, identity is tentative, safety/policy is uncertain, or the item is unpriced
- never erase a defensible provisional price merely because the disposition remains `REVIEW`

For every newly created or reappraised supported $40-through-$49.99 item, use `CONFIRM DONATION`, set `donation_confirmation_status` to `PENDING`, and include this instruction in `decision_rationale`, column H, and its Exceptions row: `Confirm this item will not be sold before donation or rehoming.` Keep it `DRAFT` and `PENDING` until BFG resolves it. To transition to `DONATE`, record `donation_confirmation_status=CONFIRMED`, `donation_confirmed_by`, an ISO `donation_confirmed_at`, and set `listing_status=DO_NOT_LIST`. If BFG declines donation, record `donation_confirmation_status=DECLINED`, the confirmer and timestamp, but do not rewrite the research recommendation as `SELL` unless a supported reappraisal places the entire range in the SELL band. Do not retroactively change a retained historical decision unless the item is explicitly reappraised.

Do not treat the $50 threshold as net profit unless the user changes the rule. Note fees, shipping burden, testing, repairs, and handling separately in `decision_rationale`.

Treat required testing as an operational limitation, not a reason by itself to use `REVIEW`. When BFG already knows an item will be tested:

- set `testing_status` to `PLANNED`
- research and report the supported value if tested working
- record the supported untested/as-is value and the dollar difference in `testing_notes`
- use the tested-working value for `decision_basis_value` and the pricing response
- keep `listing_status` at `DRAFT` until testing passes
- use `REVIEW` only for identification, authenticity, safety, policy, grouping, or valuation uncertainty independent of the planned test

After testing, set `testing_status` to `PASSED` or `FAILED`. A failed test requires a valuation refresh based on the observed failure; never continue using the tested-working value as the decision basis.

Keep disposition separate from Berryfine routing:

- `decision` answers whether the acquired item should be sold, donated, held for donation confirmation, or reviewed for independent uncertainty using the $50 rule.
- `triage_lane` answers how a sellable item should move through operations: `Auction Candidate`, `Fixed Price Fast`, `Local Sale`, `Bundle / Lot`, or `Donate / Rehome / Recycle`.
- Use `Auction Candidate` when supported value is at least $125 or collector signals justify specialist review. This does not replace the $50 SELL threshold.

## Create the inventory record

Populate every required field in [references/inventory-schema.md](references/inventory-schema.md). Use empty values rather than guesses. Keep:

- facts visible in photos
- identification inferences
- comp evidence
- pricing recommendations
- listing copy

as distinct fields.

For multiple quantities or separately listed duplicates, use separate item rows unless they will be sold as one lot. Set `parent_item_id` to connect variants, components, or split listings.

## Maintain one ledger per client

Prepare a UTF-8 JSON payload matching the schema, then use:

```powershell
python scripts/inventory_ledger.py upsert --ledger "<records-root>\<Client Folder Name>\client-inventory.csv" --input "<records-root>\<Client Folder Name>\<intake-id>\batch.json" --audit-log "<records-root>\<Client Folder Name>\item-revisions.jsonl"
```

The script creates or updates rows by `item_id`, rejects cross-client merges, preserves a stable column order, writes atomically, and appends hash-chained item revision events when `--audit-log` is supplied.

Create a sellable listing queue with:

```powershell
python scripts/inventory_ledger.py listing-queue --ledger "<records-root>\<Client Folder Name>\client-inventory.csv" --output "<records-root>\<Client Folder Name>\<intake-id>\listing-queue.csv"
```

Keep one canonical ledger per client. Use intake IDs, not separate ledgers, to distinguish batches unless the user explicitly wants isolated projects.

## Generate the client catalog workbook

Treat the supplied workbook as the formatting authority. Use the spreadsheet workflow to inspect and render it before writing output. Treat the template filename as generic and never derive the client or output filename from it; for example, `GenericCatalogTemplate.xlsx` is only a template.

Generate `catalog-payload.json` with `scripts/catalog_payload.py`. On Windows PCs with desktop Excel, use `scripts/catalog_builder.ps1` to create the New Catalog and Exceptions workbooks together and write `catalog-builder-verification.json`. The builder refuses overwrites, preserves all retained locations and displayed fills, applies `Storage` only to new rows, recalculates formulas, and will not publish only one workbook. When Excel is unavailable, use the Codex spreadsheet workflow but satisfy the same payload and verification contracts.

1. Open the supplied `.xlsx` template and inspect every sheet, used range, formula, merged cell, style, column width, row height, freeze pane, print setting, hidden row or column, and data validation.
2. Create a genuinely new workbook from the template and current intake results; never overwrite the user's reference file and never substitute or copy a prior test-run output as the new deliverable.
3. Map canonical inventory fields to the template's existing columns. Do not rename, reorder, add, or remove visible columns unless the user requests it.
4. Enforce this client-catalog column contract:
   - Preserve the existing columns through column I, including column I's exact header, position, historical values, formulas, and formatting. Do not rename `Column1`, `Sold Price`, or another template-specific column I header. Leave column I blank on a newly appended row unless the supplied client template or the user defines a value for it.
   - Keep column D's header as `LOCATION`. Preserve every pre-populated column D value exactly, including blanks. Write the exact text `Storage` only in column D for newly appended rows. Do not normalize, replace, or backfill retained location data.
   - Keep column H's header as `HISTORY/INFO`. Put the detailed client-facing response in column H: defensible identification, visible condition and completeness, direct-market valuation basis, supported price guidance, collector or variant notes, and the tested-working versus untested value difference when testing is planned. Keep comp URLs and extended research evidence in the centralized audit record rather than overloading the catalog cell.
   - Add column J with the exact header `RECOMMENDED ACTION`. Populate current-intake rows with exactly `SELL`, `DONATE`, `REVIEW`, or `CONFIRM DONATION` from the validated `decision` field so the column sorts and filters cleanly. When introducing J to a template that did not have it, leave retained historical rows blank unless the user explicitly requests a fresh appraisal. When the template already has J, preserve every retained J value and style exactly unless that row is explicitly reappraised. Never write testing status in this column.
   - Add column K with the exact header `RESEARCH REVIEW`. Use the friendly internal hyperlink label `Open research`; never place a raw marketplace URL on the Inventory List. Add `Research Review` and `Comparable Evidence` tabs with one row per item and one row per comparable respectively. Keep direct HTTPS source links in the evidence tab, use filters and frozen headers, and preserve full audit meaning without crowding the catalog.
   - Extend the header style, filter or table range, print area, and column width through K without shifting or overwriting columns A through I.
5. Add one row per unique independently sellable item or intentional lot.
6. Preserve every existing row and cell fill exactly. Blue fill means sold; do not remove, move, reinterpret, recreate, or recolor any retained historical row based on its recommended action.
7. Apply the current-intake row-fill rule across columns A through J using the final `RECOMMENDED ACTION` value:
   - `SELL`: no fill color
   - `REVIEW`: solid yellow fill `#FFFF00`
   - `DONATE`: solid yellow fill `#FFFF00`
   - `CONFIRM DONATION`: solid yellow fill `#FFFF00`
   Copy only the necessary font, alignment, border, number format, formula, validation, row-height, and print-layout properties. Clear copied fills first, then apply yellow only to current-intake `REVIEW`, `DONATE`, and `CONFIRM DONATION` rows. Do not use conditional formatting for these disposition fills. Yellow is an attention color and never means sold; blue remains the sold indicator. When an Excel table must be unbanded so new SELL rows can remain visibly unfilled, materialize the read-only source table's displayed formats and restore them to the retained range in one bulk format operation before styling new rows.
8. Preserve the manifest's natural item/photo order when appending new rows. Do not reorder the original catalog rows.
9. Extend formulas, borders, validations, and print area through all populated rows without changing original fills.
10. Store SKU and IDs as text, prices as numeric currency values, quantities as numbers, and dates as dates.
11. Preserve blank values when evidence is unavailable. Do not insert guesses merely to fill the sheet.
12. Wrap and auto-fit newly appended catalog rows and populated Exceptions rows after setting final column widths. Render and visually review every sheet. Compare original displayed fills before and after; retained-row fills must match exactly. Confirm each current-intake `SELL` row is unfilled and each current-intake `REVIEW`, `DONATE`, or `CONFIRM DONATION` row has a solid `#FFFF00` yellow fill across A:J, with no new disposition-based conditional formatting. Verify retained column D values equal the template, new column D values equal `Storage`, column H contains the intended detailed response, column I remains intact, and column J contains only permitted recommended actions for current-intake rows. Also check for clipped text, broken formulas, missing rows, style drift, and pagination problems.
13. Derive `<Client Folder Name>` from the outermost/main client intake folder, sanitize only characters invalid in a Windows filename, and save the deliverable directly in the main client folder as `<Client Folder Name> New Catalog.xlsx`. Append `New Catalog` exactly once; do not duplicate it when the folder name already ends in `New Catalog`. The preflight must reject a proposed catalog filename that does not end with the exact suffix ` New Catalog.xlsx`.

Create `<Client Folder Name> Exceptions.xlsx` directly in the main client folder from the current run. Do not create an `output` subfolder. Only the categorized inventory directory receives a date suffix.

The completed `.xlsx` is the required client deliverable. The detailed ledger, manifest, comp evidence, and listing queue are supporting audit files and must live only under the centralized audit-record root unless the user explicitly requests another records location.

## Enforce delivery completeness

Treat the New Catalog workbook and Exceptions workbook as mandatory paired outputs. Create an empty-but-headed Exceptions workbook when no exceptions remain. Do not organize the final client-facing photo set or report the batch complete until both workbooks have been authored and spreadsheet verification has passed.

After creating all deliverables, run:

```powershell
python scripts/catalog_gate.py --template <template.xlsx> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx" --ledger <client-inventory.csv> --intake-id <intake-id> --catalog-payload <catalog-payload.json> --builder-verification <catalog-builder-verification.json> --output <catalog-verification.json>
python scripts/delivery_gate.py --client-folder <client-folder> --manifest <intake-manifest.json> --ledger <client-inventory.csv> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --preflight-lock <preflight-lock.json> --catalog-verification <catalog-verification.json>
```

Both gates must pass before the completion report. The catalog gate compares every retained value and formula through I, and through J when J already existed; requires the hash-bound Excel materialized-format snapshot for retained appearance; reconciles only current-intake ledger decisions by column B item ID to column J; checks new-row location, wrapped history, blank column I, direct fills, formula errors, column J width, filter coverage, print area, and Exceptions coverage; and writes a hash-bound verification record. Without Excel builder evidence, it also compares normalized retained styles directly. The delivery gate rejects a stale verification, stale or unconfirmed preflight, changed photo content, path escape, or incomplete deliverable. Report the exact blocker; never describe the ledger, audit files, or categorized photos as a complete client delivery when either workbook is absent.

Finally run `scripts/bfg.py audit`. It must reject a research PASS created under an earlier evidence-policy version. Its `disposition_summary` is the authoritative end-of-run total and must reconcile total items to `SELL + DONATE + CONFIRM DONATION + REVIEW`; report `needs_owner_attention` and `human_review_pending` separately. Create `audit-seal.json` with `scripts/audit_seal.py` only after every gate passes; never overwrite a seal. Record later testing, listing, sale, donation, return, identification confirmation, or identification correction with `scripts/outcome_ledger.py` so realized outcomes never overwrite the original appraisal. Use `scripts/outcome_ledger.py accuracy-report` to measure identification accuracy, price-range coverage, and median absolute percentage error. Never claim the 90%-97.8% goal is achieved until the report authorizes the claim from at least 100 independently observed identities and 100 realized sales.

## Prepare listings

Catalog creation and marketplace publication are separate operations. This
skill may create catalog rows and listing drafts, but it must never publish,
transmit, or activate a listing on eBay, Facebook Marketplace, or another
marketplace.

For every AI-created row, set `human_review_status` to `PENDING`. The skill must
never approve its own output. A human reviewer must explicitly set
`human_review_status` to `APPROVED` and provide `approved_by` and `approved_at`.

Set `safety_status` to `REVIEW_REQUIRED` when legality, ownership,
authenticity, recalls, hazardous materials, product safety, or marketplace
policy is unclear. Set it to `PROHIBITED` with `listing_status` `DO_NOT_LIST`
when an item is known to be prohibited.

Create listing copy only for sufficiently identified items. Make titles factual and search-oriented. Include condition defects and missing components; do not hide them in generic wording.

Tailor each marketplace:

- eBay: searchable title, item specifics, shipping-relevant details, and an evidence-based price
- local: concise pickup description, dimensions, transport considerations, and local price
- quick sale: lowest defensible price and any time-sensitive caveat

Set `listing_status` to `READY` only when photos, identification, condition,
price, required disclosures, cited valuation evidence, safety clearance, and
explicit human approval all pass validation. Otherwise use `NEEDS_PHOTOS`,
`NEEDS_RESEARCH`, `DRAFT`, or `DO_NOT_LIST`. Treat the generated listing queue
as a human-review file, never as permission to publish.

## Report the result

For a single item, give a compact appraisal plus the evidence links.

For a batch, report:

- a mandatory disposition summary after every run with total items, `SELL`, `DONATE`, `CONFIRM DONATION`, and `REVIEW`; require the four disposition counts to add exactly to total items
- a separate `Needs owner attention` total equal to `REVIEW + CONFIRM DONATION`, with both component counts shown; do not mix this operational attention total with formal `human_review_status`
- the count whose formal `human_review_status` is `PENDING`, when applicable, labeled separately from disposition and owner-attention totals
- counts received and processed, including exclusions when they differ from total inventory items
- search-budget totals: total and average attempts, maximum attempts, ten-search count/share, average direct pages opened, valid comps per search, and whether the regression guard passed
- aggregate low, mid, and high market value
- highest-value and highest-uncertainty items
- missing photos or research blockers
- paths to the updated client ledger and listing queue
- path to the centralized iteration records folder
- path to the completed template-matched client catalog
- manifest reconciliation totals and the next unresolved photo, if any

State the valuation date and clarify that prices are estimates, not guarantees. Flag recalls, authenticity concerns, unsafe electrical goods, weapons, hazardous materials, or marketplace-restricted items for manual review rather than advising routine listing.
