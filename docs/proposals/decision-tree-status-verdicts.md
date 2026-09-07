# Decision tree status verdicts

Design, 2026-09-07. Not built.

## The problem

A decision tree leaf today ends in one of two kinds, `recommendation` or
`alert`, and the negative branches end in `action_type: no_action`. A
`no_action` leaf writes no row. The only record is an evaluation trace with
status `clear`, which no user screen reads.

So on screen these three cases look the same:

- The tree ran and found nothing wrong.
- The tree was excluded by targeting (crop, country, soil).
- The tree never ran.

A user cannot be told "this block was checked and it is fine".

## Decisions taken

Agreed with Mohamed on 2026-09-07.

1. A leaf has four kinds: `alert`, `recommendation`, `status`, `no_action`.
2. `alert`, `recommendation` and `status` leaves carry a message, a color and
   an evaluation time. `severity` stays on `alert` and `recommendation` only.
3. The status list is fixed in the platform. Tenants cannot add codes or change
   colors.
4. All four kinds write a verdict row. A missing verdict row means the tree did
   not run for that block.
5. Verdict history is kept. A replay over a date range comes later, so the
   storage must answer "what was this block on date D".
6. Verdicts are written per block and per grid cell, in one table.
7. Block health becomes the worst current verdict. The alert-counting rule in
   the `ma-health` branch becomes the fallback for a block with no verdict.
8. The map is out of scope. It is a new map, not the Farm Management map.
9. The shipped trees are not edited in this change. They are rewritten later,
   as a separate piece of work.
10. Scope of this change: backend, the tree authoring screen, and the health
    switch behind the existing flag.
11. Build on the `ma-health` branch, not on `main`.
12. A verdict does not expire. It stays current until the next sweep replaces
    it.
13. The Action Center does not show verdicts. A status is not a work item.

## The status list

Five codes. Label and color ship with the platform, in English and Arabic.

| Code | Rank | Color | English label |
| --- | --- | --- | --- |
| `na` | 0 | `#9AA0A6` | Not applicable |
| `very_good` | 1 | `#1B873F` | Very good |
| `good` | 2 | `#6FBF4B` | Good |
| `issue` | 3 | `#E8A33D` | Issue |
| `alert` | 4 | `#D64545` | Alert |

Rank is the order used when one block has several verdicts. The highest rank
wins, so `na` never wins over a real answer.

The frontend must read this list from an endpoint, not hold its own copy. A
frontend copy of a backend list has drifted before.

## What each leaf kind writes

| Leaf kind | Verdict status | Other rows |
| --- | --- | --- |
| `alert` | `alert` | one `alerts` row, as today |
| `recommendation` | `issue` | one `recommendations` row, as today |
| `status` | the code the author picked | none |
| `no_action` | `na` | none |

A `status` leaf may pick any of the five codes, including `issue` and `alert`.
It colors the block and shows a message. It opens no work item.

## Leaf format

Before:

```yaml
leaf_no_risk:
  outcome:
    action_type: no_action
    text_en: "No action needed."
```

After:

```yaml
leaf_no_risk:
  outcome:
    kind: status
    status: good
    text_en: "Checked. No anthracnose risk in the current weather window."
    text_ar: "..."
```

Compatibility. A leaf with no `kind` and `action_type: no_action` compiles as
`kind: no_action`. A leaf with no `kind` and any other `action_type` keeps
compiling as `kind: recommendation`. No stored tree breaks.

The loader rejects an unknown `kind` and an unknown `status` when the tree is
published. An unknown condition operator once compiled and ran without showing
any error for months, so this check has to fail hard and have a named test.

## Storage

New tenant table. The migration number is taken at build time from
`origin/main`, not now. This checkout is 391 commits behind and its highest
tenant migration is 0072, while production is past 0089.

```
decision_tree_block_verdicts
  id                  uuid pk
  farm_id             uuid not null
  block_id            uuid not null
  cell_id             uuid null          -- null = block scoped
  tree_id             uuid not null
  tree_code           text not null
  tree_version        int  not null
  leaf_node_id        text not null
  kind                text not null      -- alert|recommendation|status|no_action
  status_code         text not null      -- very_good|good|issue|alert|na
  severity            text null          -- alert and recommendation only
  text_en             text not null
  text_ar             text null
  run_id              uuid null          -- the run that opened the interval
  last_run_id         uuid null          -- the run that last confirmed it
  valid_from          timestamptz not null
  valid_to            timestamptz null   -- null = current
  last_evaluated_at   timestamptz not null
  alert_id            uuid null
  recommendation_id   uuid null
  created_at, updated_at
```

One row per interval, not one row per night. A sweep that returns the same
status touches `last_evaluated_at`, `last_run_id` and nothing else. A sweep
that returns a different status closes the open row and inserts a new one.

Measured shape on production today: 72 active blocks, 8 trees each. A row per
evaluation would add about 576 rows a night. Interval rows add a row only on a
real change.

Reading a date:

```sql
WHERE valid_from <= :at AND (valid_to IS NULL OR valid_to > :at)
```

Uniqueness. Only one open row per block, cell and tree:

```sql
CREATE UNIQUE INDEX uq_dt_verdicts_open
  ON decision_tree_block_verdicts (block_id, COALESCE(cell_id, uuid_nil()), tree_id)
  WHERE valid_to IS NULL;
```

`COALESCE` is needed. Postgres treats two NULL `cell_id` values as different,
so a plain index on a nullable column would not constrain block-scoped rows at
all.

Caution. `op.create_check_constraint` doubles a full constraint name. Pass the
suffix only. Every CHECK on `blocks` in production is live as
`ck_blocks_ck_blocks_*` because of this.

## Write path

In `recommendations/service.py`, where the walk result is handled now:

1. The walk reaches a leaf. Build the verdict from the leaf kind and status.
2. Look up the open verdict for that block, cell and tree.
3. If `status_code`, `leaf_node_id`, `text_en` and `text_ar` all match, update
   `last_evaluated_at` and `last_run_id`. Write nothing else.
4. Otherwise set `valid_to` on the open row and insert a new one.
5. Then open the alert or recommendation as the code does today, and store its
   id on the verdict row.

Closing a verdict. A verdict must be closed, not left open, when:

- Targeting excludes the tree from the block, for example after a crop change.
- The tree is archived or deactivated.
- The block is deactivated.

Without this a block keeps a green verdict from a tree that no longer applies.

A cell tree writes one row per cell. It does not also write a block row. A
block row plus its own cell rows would count the same finding twice, which is
how `cell_critical_share` became unreachable in the health work.

## Read API

- `GET /api/v1/decision-trees/status-codes` — the five codes with label and
  color, English and Arabic.
- `GET /api/v1/blocks/{block_id}/verdicts?at=` — the block's current verdicts,
  one per tree, plus cell rows. `at` replays a date.
- `GET /api/v1/farms/{farm_id}/verdicts?at=` — one statement for the whole
  farm, one row per block and cell. The new map reads this.

The farm read must be one statement. The Farm Console block loop is already
N+1 on indices and alerts; a per-block read here would add 72 more round trips
on the production farm.

`at` may arrive without a time zone. Stamp a separate UTC value for the
comparison and echo back what the caller sent. A naive datetime subtracted from
a `timestamptz` raises `TypeError`.

## Block health

Health becomes the worst current verdict for the block:

| Worst verdict | Health |
| --- | --- |
| `alert` | Critical |
| `issue` | Warning |
| `good`, `very_good` | Healthy |
| `na`, or no verdict | Unknown |

This runs behind `health_definition_enabled`, the flag the `ma-health` branch
already added. Freshness still gates the healthy answer only. A block whose
newest `last_evaluated_at` is older than `stale_after_hours` reads Unknown, and
an `alert` verdict reads Critical whatever its age.

`cell_critical_share` gets a better source. It can count cell verdicts directly
instead of reading alert child rows.

This work is built on the `ma-health` branch. That work is 8 commits in a local
worktree at `C:/Users/mosoliman/projects/ma-health`, branch
`feat/health-rule-single-source`, not pushed. It edits the same two files,
`app/shared/health.py` and `app/shared/health_evidence.py`, so branching off
`main` would conflict.

## Seed trees

Not in this change. Mohamed will rewrite the trees later.

The size of that later work, counted on `origin/main` on 2026-09-07: 63
`no_action` leaves across 33 seed files.

- 22 `T_` mango trees: 39 leaves
- date palm, 3 files: 6 leaves
- potato, 6 files: 12 leaves
- other, 2 files: 6 leaves

All 33 are seed files in `backend/app/modules/recommendations/seeds`. The `T_`
trees are seeds too, added by PR #638. No data migration is needed for them.

Note. A tenant can also author a tree through the screen, and those live only
as rows in `public.decision_trees` with a non-null `tenant_id`. Count them with
one query before the rewrite, because a seed edit does not reach them.

Warning. Until the trees are rewritten, every healthy path still ends in
`no_action`, which writes `na`. Under the health rule in this document, `na`
reads Unknown. Turning `health_definition_enabled` on before the rewrite would
move all 72 production blocks to Unknown. The order is: build the capability,
rewrite the trees, then turn the flag on.

## Authoring screen

`frontend/src/modules/decisionTrees`:

- `components/NodeDetailsPanel.tsx` — a leaf gets a kind selector with four
  options. Picking `status` shows the status picker with a color swatch and the
  message fields. Picking `alert` or `recommendation` keeps severity. Picking
  `no_action` hides message, color and severity.
- `lib/treeEdit.ts`, `lib/treeStructure.ts` — validation for the new kinds.
- `lib/treeTemplates.ts` — a status leaf template.
- The status list and its colors come from the new endpoint.

The explain view and the traces page say `clear` today. They show the status
code and its color instead.

## Impact analysis

Read on the `ma-health` branch, rebased on `origin/main` on 2026-09-07.

### Backend, changed by this work

| File | What changes | Phase |
| --- | --- | --- |
| `recommendations/engine.py` | `TreeOutcome` accepts four kinds and a status code. `action_type` becomes optional for `status` and `no_action` leaves. | 1 |
| `recommendations/loader.py` | Publish-time validation accepts four kinds, rejects an unknown status, and stops requiring `action_type` on a status leaf. | 1 |
| `recommendations/schemas.py` | New `LeafKind` and `StatusCode` types, and the status catalog response. | 1 |
| `recommendations/status_codes.py` | New file. The five codes with rank, color, English and Arabic label. | 1 |
| `recommendations/models.py`, new migration | The verdict table. | 2 |
| `recommendations/repository.py` | Open, confirm and close a verdict. | 3 |
| `recommendations/service.py` | Writes a verdict at every leaf. Three places read `action_type != "no_action"` to mean "something happened": lines 1020, 1128 and 1939. | 3 |
| `recommendations/router.py` | Three read endpoints. | 4 |
| `shared/health.py`, `shared/health_definition.py`, `shared/health_evidence.py` | Health reads verdicts. `HealthInputs` gains the worst verdict; the four trace counters stay for coverage. | 6 |
| `farms/blocks_summary_router.py`, `insights/service.py` | Both health callers pass the new input. | 6 |

### Backend, checked and not changed

- Evaluation traces keep their four statuses, `fired`, `clear`, `skipped`,
  `error`. A `status` leaf records `clear` and carries its status code in the
  trace outcome. This avoids changing the CHECK constraint in tenant migration
  0062 and keeps the health coverage counters working.
- `action_center/service.py` line 68 and `notifications/presentation.py` lines
  52 and 62 hold a label for `no_action`. Verdicts do not reach either screen,
  so the labels stay.
- `observer/lineage.py` reads a snapshot for kind `recommendation` or `alert`.
  A verdict has no snapshot of its own; it points at the alert or
  recommendation row when it has one.
- `timeline/service.py` and `reports/schemas.py` use the words `alert` and
  `recommendation` for their own item kinds. They are not leaf kinds and do not
  move.
- `field_flags/schemas.py` has a close reason called `no_action_needed`. It is
  unrelated.

### Frontend, changed by this work

| File | What changes | Phase |
| --- | --- | --- |
| `api/recommendations.ts`, `api/decisionTrees.ts` | The new kinds, the status codes and the catalog call. | 4 |
| `modules/decisionTrees/components/NodeDetailsPanel.tsx` | The leaf kind selector and the status picker. | 5 |
| `modules/decisionTrees/lib/treeStructure.ts` (lines 86, 95, 250), `lib/treeTemplates.ts` | New leaf templates. They write `action_type: no_action` today. | 5 |
| `modules/decisionTrees/layout/treeLayout.ts` line 147 | It dims a leaf by `action_type === "no_action"`. It has to dim by kind. | 5 |
| `modules/labs/mapnext/DockConditionsView.tsx` lines 18 and 123 | This is the screen that shows the problem today: a `clear` tree gets a green dot and the words "No action required". It shows the status and its message instead. | 7 |
| `modules/decisionTrees/pages/DecisionTreeTracesPage.tsx` | The trace row shows the status code. | 7 |
| `lib/actionTypes.ts` | Only its comment. `no_action` still never reaches the queue. | 7 |

### Translation files touched

`decisionTrees`, `farmConsole`, `recommendations` in English and Arabic. Five
status labels, one set, read from the endpoint and not hard-coded in the
frontend.

## Where it stands, 2026-09-07

Phases 1 to 7 are written on `feat/health-rule-single-source`, commits
`ec8d3464`, `c628bc2a`, `cb651c03`, `bc322abf`, `cbceba56`, `e770b577`,
`e2090428`. Nothing is pushed and `health_definition_enabled` is still off.

Left: rewrite the shipped trees (63 no-action leaves in 33 files), then
measure on production, then turn the flag on.

## Suggested phases

1. Status catalog in the backend, loader accepts four kinds, compatibility for
   stored trees. Unit tests.
2. Migration and the verdict table.
3. Engine and service write path, including closing a verdict when a tree stops
   applying.
4. Read API, three endpoints.
5. Authoring screen.
6. Health resolver reads verdicts, behind the existing flag, flag left off.
7. Explain and traces show the status.

Then, as separate work: rewrite the trees, then turn the flag on.

Phases 1 to 5 change no number already on screen. Before the flag goes on,
measure it on production the way the health work did: 72 blocks, count how many
change class.

## Open questions

- How many tenant-authored trees exist in production. One query answers it:
  `SELECT count(*) FROM public.decision_trees WHERE tenant_id IS NOT NULL`.
