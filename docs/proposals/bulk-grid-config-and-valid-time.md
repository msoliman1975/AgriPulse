# Bulk grid config at farm level + grid valid time

**Status:** DELIVERED (2026-08-04). PR 1 `#351` and PR 2 `#353` are merged to `main`;
PR 3 is this branch. Kept as the design record — the reasoning below is why the
code looks the way it does, not a to-do list.
**Supersedes:** the rev-2 UX mock (`Bulk grid & anomaly config`, artifact `64e752d7`).
**Related:** `farm-block-config-model.md` (the template→apply→lock machine this reuses),
`grid-aggregates-retention.md`.

### What changed against the plan

* **§2.2 was reproduced, not just derived.** The regression test landed red
  first: 3 of 5 assertions failed on `main`, exactly as predicted. It is a real
  bug that shipped, now fixed by migration `0054`.
* **PR 2 could not be independent of PR 1.** Alembic revisions are linear, so
  `0054` needs `0053` in the chain. The two were stacked and merged in order.
* **A same-class bug turned up outside the listed sites.** The reports
  zone-anomaly query paired configs to aggregates on `(block_id, product_id)` —
  columns that survive a rezone — so it could score a retired geometry's cells
  against the current threshold. Fixed in PR 2.
* **§A5's cleanup task shipped in PR 2** rather than waiting, and gained a
  scheduled sweep in PR 3 alongside `grid.settle_rezones_sweep`. Step 2 is
  **polled, not signalled**: nothing knows when a backfill has finished, and a
  chord over thousands of scene jobs loses one result and never completes.
* **The confirmation is narrower than the mock's.** It is demanded only when
  live geometry would be retired — never for a `create`. A confirmation asked
  for harmless actions is one operators learn to type past.
* **§B2's extra capability is defence-in-depth, not a live distinction.** Every
  role granting `farm.manage_config` currently also grants
  `imagery.subscription.manage`; a lock-step test pins that.
* **One Save, two Applies.** The mock gave section ① its own Save. The template
  is a single row carrying both columns, so two Saves writing the same row would
  be the confusing option. The two *Apply* actions stay separate, which is where
  the blast-radius difference actually lives.

---

## 1. What this delivers

Configure **grid cell size** and **anomaly z-threshold** for every block of a farm in
one pass, as a fourth category in the existing **Block defaults** panel — instead of
today's one-block-at-a-time `BlockGridConfigCard`. On a 36-block farm that is 36 manual
round trips reduced to one reviewed apply.

Second, it fixes the thing that makes bulk rezoning dangerous: **grid configs have no
valid time**, so a rezone silently orphans every prior observation. Today that's a
per-block foot-gun. With a bulk button it becomes a farm-wide one.

---

## 2. Findings from the code (2026-07-31)

These change the plan versus what the mock assumed. All line references are current `main`.

### 2.1 The mock's guardrail is incomplete — preview must be server-side

`grid/geometry.py:47 validate_cell_size` enforces **four** rules; the mock's JS
implements two:

| # | Rule | In mock? |
|---|------|----------|
| 1 | `cell_size >= native_pixel_m` | ✅ |
| 2 | **integer multiple of native pixel** | ❌ **missing** |
| 3 | `>= 4` native pixels per cell | ✅ |
| 4 | **`<= 5000` cells for *this block's* area** | ❌ **missing** |

Rule 2 means 25 m on Sentinel-2 (10 m) **fails** — the mock shows it passing. Rule 4
depends on each block's own `area_m2`, so it cannot be evaluated from a per-product
table at all: two blocks on the same product can disagree.

**Consequence:** the preview cannot be computed client-side from per-product floors.
It needs a **batch server endpoint** running the real `validate_cell_size` per
`(block, product)`. The mock's per-product floor strip stays as a *hint* only.

### 2.2 Rezone breaks reads today — a confirmed latent defect

Read paths split into two groups:

- **Config-joined** (filter `cfg.retired_at IS NULL`): `list_cell_means`
  (`repository.py:527`), `list_cells_with_values` (`:584`), `list_active_cells` (`:303`),
  `list_active_configs*` (`:425`, `:452`), plus `reports/service.py:903,932` and
  `recommendations/repository.py:987`.
- **Not config-joined** (query `block_grid_aggregates` raw):
  `get_latest_scene_time` (`repository.py:384`) and `list_observed_indices` (`:465`).

The second group sees **orphaned rows from retired grids**. So immediately after a
rezone:

1. `get_latest_scene_time` returns the last scene time of the **old** grid.
2. `get_cells_with_values` resolves `at` to that time, then LEFT JOINs the **new**
   cells → every `mean` is NULL → **heatmap renders all "no data"**.
3. `detect_block_anomalies` uses the same `at`, then `list_cell_means` INNER JOINs the
   new cells → 0 rows → detector's `min_cells` guard returns None → **anomaly detection
   is silently dead for that block** until the next scene lands.

Read from the code, not reproduced against a live DB — worth a 10-minute confirmation
on the dev tenant before building on it. If it holds, it is a bug on `main` today,
independent of this feature.

### 2.3 The expensive-looking fix is actually cheap

`grid_cells.grid_config_id` already exists, and every config-joined read path *already*
joins `grid_cells → grid_configs`. So **each aggregate row is already attributable to
the config that produced it**, through `cell_id`.

That means valid time needs **no change to `block_grid_aggregates`** — no column added
to a compressed TimescaleDB hypertable, no chunk rewrite, no decompress/recompress
dance. It is a **columns-on-`grid_configs` + read-path-predicate** change.

This is the single most important finding in this document. It moves the valid-time
work from "scary multi-week hypertable migration" to "one small migration plus a
careful sweep of 9 query sites".

### 2.4 Storage note

Aggregates are keyed `(time, block_id, cell_id, index_code, product_id)`. Old and new
grids have **different `cell_id`s**, so a rezone + backfill *adds* rows beside the
orphans rather than replacing them. Rezoning a block roughly doubles its cell-aggregate
footprint. Compression (30 d) softens it; the retention scaffold (G-8,
`grid-aggregates-retention.md`) is the lever if it matters.

---

## 3. Track A — Grid valid time

**Goal:** a grid config governs a *range of scene times*, not "whatever is current".
Rezoning stops destroying the readability of history.

Keep `retired_at` as what it honestly is — **transaction time**, the audit record of
when an operator changed their mind. Add **valid time** alongside it. Do not overload
one column with both; that conflation is the original defect.

### A1 — Schema (tenant migration `0054` — PR 2)

```sql
ALTER TABLE grid_configs
  ADD COLUMN effective_from TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
  ADD COLUMN effective_to   TIMESTAMPTZ NULL,          -- NULL = open-ended
  ADD COLUMN superseded_at  TIMESTAMPTZ NULL;          -- governs nothing; rows pending cleanup
```

`superseded_at` is what makes "rewrite history" (§A4) expressible. A superseded config
has been fully replaced by another geometry over its whole range: it governs no scene
time at all, but its rows are still physically present until the cleanup task drops
them. Without it, a config claiming `-infinity` would always collide with the one it
replaces.

- Backfill: every existing **active** config gets `effective_from = '-infinity'`,
  `effective_to = NULL` — i.e. "this geometry governs all of history", which is exactly
  today's de-facto behaviour. Existing **retired** configs get
  `effective_to = retired_at` so their aggregates become readable again for their own
  period. Retired configs are already invisible, so this can only add data back.
- Non-overlap guard, replacing reliance on the partial unique index:

```sql
ALTER TABLE grid_configs ADD CONSTRAINT ex_grid_configs_no_overlap
  EXCLUDE USING gist (
    block_id   WITH =,
    product_id WITH =,
    tstzrange(effective_from, effective_to) WITH &&
  ) WHERE (deleted_at IS NULL AND superseded_at IS NULL);
```

  Requires `btree_gist`. Keep `uq_grid_configs_block_product_active` as-is — it still
  correctly means "one *current* config per (block, product)".
- Downgrade needs convention-doubled constraint names (see the Alembic/asyncpg memo).

### A2 — Read-path migration (9 sites)

Replace `AND cfg.retired_at IS NULL` with a scene-time containment predicate:

```sql
AND tstzrange(cfg.effective_from, cfg.effective_to) @> obs.time
```

For the two paths that don't join configs (`get_latest_scene_time`,
`list_observed_indices`), **add the join** — that is what fixes §2.2. Both are hot
(the sweep calls them per block), so check the plan; the GIST exclusion index supports
the range lookup, and `grid_cells(grid_config_id)` is already indexed.

Note `list_cells_with_values` (`:581`) needs care: it LEFT JOINs observations so
no-data cells still render, and its `at` bind is pinned to `timestamptz` for asyncpg
(the #175 fix). Don't regress either property. `@>` against a NULL `at` must not
silently drop rows — the resolved-`at` path is the one to exercise in tests.

### A3 — Write path

`imagery/tasks.py:1056` calls `list_active_cells(block_id, product_id)` — "the current
grid". It must become "the grid governing **this scene's** time", or a late-arriving
2025 scene gets gridded on 2026 geometry. Add
`list_cells_for_scene(block_id, product_id, at)` and switch the caller.

This is also what makes backfill honest: `grid.backfill_block` re-enqueues
`compute_indices` per scene, and each will now land on the geometry that governs that
scene's date.

### A4 — Rezone semantics: "rewrite history" is the default *(decided)*

A rezone means the new geometry becomes canonical for **all** of history — one grid per
(block, product), past and future, so trends are never compared across a geometry
boundary. This matches what the per-block card does today, so nobody's mental model
changes.

**Implement it as recompute-then-swap, not swap-then-recompute.** The naive form —
close the old config, queue the backfill — has two defects: the new config claiming
`-infinity` overlaps the config it replaces (the §A1 constraint rejects it), and it
opens a window where history is deleted but not yet regenerated. An interrupted or
failed backfill in that window is permanent data loss.

The cutover is therefore two-step:

1. **On apply.** Insert the new config with `effective_from = now()`; set the old
   config's `effective_to = now()`. Both are valid, non-overlapping. The new geometry
   governs new scenes; **history stays readable on the old geometry throughout**.
   Enqueue the backfill.
2. **On backfill completion.** Once recomputed rows exist for the covered scene range,
   extend the new config's `effective_from` back to `-infinity`, stamp the old config
   `superseded_at = now()`, and hand its aggregate rows to the cleanup task.

Net effect is exactly "rewrite history" — one geometry over the whole record — reached
without a blind window, and safely abandonable at step 1 if the backfill dies.

**Partial backfill is the interesting case.** If the budget (§B4) doesn't cover every
scene, step 2 can only pull `effective_from` back as far as the oldest recomputed
scene. Older scenes keep their old config, which stays live rather than superseded.
The farm then genuinely has two geometries across its history — the UI must say so
rather than implying a clean rewrite. This is the honest version of the mock's
"stranded scenes" warning.

Cleanup of superseded rows runs as a separate task, not inline with apply: deleting
from a compressed hypertable is slow and must not block the request.

### A5 — Cross-cutting

- **Purge registry** (`shared/purge/registry.py`): new columns don't add tables, but the
  CI "no orphans" guard should be re-run; if the plan later adds a farm-template table
  it **must** be registered or CI fails.
- **Retention** (G-8): a retention policy now has a defensible rule — drop aggregates
  whose governing config was superseded more than N days ago. The §A4 cleanup task is
  the same mechanism; retention is just a longer timer on it.
- **Cleanup task** (new): drops aggregate rows belonging to superseded configs, in
  chunk-friendly batches. Must tolerate compressed chunks and be safely re-runnable.

### A6 — Tests

- Unit: range containment, non-overlap constraint rejects an overlapping insert,
  `-infinity` backfill semantics.
- Integration (testcontainers, real Postgres + Timescale): rezone in "from now on" mode
  → old scene still returns cell values on old geometry, new scene on new; rezone in
  "rewrite" mode + backfill → old scenes reappear on new geometry.
- **Regression for §2.2**: rezone, then assert `get_latest_scene_time` +
  `get_cells_with_values` agree and the heatmap is not all-null. This test should fail
  on current `main` — if it passes, §2.2 is wrong and this section needs revisiting.

---

## 4. Track B — Bulk grid config

### B1 — Farm template storage (tenant migration `0053` — PR 1)

Single-row template, matching the **Irrigation** category's shape rather than the
multi-row Subscriptions one (the mock has exactly one cell size + one z per farm):

```sql
ALTER TABLE farms
  ADD COLUMN default_grid_cell_size_m     NUMERIC(6,2) NULL,   -- NULL = no template
  ADD COLUMN default_anomaly_z_threshold  NUMERIC(4,2) NULL,
  ADD COLUMN grid_locked                  BOOLEAN NOT NULL DEFAULT FALSE;
```

Wire into `config_template.py`: extend `Category` to `"grid"` and add
`_LOCK_COLUMN["grid"] = "grid_locked"`. Lock guard goes on the block-level
`PUT /blocks/{id}/grid-configs/{product}`.

**Design note — the farm template is not a resolution tier.** The z-threshold already
resolves block → tenant → platform (`grid.anomaly_z_threshold`, G-3). The farm template
does **not** insert a fourth tier; consistent with the whole config model, it is
copy-on-apply and writes into `grid_configs.anomaly_z_threshold`. Applying it therefore
*detaches* those blocks from the tenant default permanently — so the apply request needs
an explicit `clear_override` mode meaning "set NULL, go back to inheriting". Without
that, bulk apply is a one-way door.

### B2 — Batch preview endpoint

```
POST /api/v1/farms/{farm_id}/config/grid/apply-preview
POST /api/v1/farms/{farm_id}/config/grid/apply
GET|PUT /api/v1/farms/{farm_id}/config/grid/template
```

Preview returns **one row per `(block, active imagery subscription)`** — the same key as
`grid_configs`, so a dual-subscribed block yields two rows. Per row:

`block_id, block_code, block_name, product_id, product_name, native_pixel_m,
current_cell_size_m, current_z, action, reason, scenes_affected`

`action ∈ {rezone, create, threshold, none, skipped, blocked}`, computed by calling the
real `validate_cell_size` per row (§2.1). `skipped` = no active subscription, or (for a
threshold apply) no grid yet. `blocked` carries the backend's own guardrail string.

**Authority:** template edit gates on `farm.manage_config`; apply additionally requires
`imagery.subscription.manage` (it reshapes observation streams and spends compute — the
same scope the per-block PUT uses). Require both.

Reuse `_resolve_target_blocks` and the `target_block_ids` convention so per-block
"reset to farm" is the same code path with a one-element list.

### B3 — Apply, threshold-only *(non-destructive — ship this first)*

Writes `anomaly_z_threshold` on each selected block's active config via the existing
in-place `repository.update_config_threshold`. **Must not** route through
`service.upsert_config`, which would rezone if the cell size happened to differ.

No geometry change, no data loss, effective on the next sweep. This is the whole of the
mock's section ② and it needs none of Track A.

### B4 — Apply, cell size *(destructive — gated behind Track A)*

Per selected row: run the §A4 step-1 cutover, then enqueue backfill under the farm
budget below. Atomic per farm — partial application is worse than none.

Preview must state truthfully: how many grids rezone, how many scenes the budget
recomputes, and **which blocks the budget does not reach** — those keep a second,
older geometry (§A4) rather than being silently dropped.

Keep the mock's **type-the-farm-name** confirmation for any destructive selection.

#### Farm-level compute budget *(decided — replaces the per-block cap)*

`grid.backfill_block`'s `limit=200` per block (`grid/tasks.py:405`) is the wrong shape
for a farm apply: 36 blocks × 200 is 7,200 unbudgeted jobs, and the cap silently
truncates per block with no farm-wide view.

**Unit: scene-compute jobs, not CDSE PUs.** `backfill_block` re-enqueues
`compute_indices` against the stored `raw_bands_key` — it recomputes from raw COGs
already in R2 and does **not** re-fetch from CDSE. The cost is heavy-worker time and
the resulting aggregate rows, not provider quota. *(Read from
`grid/tasks.py:439` + `imagery/tasks.py` step 3; confirm before quoting it to anyone
sizing capacity.)*

- Apply request carries `backfill_budget_scenes: int | null` — null meaning "everything".
- Preview returns the **total scene-jobs the selection implies**, farm-wide, so the
  number is chosen against a real figure rather than guessed.
- A new `grid.backfill_farm` task owns the fan-out and enforces the budget across
  blocks instead of per block. **Newest scenes first** — recent history is what gets
  looked at, and it makes the §A4 step-2 `effective_from` walk backwards
  monotonically, which is the only order that yields a coherent two-geometry state.
- Fair-share across blocks so one 500-scene block can't consume a farm budget and
  leave 35 blocks untouched.
- Report what it did **and did not** reach; that number feeds the §A4 partial-rewrite
  disclosure and the Backfill Console.
- Keep the per-block `limit` for the existing single-block endpoint — unchanged
  behaviour there.

### B5 — Frontend

`BlockDefaultsPanel.tsx` gains a fourth `Card` with the mock's two numbered sections.
Reuse `LockChip` and `ApplyPreviewPanel` (the row/checkbox/summary shell already exists
for subscriptions).

Carry over the three #330 guards, which the mock already encodes: snapshot-compare
against the **saved** template and disable Apply while dirty; disable Confirm when
nothing would change; render a zero-change apply as a **warning, not green**.

Reuse `BlockGridConfigCard`'s number input + live preview call for the single-block
case; the farm case debounces onto the batch preview endpoint.

### B6 — i18n + tests

EN + AR keys under `farmConsole` (parity check is enforced). Vitest for the dirty-guard
and zero-change-warning paths, mutation-checked the way `BlockDefaultsPanel.test.tsx`
was. Playwright: farm with mixed products → set 8 m → assert S2 rows go `blocked` and
PlanetScope survives.

---

## 5. Sequencing — three independent PRs *(decided)*

The safe half of the feature ships first; the destructive half waits on the foundation.
Each PR stands alone and is revertable without unpicking the others.

### PR 1 — Bulk anomaly threshold *(non-destructive)*
B1 template + `grid` lock category, B2 batch preview endpoint, B3 threshold-only apply,
B5 panel section ② + the three #330 guards, B6 i18n/tests.
Tenant migration `0053` (farm template columns + `grid_locked`).
Ships the bulk capability for the knob that actually gets retuned, and needs nothing
from Track A. Section ① of the panel is not rendered yet.

### PR 2 — Grid valid time *(own PR, no feature surface)*
All of Track A: A1 schema, A2 the 9 read paths, A3 scene-time-aware write path,
A4 rezone cutover + supersede, A5 cleanup task + purge/retention wiring, A6 tests.
Tenant migration `0054`.
**Justified independently of this feature** — §2.2 is a live bug on `main` and this is
its fix. Reviewable as a bug fix with a migration rather than buried in a feature diff,
and revertable on its own if the read-path sweep misses something.
Land the §2.2 regression test **first**, red, to prove the defect before fixing it.

### PR 3 — Bulk cell size / rezone *(destructive)*
B4 apply + `grid.backfill_farm` + the farm compute budget, panel section ①,
type-the-farm-name confirmation, partial-rewrite disclosure.
Depends on PR 1 (template, preview, panel) and PR 2 (cutover semantics).

**Do not ship PR 3 before PR 2.** One click would orphan history across 36 blocks, and
per §2.2 the heatmap and the anomaly sweep would go quiet at the same moment — a
farm-wide silent failure.

## 6. Decisions taken

| Decision | Choice | Consequence |
|---|---|---|
| Rezone mode | **Rewrite history** — one geometry over the whole record | Implemented as recompute-then-swap (§A4); needs `superseded_at` + a cleanup task |
| Backfill cap | **Farm-level compute budget**, replacing the 200/block cap | New `grid.backfill_farm`; unit is scene-jobs, not CDSE PUs (§B4) |
| Phase 2 packaging | **Its own PR** | Sequenced as PR 2 above; carries the §2.2 regression test |

## 7. Verify before building

1. **Reproduce §2.2 on the dev tenant** — rezone a block that has history, then check
   whether the heatmap goes all-"no data" and the sweep stops flagging. The whole
   justification for PR 2 as a standalone bug fix rests on this. If it does *not*
   reproduce, re-derive §2.2 before writing the migration.
2. **Confirm backfill does not re-hit CDSE** (§B4) — trace one `compute_indices` re-run
   and check it reads the stored `raw_bands_key` rather than fetching. Determines
   whether the budget is a compute knob or a spend knob.
3. **`btree_gist` availability** in the tenant schemas for the §A1 exclusion constraint.
