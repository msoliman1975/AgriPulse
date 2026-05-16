# Farm-Block Config Model

Author: design session 2026-05-14
Status: proposed, not started
Branch (planned): `feat/farm-block-config-model`

## Problem

Today's farm/block config story is muddled. Some fields (imagery cadence, weather provider) have a partial inheritance pattern via `farm_imagery_overrides` / `farm_weather_overrides`, but the table shape is one-row-per-farm with single nullable knobs — it doesn't hold the actual product/provider list. Other fields (irrigation system, responsible user, tags) live only on blocks with no farm-level concept. Soil and crop fields live only on blocks (correctly — they are measurements, not policy). There is no consistent mental model for "what's farm-wide, what's block-local, what's templatable."

Users want to:
1. Configure a farm including its own details and the defaults that blocks should inherit.
2. Populate those defaults into the blocks under that farm.
3. Continue editing block-level overrides for blocks that need to diverge.
4. Optionally enforce that some categories stay centrally managed (no block-level edits).

## Concept

Every configurable field falls into one of three buckets:

| Bucket | Lives on | Block UI | Farm UI | Mechanic |
|---|---|---|---|---|
| **Farm-only** | farms row | not shown | editable | normal CRUD on the farm |
| **Block-only** | blocks row | editable | not shown | normal CRUD on the block |
| **Shared (template)** | farm template + block columns | shown; editable iff lock OFF | template editable + lock toggle + Apply | farm holds template, blocks hold values, lock enforces farm==block when ON |

Authoring model is **Approach B (snapshot/copy)**: editing the farm template does not silently propagate to blocks. "Apply to blocks" is an explicit action with a diff preview. The **lock** toggle per Shared category adds an enforcement layer — when locked, block fields become read-only and the farm template auto-syncs to all blocks; flipping the lock ON when blocks diverge requires confirming an overwrite.

This is Approach B + per-category lock, not pure live inheritance (Approach A). It avoids the "what is my effective value" resolver mental model that pure A imposes, while keeping the consistency guarantees A gives for free.

## Field-by-field triage

### Farm-only
Context that only makes sense for the whole property.

- `farms.code`, `farms.name`, `farms.description`
- `farms.boundary`, `farms.boundary_utm`, `farms.centroid`, `farms.area_m2`
- `farms.elevation_m`
- `farms.governorate`, `farms.district`, `farms.nearest_city`, `farms.address_line`
- `farms.farm_type`, `farms.ownership_type`, `farms.primary_water_source`
- `farms.established_date`
- `farms.farm_manager_id` *(new — renamed concept; see below)*
- `farms.tags` (farm-wide tags — distinct from `default_tags`)
- `farms.active_from`, `farms.active_to`

### Block-only
Per-plot identity, geometry, and measurements.

- `blocks.code`, `blocks.name`, `blocks.notes`
- `blocks.boundary`, `blocks.boundary_utm`, `blocks.centroid`, `blocks.area_m2`, `blocks.aoi_hash`
- `blocks.slope_pct`, `blocks.aspect_deg`, `blocks.elevation_m`
- `blocks.unit_type`, `blocks.parent_unit_id`, `blocks.irrigation_geometry` (pivot/sector identity)
- `blocks.active_from`, `blocks.active_to`
- `blocks.agronomist_id` *(renamed from `responsible_user_id`)*
- Soil: `soil_texture`, `salinity_class`, `soil_ph`, `soil_ec_ds_per_m`, `soil_organic_matter_pct`, `last_soil_test_date`
- Crop: entire `block_crops` table (planting_date, variety, growth_stage, density, spacing, etc.)
- `block_index_baselines.*` (auto-computed)
- `irrigation_schedules.*` (workflow state)

### Shared (template + edit + lock)

**Subscriptions** *(lockable)*
- Imagery: full list of `(product_id, cadence_hours, cloud_cover_max_pct, is_active)` rows
- Weather: full list of `(provider_code, cadence_hours, is_active)` rows

**Irrigation** *(lockable)*
- `irrigation_system`, `irrigation_source`, `flow_rate_m3_per_hour`

**Org** *(lockable)*
- `default_tags` — additive; farm tags are merged into block `tags`, not replacing them.

## Naming changes

Two role-bearing fields get distinguishing names to make their scope unambiguous:

- **`farm_manager_id`** (new, Farm-only) — the person accountable for the whole property: planning, contracts, strategic ownership.
- **`agronomist_id`** (rename of `blocks.responsible_user_id`, Block-only) — the person tending this specific plot day-to-day.

A future `farm_default_agronomist_id` (Shared) can be added if "who manages new blocks by default" becomes a real ask; out of scope for V1.

## Edge calls

- **Tags** — farm tags are *additive context*. The block always shows farm tags as read-only chips plus its own editable tags. Applying the org template merges farm `default_tags` into each block's `tags` set; existing block-local tags are never removed.
- **Soil** — kept Block-only. We did not add a farm-level soil default. If users complain about retyping soil values when creating many blocks under one uniform farm, revisit by adding a Template-seed only pattern (farm holds default, prefills on new block creation, no sync, no lock).
- **Crop / planting plan** — kept Block-only. Same reasoning. Revisit if users want farm-wide planting plans.

## UX

### FarmDrawer tabs

`Identity | Location | Geometry | People | Defaults | Lifecycle`

- **Identity / Location / Geometry / People / Lifecycle** — Farm-only fields, conventional forms. The People tab holds `farm_manager_id`.
- **Defaults** — the new heart of this design. One accordion section per Shared category (Subscriptions, Irrigation, Org), each with:
  - Header: category name + lock state chip (🔓 / 🔒) + Lock/Unlock button.
  - Body: template fields (always editable here).
  - Status line: "X of N blocks match this template. Y diverged ▾" (clickable, opens divergent-blocks drawer).
  - Action: `[Apply to all blocks…]` (only when unlocked — locked is already auto-synced).

### Block DetailPanel tabs

`Overview | Crop | Soil | Settings | People | Notes`

- **Overview / Crop / Soil / People / Notes** — Block-only fields. People holds `agronomist_id`; `farm_manager_id` shown read-only as context.
- **Settings** — the Shared categories (Subscriptions + Irrigation):
  - **Unlocked state:** editable inputs, with per-field "differs from template" ⚠ chip when divergent, and a section-level `[Reset to farm]` CTA.
  - **Locked state:** read-only display, 🔒 "Centrally managed by farm template" banner, link `[Open farm template ↗]`.

### Lock-on transition (with divergent blocks)

Modal shows the diff — "Locking X will overwrite N blocks: …" — with `[Cancel]` or `[Lock and overwrite]`. Lock-off is silent.

### Apply-to-blocks (unlocked)

Modal lists all blocks with a checkbox per block and a per-block diff preview. User can selectively uncheck blocks. Same pattern as the existing imagery overrides UX, generalized.

## Authority

| Action | FarmManager | Agronomist | TenantAdmin |
|---|---|---|---|
| Edit Farm-only fields | ✓ | — | ✓ |
| Edit farm template (Defaults tab) | ✓ | — | ✓ |
| Toggle lock | ✓ | — | ✓ |
| Apply template to blocks | ✓ | — | ✓ |
| Edit Block-only fields | ✓ | ✓ | ✓ |
| Edit Shared fields on a block (lock OFF) | ✓ | ✓ | ✓ |
| Edit Shared fields on a block (lock ON) | — | — | — (server 409) |

New capability: **`farm.manage_config`** — required for template edits, lock toggles, Apply, Reset. Granted to FarmManager + TenantAdmin.

## Schema sketch

```sql
-- 1. Farm template + lock state on farms row
ALTER TABLE farms
  ADD COLUMN farm_manager_id UUID NULL,
  ADD COLUMN default_irrigation_system     TEXT NULL,
  ADD COLUMN default_irrigation_source     TEXT NULL,
  ADD COLUMN default_flow_rate_m3_per_hour NUMERIC(8,2) NULL,
  ADD COLUMN default_tags                  TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
  ADD COLUMN subscriptions_locked BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN irrigation_locked    BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN org_locked           BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Block rename
ALTER TABLE blocks
  RENAME COLUMN responsible_user_id TO agronomist_id;

-- 3. Subscriptions: existing override tables expand into true multi-row templates
--    (one row per product/provider rather than one row per farm).
ALTER TABLE farm_imagery_overrides
  RENAME TO farm_imagery_template;
-- new shape: PK (farm_id, product_id), cols cadence_hours, cloud_cover_max_pct, is_active
ALTER TABLE farm_weather_overrides
  RENAME TO farm_weather_template;
-- new shape: PK (farm_id, provider_code), cols cadence_hours, is_active

-- 4. Track when block subs were last reconciled by an Apply
ALTER TABLE imagery_aoi_subscriptions ADD COLUMN applied_at TIMESTAMPTZ NULL;
ALTER TABLE weather_subscriptions     ADD COLUMN applied_at TIMESTAMPTZ NULL;
```

No new resolver. No three-tier inheritance chain to maintain. Block reads are direct SELECTs on the block rows; the template is only consulted by the Apply/Lock/Reset endpoints.

## Rollout — 4 PRs

Branch `feat/farm-block-config-model`. Tenant migrations pick up from 0026 (lifecycle migration).

### PR-1 — Schema + renames (mechanical foundation)

Goal: land column changes with zero behavior change so subsequent PRs touch only logic/UI.

**Backend**
- Migration `0027_farm_block_config_foundation` per schema sketch above (parts 1 + 2).
- Update SQLAlchemy models in `backend/app/modules/farms/models.py` and `blocks/models.py`.
- Pydantic schemas: `FarmRead`/`FarmUpdate` gain new fields (all nullable); `BlockRead`/`BlockUpdate` get `agronomist_id`.
- `GET /v1/farms/{id}` + `GET /v1/blocks/{id}` return the new fields. No new write endpoints.
- Add `farm.manage_config` capability and grant to FarmManager + TenantAdmin roles.

**Frontend**
- Regenerate API types.
- Search-replace `responsible_user_id` → `agronomist_id` across `frontend/src` (queries, DetailPanel "People" section, types). Label changes from "Responsible" → "Agronomist".
- FarmDrawer adds stubbed "Defaults" tab — placeholder "Coming in PR-2".

**Tests**
- Migration round-trip (upgrade → downgrade → upgrade).
- `agronomist_id` writes through existing block PATCH.
- Existing tests stay green.

**Risk:** none material.

### PR-2 — Subscriptions template + Apply-to-blocks

Goal: turn override tables into true farm templates, build authoring UI, ship Apply flow. No lock yet.

**Backend**
- Migration `0028_subscriptions_template` per schema sketch parts 3 + 4. Data move: existing single-row knobs become a synthetic single-row template per farm under the "currently-most-used" product/provider (one-time best-effort backfill).
- New module `backend/app/modules/farms/config_template.py`:
  - `get_farm_template(farm_id, category)` — returns template rows for category.
  - `compute_apply_diff(farm_id, category, target_block_ids=None)` — returns per-block diff `{block_id, will_add, will_remove, will_update}`.
  - `apply_template(farm_id, category, target_block_ids=None, updated_by)` — atomic: reconciles each target block's rows to match the template (add missing, update changed, remove extra). Sets `applied_at = now()`.
- New endpoints under `/v1/farms/{id}/config/`:
  - `GET /subscriptions/template`, `PUT /subscriptions/template` (replace whole list)
  - `POST /subscriptions/apply-preview` (body: optional `block_ids`) → diff
  - `POST /subscriptions/apply` (body: `block_ids`) → executes, returns counts
- Authority: requires `farm.manage_config`.

**Frontend**
- New `FarmDefaultsTab` component with one accordion section: **Subscriptions**.
  - Imagery product list + Weather provider list, editable inline (cadence, cloud%, is_active). `[+ Add product]` opens a picker fed by `/v1/imagery/products`.
  - "X of N blocks match" status line (cached 30s).
  - `[Apply to all blocks…]` → `ApplyTemplateModal` with per-block diff + checkboxes.
- Block DetailPanel: read-only display of effective subscriptions; soft "Inherits from farm template" badge.

**Tests**
- Template CRUD: insert / update / replace.
- Apply-preview correctness across: block-matches, block-has-extra-row, block-has-divergent-knob.
- Apply atomicity: nothing partially-applied on rollback.
- Selective apply: passing `block_ids` only touches those blocks.

**Risk:** the data move in 0028 is the hairy part. Recommend a feature flag `FARM_CONFIG_TEMPLATE_ENABLED` (default OFF) so rollout can be staged in prod.

### PR-3 — Lock + Irrigation + Org template

Goal: introduce lock semantics and the remaining two Shared categories.

**Backend**
- Service-layer guards in `config_template.py` and block PATCH handlers: reject writes to locked-category fields with 409 Conflict. *(Triggers were considered but rejected — service-layer guards keep the test surface in Python; the cost is that direct DB writes bypass the lock, which is an acceptable trade.)*
- Extend `config_template.py` with `lock_category(farm_id, category, force_overwrite=False)`:
  - If `force_overwrite=False` and divergent blocks exist → 409 with diff payload (UI renders confirm modal).
  - If `force_overwrite=True` → run `apply_template` then set lock boolean.
- New endpoints:
  - `POST /subscriptions/lock` + `/unlock` (and same for irrigation, org)
  - `GET /irrigation/template` + `PUT /irrigation/template`
  - `GET /org/template` + `PUT /org/template`
  - `POST /irrigation/apply-preview` + `/apply`
  - `POST /org/apply-preview` + `/apply` (additive merge — never removes block-local tags)

**Frontend**
- FarmDefaultsTab gains Irrigation + Org sections.
- Lock toggle UI per section header with `LockToggleModal` (shows diff when locking with divergent blocks).
- Block DetailPanel: new **Settings** tab:
  - Subscriptions + Irrigation rendered locked (🔒, read-only, link to farm template) or unlocked (editable inputs).
  - Locked attempts blocked client-side (disabled inputs) AND server-side (409).

**Tests**
- Lock-on-with-divergence: API returns 409 + diff; `force_overwrite=true` resolves and sets lock.
- Lock-on then attempt block edit: 409.
- Lock-off: block edits work again.
- Org-tags merge: farm `default_tags=['#cotton']` applied to block `tags=['#south']` → `['#south', '#cotton']`.

**Risk:** lock-state UI must stay in sync across tabs. Use react-query invalidation on the farm record after any lock mutation.

### PR-4 — Drift detection (Reset + status) + polish

Goal: make unlocked-but-diverged state observable on both sides.

**Backend**
- `GET /v1/farms/{id}/config/<category>/divergence` → `{matched_block_ids, divergent_block_ids, total}`.
- `POST /v1/blocks/{id}/config/<category>/reset-to-farm` → applies farm template to that one block.
- Audit events for every Apply / Lock / Unlock / Reset with diff payload.

**Frontend**
- Farm Defaults tab: live "X of N match • Y diverged ▾" link → side-drawer listing divergent blocks with per-row Reset buttons.
- Block Settings tab (unlocked): per-field ⚠ chip when divergent + section-level `[Reset to farm]` CTA.

**Tests**
- Divergence endpoint across all three categories.
- Reset endpoint: reverts a single block, doesn't touch others.
- Audit: one event per action, payload includes diff.

**Risk:** none — pure additive UX.

## Cross-cutting

**Capability added in PR-1:** `farm.manage_config`.

**Feature flag:** `FARM_CONFIG_TEMPLATE_ENABLED` (default OFF in PR-2, flipped on after backfill verification; removed in PR-4 or follow-up cleanup).

**Docs to refresh** (PR-4 or follow-up): `docs/data_model.md` § farms/blocks, plus new § "Farm-block config model" + runbook for "blocks divergent after lock failure → how to manually resolve."

## Out of scope (V2 / later)

- `farm_default_agronomist_id` — Shared field for new-block prefill of agronomist.
- Default crop / planting plan at farm level (Template-seed only pattern).
- Per-block lock overrides (e.g. "this block always uses 12h cadence even when subscriptions locked").
- Bulk template editor across multiple farms (tenant-level template).
- Soil defaults at farm level.
