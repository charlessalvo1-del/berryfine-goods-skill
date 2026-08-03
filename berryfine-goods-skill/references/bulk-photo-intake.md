# Bulk photo intake

## Contents

- [Recommended user setup](#recommended-user-setup)
- [Mandatory preflight confirmation](#mandatory-preflight-confirmation)
- [Optional method: one folder per item](#optional-method-one-folder-per-item)
- [Primary BFG method: continuous sequence](#primary-bfg-method-continuous-sequence)
- [Automated flat-sequence review](#automated-flat-sequence-review)
- [Folder scan and manifest](#folder-scan-and-manifest)
- [Processing and checkpointing](#processing-and-checkpointing)
- [Categorized photo delivery](#categorized-photo-delivery)
- [Client catalog column contract](#client-catalog-column-contract)
- [Output contract](#output-contract)
- [Mandatory delivery gate](#mandatory-delivery-gate)

## Recommended user setup

Use a local folder instead of uploading hundreds of images into chat.

Require Python 3.11 or newer. Run command examples from the repository root using the complete nested Skill path.
Replace every `<...>` placeholder with the real value and quote concrete paths containing spaces before execution.

The user may provide one flat, unnumbered camera roll. Do not require item folders, renamed photos, separator cards, or manual boundary confirmation. A folder-per-item layout remains supported when it already exists, but it is not required for BFG processing.

Flat sequence example:

```text
Client Name/
├── Inventory 8 1 2026/
│   ├── IMG_0001.jpg
│   ├── IMG_0002.jpg
│   └── ...
├── catalog-template.xlsx
├── Client Name New Catalog.xlsx
├── Client Name Exceptions.xlsx
└── Categorized Inventory 2026-08-02/
```

Optional folder-per-item structure:

```text
Client Name - 2026-07-26/
├── photos/
│   ├── Brass Table Lamp/
│   │   ├── IMG_0001.jpg
│   │   ├── IMG_0002.jpg
│   │   └── IMG_0003.jpg
│   ├── Oak Side Chair/
│   │   ├── IMG_0004.jpg
│   │   └── IMG_0005.jpg
│   └── Blue Glass Set/
│       └── ...
├── catalog-template.xlsx
├── Client Name New Catalog.xlsx
├── Client Name Exceptions.xlsx
└── Categorized Inventory 2026-07-26/
```

Add the client folder to the Codex workspace or place it under a workspace Codex can access. Then provide the folder path in the request.

Keep internal history outside the client folder. The default records structure is:

```text
C:\BFG Bulk Import Records\
└── Client Name\
    ├── client-inventory.csv
    ├── intake-2026-001\
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
    └── intake-2026-002\
        └── ...
```

The client-level ledger spans all iterations. Each intake-ID folder preserves that run's manifest, review, grouping, reconciliation, research, batch, and optional listing-queue artifacts.

## Mandatory preflight confirmation

Before modifying source evidence or writing client-facing deliverables, inspect the client folder read-only and report the selected photo folder and template workbook, photo and extension counts, flat-versus-nested structure, workbook hash and sheet structure, and every prior-run directory or artifact that will be excluded. Propose a new intake ID, dated categorized-folder name, exact client-facing deliverable names, and exact centralized records folder `C:\BFG Bulk Import Records\<Client Folder Name>\<intake-id>`. The sole permitted pre-confirmation write is the PENDING preflight record in the centralized audit folder.

Hash the selected images during preflight and automatically resolve exact duplicates before confirmation. For each SHA-256 group, retain one canonical path, preferring a filename without a copy-style suffix and then natural path order. Report the group count, retained canonical path, and every redundant path. Record redundant files as `exact_duplicate` exclusions in the preflight and manifest without moving, renaming, or deleting the originals. Bind the resolution digest into the confirmation so any later duplicate-set change invalidates the run.

Also state the full catalog rules: preserve pre-populated rows and their existing `LOCATION` values; use `Storage` only on new rows; place detailed responses in H; preserve I; add `RECOMMENDED ACTION` in J; apply the action-fill rules; and use `SELL` at $50 or more, `CONFIRM DONATION` from $40 through $49.99, `DONATE` below $40, and `REVIEW` only for independent uncertainty. Explicitly ask the user to confirm these catalog rules. A generic preflight confirmation that does not state them is not sufficient.

Create a PENDING `preflight-lock.json` with `scripts/preflight_lock.py create`, pause, and obtain explicit user confirmation. Record the confirmation with `scripts/preflight_lock.py confirm`; never invent the confirming identity. The confirmed lock binds the exact source photo hashes, template hash, exclusions, output paths, and catalog rules. Any change requires a new lock. A new test must not reuse a prior manifest, folder assignment, catalog, exception workbook, identification, valuation, or categorized directory. Prior results may be compared only after the independent run is complete unless the user explicitly requests a baseline-assisted run.

After scanning, run `photo_quality_gate.py`. After the blind passes, run `review_provenance_gate.py` before sequence reconciliation. After final grouping, run `apply_grouping.py`; manual assignment changes after the grouping lock are prohibited.

### Catalog-only legacy refresh

When the user explicitly states that prior research is complete and requests only a catalog correction, use a new `legacy-catalog-refresh` intake instead of treating the legacy rows as a new photo/research intake. Bind the source intake ID, source-ledger hash, and one verified categorized-photo delivery in the preflight. Do not rerun grouping, image review, or the current structured-comparables gate. Run `categorized_inventory_gate.py` once against the completed source manifest and categorized set. Its immutable verification record is the only legacy-refresh write allowed before preflight because it seals existing evidence without modifying it. Keep the verified set directly in the main client folder rather than inside a test or archive folder.

Run `legacy_catalog_refresh.py prepare`, upsert its target-intake batch with the item revision log, and run `legacy_catalog_refresh.py verify`. Preserve identification, values, research, photos, and stable item IDs. Permit only deterministic policy migration: legacy `DONATE` from $40 through $49.99 becomes `CONFIRM DONATION`; existing `SELL`, below-$40 `DONATE`, and independently uncertain `REVIEW` remain. Keep every refreshed row `DRAFT` and human-review `PENDING`; the verification must prohibit listing authorization.

Generate both workbooks from the untouched original template. From the repository root, run:

```powershell
python .\berryfine-goods-skill\scripts\catalog_gate.py --template <template.xlsx> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx" --ledger <client-inventory.csv> --intake-id <new-intake-id> --catalog-payload <catalog-payload.json> --builder-verification <catalog-builder-verification.json> --output <catalog-verification.json>
python .\berryfine-goods-skill\scripts\bfg.py legacy-audit --manifest <source-manifest.json> --preflight <preflight-lock.json> --ledger <client-inventory.csv> --intake-id <new-intake-id> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx"
python .\berryfine-goods-skill\scripts\delivery_gate.py --workflow legacy-catalog-refresh --client-folder <client-folder> --manifest <source-manifest.json> --ledger <client-inventory.csv> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --categorized-verification <categorized-verification.json> --intake-id <new-intake-id> --preflight-lock <preflight-lock.json> --catalog-verification <catalog-verification.json>
```

`legacy-audit` validates retained source evidence and policy-only refresh conditions; the delivery gate performs final legacy-refresh delivery verification. Both applicable checks must return `PASS`. Do not process a legacy refresh through the normal full-intake `bfg.py audit` artifact requirements. The final gate performs one destination-only digest check; it does not recreate current-intake photo-quality, blind forward/reverse review, new grouping research, or completed-sale research artifacts. The normal full-intake audit does not replace the legacy delivery gate. No command in this workflow authorizes a listing. Never describe this workflow as new photo review, new research, or listing approval.

Supply each prior-test or archive directory as an exact repeatable `--ignore-dir` rule. Record the exclusions in the new manifest so the audit trail proves that old images were not processed.

## Optional method: one folder per item

Create one immediate child folder for each independently sellable object or intentional lot. Put every view of that item inside its folder.

Folder names do not need numbers and individual photos do not need to be renamed. Descriptive folder names are helpful but are not treated as confirmed identification.

The skill must:

- treat each immediate child folder as one proposed item group
- preserve original photo filenames and timestamps
- generate a stable unique `item_id` for the catalog
- verify that the folder contains one item or intentional lot
- flag folders containing multiple unrelated objects for review or splitting
- keep empty folders and unsupported files out of the item count while reporting them separately

Numbered folder prefixes such as `001 - Brass Lamp` are optional and only affect processing order.

Sort item folders and photo paths naturally and case-insensitively. Numeric prefixes control processing order when present, so `2 - Chair` sorts before `10 - Lamp`. Preserve the resulting manifest sequence when adding new rows to the client catalog; do not reorder existing catalog rows.

## Primary BFG method: continuous sequence

Also support a single camera-roll folder when the user explicitly chooses sequence intake:

```text
photos/
├── IMG_0001.jpg
├── IMG_0002.jpg
└── ...
```

Separator cards, QR codes, or barcodes may be used when convenient, but never require them. Do not infer sequence boundaries solely from timestamps. Use the automated multi-pass visual protocol below and preserve uncertain decisions as conservative splits with `REVIEW` status.

## Automated flat-sequence review

Run the following without prior-test grouping, identification, or valuation data:

1. **Forward pass:** inspect the sequence in overlapping windows containing no more than 18 new photos and up to three context photos on either side. Record split positions, the identities on both sides, confidence, and visible evidence.
2. **Reverse pass:** review the original-resolution photos independently from the end toward the beginning. Do not expose the forward boundaries to this pass.
3. **Automated adjudication:** compare both boundary sets and reopen every disagreement at original resolution. A disputed join requires high confidence plus a written `lot_rationale` proving one sellable unit.
4. **Cohesion pass:** inspect each provisional group's first, middle, and last images. Split changes in product type, model, character, package identity, dinnerware piece type, shape, or intended buyer even when brand, team, pattern, or color is shared.
5. **Deterministic gate:** run `scripts/sequence_review_gate.py`. When adjudication is missing or uncertain, default to a split and mark both adjacent groups `REVIEW`; never default to a merge.

Example:

```powershell
python .\berryfine-goods-skill\scripts\sequence_review_gate.py --manifest <intake-manifest.json> --forward <forward-review.json> --reverse <reverse-review.json> --cohesion <cohesion-review.json> --adjudication <adjudication.json> --output <final-grouping.json>
```

Use this format for each forward, reverse, or cohesion review:

```json
{
  "version": 1,
  "pass": "forward",
  "photo_count": 12,
  "manifest_photo_digest": "<64-character digest from intake-manifest.json>",
  "boundaries": [
    {
      "after_sequence": 303,
      "confidence": "high",
      "left_identity": "clear champagne flute set",
      "right_identity": "clear etched goblet set",
      "reason": "The bowl shape and etched decoration change at the boundary."
    }
  ]
}
```

Use the same structure with `pass` set to `reverse` or `cohesion`. Use this format for disagreements:

```json
{
  "version": 1,
  "pass": "adjudication",
  "photo_count": 12,
  "manifest_photo_digest": "<64-character digest from intake-manifest.json>",
  "decisions": [
    {
      "after_sequence": 5,
      "decision": "split",
      "confidence": "high",
      "left_identity": "collectible figure set",
      "right_identity": "single boxed figurine",
      "reason": "The packaging and collectible format identify different products.",
      "lot_rationale": ""
    }
  ]
}
```

A `join` adjudication must use `high` confidence and a nonblank `lot_rationale`.

The AI performs these passes without requesting routine boundary work from the user. Each pass must carry the exact manifest photo digest; photo count alone is insufficient. All resulting inventory rows remain `DRAFT` and `PENDING` until normal BFG human listing approval.

Use prior-run groupings only after the independent result is locked. A prior run may create a discrepancy warning but may not automatically merge, split, identify, or value the current intake.

## Photo sequence

For each item, capture:

1. separator card or item ID
2. front or hero view
3. back or underside
4. side or profile
5. maker mark, label, signature, model, or serial number
6. defect or condition close-up
7. measurement or scale view

Add working-state, cord, hardware, interior, provenance, or accessory photos when applicable. Capture 8–12 photos for likely auction candidates.

## Folder scan and manifest

Run:

```powershell
python .\berryfine-goods-skill\scripts\photo_manifest.py scan --photos <photos> --output "C:\BFG Bulk Import Records\<Client Folder Name>\<intake-id>\intake-manifest.json" --client-id <client-id> --client-name "<client-name>" --intake-id <intake-id> --catalog-template <template.xlsx> --preflight-lock <preflight-lock.json> --intake-method auto [--ignore-dir <archive-folder>] [--ignore-file <file-or-glob>]
```

The scanner:

- sorts paths naturally
- auto-detects folder grouping when photos are stored in child folders
- supports explicit `folders` and `sequence` methods
- assigns every nested photo to its immediate top-level item folder
- sorts folders and photos naturally by relative path
- records relative path, size, timestamp, SHA-256, and processing state
- keeps one deterministic canonical path per exact SHA-256 hash and records every redundant copy as an automatic `exact_duplicate` exclusion
- binds the duplicate-resolution policy, mapping, counts, and digest to the confirmed preflight and manifest
- preserves prior item assignments only when the file content hash is unchanged; changed content resets to pending
- marks new and missing files without deleting history
- writes atomically
- skips `.git`, `__pycache__`, and `output` directories by default
- skips generated `Categorized Inventory YYYY-MM-DD` directories by default
- accepts repeatable `--ignore-dir` rules for archive, prior-test, or non-intake folders
- accepts repeatable `--ignore-file` rules for known screenshots, exports, or other non-inventory images; use exact filenames when possible
- records skipped directories, their image counts, and unsupported files in the manifest instead of silently discarding them

Use `--intake-method folders` to require folder grouping. Use `--intake-method sequence` for a flat camera roll with separator cards. In `auto` mode, any nested photo folders select folder grouping; an entirely flat folder selects sequence grouping.

The scanner does not visually identify objects. Folder names and separator cards establish proposed groups that must still be reviewed.

## Processing and checkpointing

Process a maximum of 24 photos or 24 candidate objects per analysis pass. For flat-sequence boundary detection, use at most 18 new photos plus up to three context photos on each side. Use smaller batches when images are large or identification is difficult.

After every pass:

- assign each reviewed photo a status
- connect item photos to one stable `item_id`
- upsert completed items into the client ledger
- record comp evidence
- save the next pending sequence in the manifest
- generate a fresh reconciliation summary

Allowed photo statuses:

- `pending`
- `assigned`
- `separator`
- `excluded`
- `unresolved`
- `missing`

Do not mark a photo `excluded` without a reason.

## Categorized photo delivery

After every included photo has an `assigned` status and unique spreadsheet-matched `group_id`, run:

```powershell
python .\berryfine-goods-skill\scripts\organize_photos.py --manifest <manifest.json> --output "<client-folder>\Categorized Inventory <YYYY-MM-DD>"
```

Use the intake or processing date in ISO format. Set each final `group_id` and nested item-folder name to the Windows-safe `<SKU> - <DESCRIPTION>` identity from catalog columns B and C. Never use column D as the folder name; retained locations may vary and new rows use `Storage`. Reject blank, duplicate, reserved, absolute, or path-traversing group IDs and relative paths. Reject any active SHA-256 hash assigned to more than one categorized destination. The script copies files, verifies every source and destination SHA-256 against the manifest, and preserves the flat originals. Use `--resume` only to verify and complete an existing categorized directory; a same-name file with different contents is a hard failure.

## Client catalog column contract

Preserve the template layout and apply these exact output rules:

- preserve columns A through I in place; preserve column I's existing header, values, formulas, and formatting
- keep the column D header `LOCATION`; preserve every pre-populated D value exactly, including blanks, and write `Storage` only for newly appended rows
- keep the column H header `HISTORY/INFO` and put the detailed identification, condition, valuation, pricing, collector, and applicable testing narrative in H
- add column J with the exact header `RECOMMENDED ACTION`
- write only `SELL`, `DONATE`, `REVIEW`, or `CONFIRM DONATION` in J for rows appraised in the current intake; when J is new, leave retained historical rows blank unless explicitly reappraised, but when J already exists preserve its retained values and styles exactly
- extend the header style, filter or table range, print area, and usable width through J without altering the original fills in A:I
- preserve every original fill and never recolor retained historical rows; blue remains sold
- leave current-intake `SELL` rows unfilled
- apply a solid yellow `#FFFF00` fill across A:J to current-intake `REVIEW`, `DONATE`, and `CONFIRM DONATION` rows; yellow is an attention color and does not mean sold
- clear copied row fills before applying the action-specific fill, and do not implement disposition color with conditional formatting
- when unbanding a table, materialize the read-only source table's displayed formats and restore them to the retained range in one bulk format operation so its visible appearance remains unchanged
- wrap and auto-fit new catalog rows and populated Exceptions rows after final column widths are set; reject clipped client-facing text during visual QA
- route every supported $40-through-$49.99 current item to `CONFIRM DONATION`, include `Confirm this item will not be sold before donation or rehoming.` in H and its Exceptions row, and keep it `DRAFT` and `PENDING` until a named BFG confirmation is recorded

## Resuming

On a later run:

1. load and refresh the manifest from the applicable centralized intake-ID folder
2. find the first `pending` or `unresolved` photo
3. load the existing client ledger
4. continue from that point

Do not revalue completed items unless the user asks for a refresh or the prior result is incomplete.

## Output contract

Produce:

- the newly generated client catalog in the exact supplied workbook style, named `<Client Folder Name> New Catalog.xlsx` and saved directly in the main client folder
- a `Categorized Inventory YYYY-MM-DD` directory containing one spreadsheet-matched folder per item and copies of all assigned photos
- `<Client Folder Name> Exceptions.xlsx`, generated from the current run and saved directly in the main client folder, including an empty-but-headed workbook when no exceptions remain
- a canonical detailed inventory ledger at `C:\BFG Bulk Import Records\<Client Folder Name>\client-inventory.csv`
- the intake manifest in `C:\BFG Bulk Import Records\<Client Folder Name>\<intake-id>`
- the confirmed preflight lock and hash-bound catalog verification in the same intake-ID folder
- comp evidence or research audit data in the same intake-ID folder
- a listing queue for SELL items in the same intake-ID folder when requested

Never overwrite the supplied template, original photos, or an existing intake-ID records folder.
Do not create an `output` subfolder. Do not place audit artifacts in the main client folder. Do not copy a prior test-run catalog or exception workbook and present it as newly generated output. Only the categorized inventory directory receives a date suffix among client-facing deliverables; audit iterations are distinguished by intake ID.

## Mandatory delivery gate

Treat `<Client Folder Name> New Catalog.xlsx` and `<Client Folder Name> Exceptions.xlsx` as mandatory paired deliverables. Create the Exceptions workbook with headers even when it has no exception rows.

After spreadsheet rendering and content checks, run:

```powershell
python .\berryfine-goods-skill\scripts\catalog_gate.py --template <template.xlsx> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx" --ledger <client-inventory.csv> --intake-id <intake-id> --catalog-payload <catalog-payload.json> --builder-verification <catalog-builder-verification.json> --output <catalog-verification.json>
python .\berryfine-goods-skill\scripts\delivery_gate.py --workflow full-intake --client-folder <client-folder> --manifest <intake-manifest.json> --ledger <client-inventory.csv> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --preflight-lock <preflight-lock.json> --catalog-verification <catalog-verification.json>
python .\berryfine-goods-skill\scripts\bfg.py audit --client-folder <client-folder> --records <iteration-record-folder> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --client-name "<Client Folder Name>" --intake-id <intake-id>
```

Do not report the run complete unless all three commands return `PASS`. `catalog_gate.py` validates the catalog and Exceptions workbook contract, `delivery_gate.py` performs final full-intake delivery verification, and `bfg.py audit` performs the final aggregate artifact and workflow-status audit without replacing the delivery gate. File presence alone is not completion. The catalog verification must reconcile retained values and formulas through I, plus retained J when it already existed; require the hash-bound Excel materialized-format snapshot for retained appearance; reconcile only current-intake item IDs and actions; and check new-row location, wrapped history, column I, direct fills, formula errors, column J width, filter coverage, print area, and Exceptions coverage. Without Excel builder evidence, it compares normalized retained styles directly. The delivery gate must recheck the verification hashes, confirmed preflight bindings, exact categorized file set, and every categorized photo hash. Missing, misnamed, invalid, unchanged-template, partial, stale, or content-mismatched artifacts are blockers. Audit JSON, the ledger, and categorized photos do not substitute for either required workbook.

The reference exact-format builder is `berryfine-goods-skill/scripts/catalog_builder.ps1`. It requires Windows, PowerShell, desktop Microsoft Excel, and registered Excel COM automation. Another builder may be used only if it produces the same untouched-template, retained-value/formula/displayed-format, conditional-format-scope, column D/H/I/J, direct-fill, filter, print-area, formula-error, Exceptions, catalog-verification, and delivery-verification contract. A non-Excel implementation cannot claim exact compatibility merely because it creates an `.xlsx` file. Human visual inspection remains recommended and does not replace deterministic gates.
