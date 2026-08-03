# Berryfine Goods Skill

Version 2.2.1 standardizes Python 3.11 as the minimum, tests Python 3.11 and 3.14 in CI, documents workflow-specific audit and delivery sequences, makes the Windows/PowerShell/desktop-Excel requirement for the exact workbook builder explicit, and improves non-destructive doctor diagnostics. It preserves version 2.2.0's deterministic exact-duplicate resolution without changing disposition thresholds, human approval requirements, listing authorization, or the prohibition on marketplace publication.

The release also supports bulk, unnumbered photo intake with real image-signature and hash validation, blind-review provenance, deterministic grouping application, structured completed-sale evidence, automatic catalog/Exceptions payloads, reusable Excel automation, immutable audit seals, outcome tracking, and a single workflow audit command. Warehouse tracking is intentionally outside this repository and remains a separate future system.

Before a real intake, run:

```powershell
python .\berryfine-goods-skill\scripts\bfg.py doctor
```

For a normal full intake, run these commands from the repository root after authoring the workbooks and categorized photo set:

The examples are command templates: replace every `<...>` placeholder with the real value and quote concrete paths that contain spaces.

```powershell
python .\berryfine-goods-skill\scripts\catalog_gate.py --template <template.xlsx> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx" --ledger <client-inventory.csv> --intake-id <intake-id> --catalog-payload <catalog-payload.json> --builder-verification <catalog-builder-verification.json> --output <catalog-verification.json>
python .\berryfine-goods-skill\scripts\delivery_gate.py --workflow full-intake --client-folder <client-folder> --manifest <intake-manifest.json> --ledger <client-inventory.csv> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --preflight-lock <preflight-lock.json> --catalog-verification <catalog-verification.json>
python .\berryfine-goods-skill\scripts\bfg.py audit --client-folder <client-folder> --records <iteration-record-folder> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --client-name "<Client Folder Name>" --intake-id <intake-id>
```

`catalog_gate.py` validates the catalog and Exceptions workbook contract. `delivery_gate.py` performs final full-intake delivery verification. `bfg.py audit` performs the final aggregate artifact and workflow-status audit and does not replace `delivery_gate.py`. A full intake is incomplete unless all applicable commands return `PASS`; file presence alone is not completion.

For a legacy catalog refresh, run the repository-root sequence below. `legacy-audit` validates retained source evidence and policy-only refresh conditions; the legacy delivery gate performs final delivery verification. Do not run a legacy refresh through the normal full-intake audit requirements.

```powershell
python .\berryfine-goods-skill\scripts\catalog_gate.py --template <template.xlsx> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx" --ledger <client-inventory.csv> --intake-id <new-intake-id> --catalog-payload <catalog-payload.json> --builder-verification <catalog-builder-verification.json> --output <catalog-verification.json>
python .\berryfine-goods-skill\scripts\bfg.py legacy-audit --manifest <source-manifest.json> --preflight <preflight-lock.json> --ledger <client-inventory.csv> --intake-id <new-intake-id> --catalog "<client-folder>\<Client Folder Name> New Catalog.xlsx" --exceptions "<client-folder>\<Client Folder Name> Exceptions.xlsx"
python .\berryfine-goods-skill\scripts\delivery_gate.py --workflow legacy-catalog-refresh --client-folder <client-folder> --manifest <source-manifest.json> --ledger <client-inventory.csv> --categorized "<client-folder>\Categorized Inventory <YYYY-MM-DD>" --categorized-verification <categorized-verification.json> --intake-id <new-intake-id> --preflight-lock <preflight-lock.json> --catalog-verification <catalog-verification.json>
```

Both applicable legacy checks must return `PASS`. A legacy refresh retains source evidence and does not recreate current-intake photo-quality, blind forward/reverse review, grouping research, or completed-sale research artifacts. No legacy-refresh command authorizes a listing.

Berryfine Goods Skill turns one item or hundreds of client inventory photos into
an evidence-backed consignment catalog. It supports flat camera rolls and
folder-per-item intake, automated photo grouping, exact-item identification,
completed-sale research, value estimates, client catalog creation, categorized
photo folders, exceptions reporting, and a persistent inventory ledger per
client. It produces drafts and review artifacts; it never publishes a listing.

## Recommended actions

The sortable `RECOMMENDED ACTION` column uses four distinct decisions:

| Supported gross resale value or issue | Action | Result |
|---|---|---|
| $50 or more | `SELL` | Unfilled new catalog row |
| $40 through $49.99 | `CONFIRM DONATION` | Yellow row; draft remains pending until BFG confirms |
| Below $40 | `DONATE` | Yellow row |
| Identification, authenticity, safety, policy, grouping, or valuation uncertainty | `REVIEW` | Yellow row with the unresolved issue documented |

`CONFIRM DONATION` prevents a borderline item from being silently donated. A
named BFG reviewer must confirm it before the ledger can transition to `DONATE`.
If BFG instead chooses `SELL`, the record keeps the decision, confirmer,
timestamp, and explicit below-$50 override reason. Planned testing is tracked
separately and does not cause `REVIEW` by itself.

## Catalog and audit safeguards

- Preserve all existing rows, values, formulas, and displayed colors; blue still
  means sold.
- Preserve every pre-populated `LOCATION`; write `Storage` only on newly added
  rows.
- Put detailed identification, condition, evidence, pricing, and testing notes
  in column H `HISTORY/INFO`; preserve column I; use column J for the four exact
  actions above.
- Preserve retained column J values and styles when the template already has
  `RECOMMENDED ACTION`; only a newly introduced J starts blank historically.
- Leave new `SELL` rows unfilled. Apply solid yellow `#FFFF00` across A:J to new
  `DONATE`, `REVIEW`, and `CONFIRM DONATION` rows.
- Require a confirmed, hash-bound preflight lock before manifest creation.
- Resolve exact duplicate hashes before confirmation, retain the non-copy-style
  filename when available, record every redundant path, and invalidate the run
  if the duplicate set changes.
- Hash every source photo, bind every sequence-review pass to the exact photo
  set, reject path traversal, and verify categorized copies byte-for-byte.
- Run the deterministic catalog gate before the delivery gate. Delivery fails
  if the catalog, Exceptions workbook, ledger, confirmation lock, verification
  record, or categorized photos are missing, stale, renamed, or inconsistent.
  The catalog gate also checks retained values and formulas, the hash-bound
  Excel materialized-format snapshot, current-intake item/action reconciliation,
  wrapping, fills, column J width, filter coverage, print area, formula errors,
  and Exceptions coverage. Without Excel builder evidence it compares normalized
  retained styles directly.

Client-facing outputs stay in the main client folder as `<Client Name> New
Catalog.xlsx`, `<Client Name> Exceptions.xlsx`, and `Categorized Inventory
YYYY-MM-DD`. Internal audit history stays at `C:\BFG Bulk Import Records\<Client
Name>\<intake-id>`, while one client-level `client-inventory.csv` spans catalog
iterations.

## Operating workflow

1. Inspect the selected photo folder, catalog template, prior-run exclusions,
   duplicate resolution, client name, intake ID, and proposed output paths
   without changing source files.
2. Create a PENDING preflight lock, state all catalog rules, and obtain explicit
   confirmation from the user. Record the real confirming identity.
3. Create the photo manifest. Any photo, template, exclusion, path, or rules
   change after confirmation stops the run and requires a new preflight.
4. Group photos with independent forward, reverse, adjudication, and cohesion
   passes for flat camera rolls; folder intake follows the same cohesion checks.
5. Identify items, research completed sales, value them, and update the canonical
   client ledger. Every AI-created listing remains human-review `PENDING`.
6. Author the new catalog and Exceptions workbook from the supplied template,
   then run `catalog_gate.py` to verify content and formatting deterministically.
7. Copy assigned photos into the dated categorized inventory and verify every
   copy against its source hash.
8. Run `delivery_gate.py`. Report completion only after it returns `PASS`.

Requirements are Codex, Git, filesystem access to the intake and records roots,
and Python 3.11 or newer. The reference exact-format builder at
`berryfine-goods-skill/scripts/catalog_builder.ps1` requires Windows,
PowerShell, desktop Microsoft Excel, and registered Excel COM automation.
Another builder may be used only when it produces the same workbook contract
and passes `catalog_gate.py` and `delivery_gate.py`; creating an `.xlsx` alone
does not establish exact compatibility. Human visual inspection remains
recommended and does not replace deterministic gates.

`bfg.py doctor` reports core Python workflow readiness in `status` and
`core_workflow_ready`. This is a clarified v2.2.1 status contract: exact Excel
builder readiness is reported separately in `exact_excel_builder_ready`, along
with Windows, PowerShell, and non-destructive desktop Excel detection results.

## Install

Clone the public repository on the target PC:

```powershell
git clone https://github.com/charlessalvo1-del/berryfine-goods-skill.git
$skillDestination = Join-Path $env:USERPROFILE ".codex\skills\berryfine-goods-skill"
New-Item -ItemType Directory -Force $skillDestination | Out-Null
Copy-Item -Recurse -Force `
  .\berryfine-goods-skill\berryfine-goods-skill\* `
  $skillDestination
```

To update an existing clone, run `git -C .\berryfine-goods-skill pull --ff-only`, verify `Get-Content .\berryfine-goods-skill\VERSION` reports the intended version, then repeat the destination-directory and `Copy-Item` commands above. These commands copy the Skill contents into the installed Skill directory instead of nesting another Skill folder inside it.

Restart Codex, then invoke the skill with `$berryfine-goods-skill`. The
human-facing name is **Berryfine Goods Skill**.

## Contents

- `berryfine-goods-skill/SKILL.md` — workflow and blocking safety rules
- `berryfine-goods-skill/agents/openai.yaml` — Codex display metadata
- `berryfine-goods-skill/references/` — intake, schema, and valuation contracts
- `berryfine-goods-skill/scripts/` — preflight, manifest, grouping, ledger,
  workbook-verification, photo-organization, and delivery gates
- `tests/` — regression coverage for policy, integrity, and delivery safeguards
