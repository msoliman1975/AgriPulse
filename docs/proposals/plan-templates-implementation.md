# Plan Templates — Design & Implementation Plan

**Status:** Designed, approved. Coding **parked** until the parallel *Reports* session lands (shared-file coordination — see §0).
**Date:** 2026-06-12 · **Revised 2026-06-13** to target by the crop-taxonomy **path** (Crop → Variety → Strain) now that the taxonomy branch shipped.

A new capability: **platform-curated agriculture plan templates** keyed by a crop-taxonomy **path** (crop, variety, or strain) (+ optional region), made of standard activities with **types and durations but no fixed dates**. A tenant applies a template to a farm's matching-crop blocks with a start date, and the system materialises the existing plan/board structure (`vegetation_plans` + `plan_activities`).

> **Crop-taxonomy alignment (2026-06-13).** The `feat/crop-taxonomy` branch added the 3-level Crop → Variety → Strain taxonomy with a canonical, prefix-matchable **path code** (`mango.alphonso.short` / `cotton`), denormalised onto `block_crops.crop_path`, and made it the cross-consumer targeting key for decision trees (PR-3) and reports (PR-4). Plan templates **reuse the same convention**: target by `crop_path` prefix and match with the shared pure helper `app.shared.crop_taxonomy.path_matches(target, actual)`. This supersedes the original `crop_id` + optional `crop_variety_id` hard-gate below.

---

## Design decisions (locked)

1. **Ownership** — Platform-curated catalog in the **public schema** (like `crops` / `decision_trees`); tenants apply read-only. Platform admins author.
2. **Template shape** — header (**`crop_path`** targeting key — crop, variety, or strain depth via the cascading picker; + optional region/country + name) → **template-local milestones** (name + `day_from_start`) → **activities** (`activity_type`, `anchor` = `start` *or* a milestone, `offset_days`, `duration_days`, + optional defaults). `crop_id` stays denormalised on the row (derived from the path's first segment) for display + crop-scoped queries.
3. **Timing model** — mix of explicit **offset-from-start** and **milestone-anchored** activities. Milestones are **template-local** (each template declares its own); no shared crop-phenology model (G2 stays a separate future effort).
4. **Apply targeting** — user picks the farm's **matching-crop blocks**; **per-block start date** (default = that block's `BlockCrop.planting_date`); each block resolves its own dates.
5. **Apply output** — create/reuse one **`VegetationPlan`** per farm+season and link the generated `PlanActivity` rows to it (named, status-tracked, deletable as a unit).
6. **Match strictness** — the template's `crop_path` is a **hard gate by path prefix**: it matches a block whose `block_crops.crop_path` equals the template path or is a descendant of it (`path_matches(template.crop_path, block.crop_path)`). So a `mango` template fits every Mango block (any variety/strain), `mango.alphonso` fits all Alphonso strains, and `mango.alphonso.short` is exact — one rule replaces the old crop-then-variety gate. Region/country are **soft sort hints only** (never block). No new farm `country` field — sort hint uses farm `governorate`.
7. **Re-apply** — idempotent per farm+season: regenerate template-generated **pending** rows for the selected blocks; **preserve** completed/in-progress **and** manually-added rows; applying to a new block just adds.

**Defaulted (confirmed):** source marker on `plan_activities`; country/region on template only; per-activity defaults (`product_name`/`dosage`/`notes`/`start_time`); reuse existing `activity_type` vocabulary; season label/year derived-then-editable; platform authoring + `plan_template.{manage,read,apply}` caps; generated rows `status='scheduled'`.

---

## §0 — Coordination with the *Reports* session ⚠️
Collision surface is small (we add a **new `plan_templates` module** + additive columns). Shared files to merge carefully:
- `capabilities.yaml` / `role_capabilities.yaml` — both add caps (additive; expect a conflict).
- Migration heads (**public and tenant**) — both add migrations → revision-chain collision. Mitigation: create migrations **last**, chain off the then-current head, rebase `down_revision` at integration.
- Platform + tenant nav entries (additive).
- No shared backend modules or frontend pages.

---

## §1 — Data model

### Public schema (platform-curated)
- **`plan_templates`** — `id`, `code` (unique), `name`, **`crop_path`** (text, the targeting key — `mango` / `mango.alphonso` / `mango.alphonso.short`; btree index for prefix lookups), `crop_id`→crops (denormalised from the path's first segment for display), `country` (nullable text), `region` (nullable text), `description`, `status` (`draft`|`published`|`archived`; only `published` appliable), timestamps. *Drops the separate `crop_variety_id` FK — variety/strain targeting now lives in `crop_path`. No versions table for V1 (apply snapshots into `plan_activities`, so edits never mutate applied plans); versioning deferred.*
- **`plan_template_milestones`** — `id`, `template_id` (cascade), `code` (unique per template), `name`, `day_from_start` (≥0), `sort_order`.
- **`plan_template_activities`** — `id`, `template_id` (cascade), `activity_type` (shared vocabulary), `anchor` (`start`|`milestone`), `milestone_id` (nullable; required when `anchor=milestone`), `offset_days` (int; negative allowed for "before a milestone"), `duration_days` (≥1), `product_name`/`dosage`/`notes`/`start_time` (nullable), `sort_order`. Validation: resolved day `(anchor==start?0:milestone.day_from_start)+offset_days` ≥ 0.

### Tenant schema (additive)
- **`plan_activities`** — add `source` (`manual`|`template`|`recommendation`, default `manual`), `applied_template_id` (nullable), `template_activity_id` (nullable); partial index `(plan_id, block_id, applied_template_id) WHERE applied_template_id IS NOT NULL`.
- **`vegetation_plans`** — add `applied_template_id` (nullable). *All nullable adds — data-safe, fast; needs data-safe downgrades for the CI roundtrip tests.*

---

## §2 — Apply engine
- **Resolver (pure fn, unit-tested):** `(template, block_start_date) → [{activity_type, scheduled_date, duration_days, defaults…}]`; `scheduled_date = block_start_date + ((anchor==start?0:milestone.day)+offset)`.
- **`apply_template` service** — input `{template_id, farm_id, season_label, season_year, blocks:[{block_id, start_date}]}`:
  1. **Hard-gate match** per block via `path_matches(template.crop_path, block_crops.crop_path)` (exact path or any descendant).
  2. **Find-or-create** `VegetationPlan(farm, season_label, season_year)`; set `applied_template_id`.
  3. **Idempotent regen per block:** `DELETE plan_activities WHERE plan_id=… AND block_id=… AND applied_template_id=template AND status='scheduled'`, then insert fresh. Preserves `source='manual'` + completed/in-progress.
  4. Insert with `source='template'`, `applied_template_id`, `template_activity_id`, `status='scheduled'`.
- **Preview (dry-run):** same resolution, no writes — per-block schedule for the wizard.

---

## §3 — REST API (new `plan_templates` router)
**Authoring (cap `plan_template.manage`, platform):**
`GET /v1/plan-templates` · `POST` · `GET /{id}` (full tree) · `PUT /{id}` (**replace whole tree** atomically) · `POST /{id}/publish` · `/archive` · `DELETE` (archive).

**Apply (cap `plan_template.apply`, tenant; farm-scoped):**
- `GET /v1/plan-templates/appliable?farm_id=` — published templates matching the farm's block crops (hard gate), region-sorted; returns matching blocks + `planting_date` defaults.
- `POST /v1/plan-templates/{id}/preview` — dry-run schedule.
- `POST /v1/plan-templates/{id}/apply` — runs engine; returns `{plan_id, per-block counts, skipped, total}`.

---

## §4 — Frontend
**Platform authoring `/platform/plan-templates`:** list (crop path, status, #applied) + editor (header with the **cascading crop → variety → strain picker** that emits `crop_path` — same control as `CropPathFilter`/`CropPicker`, depth-aware via `classification_depth` — + region/country + name; milestones editor; activities editor with anchor dropdown/offset/duration/defaults) + **timeline/Gantt preview** of resolved days + publish/archive.

**Tenant apply (Plan/board page + farm context on `/labs/map`):** "Apply template" → wizard: (1) pick template (matches first, region hint) → (2) pick blocks (pre-checked matching-crop) + **per-block start date** (default `planting_date`) → (3) season label/year (derived, editable) → (4) **preview schedule** → confirm → apply. `api/planTemplates.ts`; i18n en/ar.

---

## §5 — Capabilities & seeding
New caps `plan_template.manage` (platform), `plan_template.read` + `plan_template.apply` (tenant). Add to the two yaml files (⚠️ Reports merge). Optional: seed 1–2 starter templates (wheat, tomato) via public migration/loader, or author via UI.

---

## §6 — Staged PR rollout
- **PR-1** — Data model + migrations (public 3 tables + tenant column adds; models/repo/schemas). Migrations created **last** + rebased vs Reports; data-safe downgrades.
- **PR-2** — Apply engine + tenant endpoints (resolver + appliable/preview/apply + caps). Tests: resolver math, idempotent re-apply (preserve manual/completed), **path-prefix hard-gate match** (crop/variety/strain depth via `path_matches`), per-block dates.
- **PR-3** — Platform authoring API + UI (whole-tree CRUD + editor + timeline preview).
- **PR-4** — Tenant apply wizard UI (button + 4-step wizard + preview).
- **PR-5** — Seed + polish + i18n + docs.

---

## §7 — Open / optional (non-blocking)
- Template **versioning** (deferred — apply snapshots, so not needed for correctness).
- `activity_type` vocabulary — reuse existing; add `land_prep`/`scouting` if missing (small shared-constant edit).
- "Generated from template" badge on board activities (uses `source`/`applied_template_id`).

---

## Existing structures this builds on (reference)
- `backend/app/modules/plans/models.py` — `VegetationPlan` (one per farm/season), `PlanActivity` (`block_id`, `activity_type`, `scheduled_date`, `duration_days`, `start_time`, `product_name`, `dosage`, `notes`, `status`, `recommendation_id`).
- `backend/app/modules/plans/schemas.py` — the `activity_type` vocabulary.
- `backend/app/modules/farms/models.py` — `Crop` (`classification_depth`), `CropVariety` (`path`), `CropVarietyStrain` (`path`), `BlockCrop` (`block_id`+`crop_id`+`crop_variety_id`+`crop_variety_strain_id`+**`crop_path`**+`season_label`+`planting_date`), `Farm` (`governorate`/`district`; **no country field**).
- `backend/app/shared/crop_taxonomy.py` — `path_matches(target, actual)` (prefix gate) + `strain_code(path)`; reuse for the hard-gate match, don't re-implement.
