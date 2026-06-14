# Phenology Spine & Stage-Aware Planning — Implementation Plan

**Status:** Designed, approved for implementation. **Date:** 2026-06-13.
**Supersedes/extends:** `docs/proposals/plan-templates-implementation.md` (un-parked — Reports V1 has landed, so its §0 collision note is resolved). Plan-templates is now built **on top of** the phenology spine (Option 1 — phenology is the canonical timing spine; template activities anchor to stage codes).

This initiative connects four previously-separate threads into one model:

1. **Phenology stages become a real, validated, taxonomy-owned model** (Crop → Variety → Strain), not opaque JSON.
2. **Canopy size becomes a taxonomy-defined lookup** (same resolver pattern), surfaced as a Block-level dropdown and exposed to the rules engine.
3. **Growth stage auto-advances** via a daily task (writes `source='derived'`), with a per-block **lock flag** to honour manual overrides.
4. **Plan templates anchor activities to stages**, so a single source of truth (the taxonomy's stages) drives both "what stage is this block in" *and* "when does this activity land."

The recommendation engine (which already reads `block.growth_stage`) gains soil + canopy-size inputs and a corrected mango ruleset (NDMI, stress-induction = low-moisture **AND** cool-temp).

---

## 0. What already exists (do not rebuild)

| Asset | Location | State |
|---|---|---|
| `Crop.phenology_stages`, `CropVariety/Strain.phenology_stages_override` (JSONB) | `farms/models.py` | Columns exist; **opaque, unvalidated, empty** |
| `Crop.is_perennial`, `gdd_base_temp_c`, `gdd_upper_temp_c`, `default_growing_season_days` | `farms/models.py` | Exist — drive cycle + GDD math |
| `resolve_phenology_stages()` (wholesale deepest-wins) | `farms/crop_thresholds.py` | Exists; sibling to `resolve_thresholds()` |
| `BlockCrop.growth_stage`, `growth_stage_updated_at`, `season_label`, `planting_date` | `farms/models.py` | Exist |
| `GrowthStageLog` + `source ∈ (manual,derived,imported)` (`ck_growth_stage_logs_source`, tenant 0007) | `farms/models.py` | Exists; **`derived` reserved, never written** |
| `record_growth_stage_transition()` service + `POST /v1/blocks/{id}/growth-stages` | `farms/service.py`, `router.py` | Manual path works |
| Rules engine reads `block.growth_stage` (`BLOCK_FIELDS`) | `shared/conditions/models.py:40` | Wired |
| `WeatherDerivedDaily` (per farm/day): `gdd_base10/15`, `gdd_cumulative_base10_season`, `temp_min/max/mean` | `weather/` | Exists; farm-level |
| 7 indices incl. **NDMI** (NIR−SWIR) and NDWI (McFeeters, Green−NIR) | `indices/computation.py` | Computed/stored |
| `VegetationPlan` (farm + `season_label` + `season_year`), `PlanActivity` | `plans/models.py` | Exists |
| `path_matches(target, actual)` prefix gate | `shared/crop_taxonomy.py` | Reuse for template match |

**Migration heads at time of writing:** public **`0031`**, tenant **`0039`**. All new migrations chain off these (rebase `down_revision` at integration).

---

## 1. Data model

### 1.1 Phenology stages — canonical, validated shape

Stored in the existing `phenology_stages` (Crop) / `phenology_stages_override` (Variety/Strain) columns. No new columns; we **define and enforce** the shape with a Pydantic model and validate on write (catalog authoring API) — storage stays JSONB.

```jsonc
{
  "stages": [
    {
      "code": "pre_flowering",                  // stable; matches BlockCrop.growth_stage
      "name_en": "Pre-flowering (stress induction)",
      "name_ar": "ما قبل التزهير (التصويم)",
      "order": 2,
      "advance": {
        "mode": "calendar_doy",                 // days_from_planting | gdd_from_planting | calendar_doy | manual
        "start_doy": "12-01",                    // calendar_doy: MM-DD, wrap-around allowed
        "end_doy": "01-31"
      }
    },
    {
      "code": "fruit_development",
      "name_en": "Fruit set & development", "name_ar": "العقد وتطور الثمار", "order": 4,
      "advance": { "mode": "calendar_doy", "start_doy": "03-15", "end_doy": "06-30" }
    }
  ]
}
```

**Mode → parameters:**
- `days_from_planting` → `start_day`, `end_day` (int days after `BlockCrop.planting_date`). Annual crops.
- `gdd_from_planting` → `start_gdd`, `end_gdd` (cumulative GDD from planting, using `Crop.gdd_base_temp_c`/`gdd_upper_temp_c`). Annual crops.
- `calendar_doy` → `start_doy`, `end_doy` (`MM-DD`, wrap allowed e.g. Dec→Jan). Perennials (recurring season).
- `manual` → no params; only advances via the manual endpoint.

**Validation rules (Pydantic + cross-check against `Crop.is_perennial`):**
- `code` unique within the list; `order` unique and contiguous-ish (warn, not hard-fail).
- **Perennial crops** (`is_perennial=true`): every stage `advance.mode ∈ {calendar_doy, manual}`. `days/gdd_from_planting` rejected (planting was years ago → meaningless).
- **Annual crops**: `advance.mode ∈ {days_from_planting, gdd_from_planting, manual}`. `calendar_doy` rejected.
- `gdd_from_planting` requires the crop to have `gdd_base_temp_c` set.
- Stage windows should be non-overlapping per cycle (warn if they overlap; the resolver picks the highest `order` whose window contains "now").

**Resolution:** reuse `resolve_phenology_stages()` — **wholesale replacement**, deepest non-null wins (strain override replaces variety replaces crop). A variety like Keitt can ship its own full stage list.

### 1.2 Canopy size classes — new taxonomy lookup (mirrors phenology)

**Public migration (off 0031):** add JSONB columns
- `crops.size_classes`
- `crop_varieties.size_classes_override`
- `crop_variety_strains.size_classes_override`

Shape:
```jsonc
{
  "classes": [
    { "code": "small",  "name_en": "Small (<2 m)",   "name_ar": "صغير (<2 م)",  "order": 1 },
    { "code": "medium", "name_en": "Medium (2–4 m)", "name_ar": "متوسط (2–4 م)", "order": 2 },
    { "code": "large",  "name_en": "Large (>4 m)",   "name_ar": "كبير (>4 م)",   "order": 3 }
  ]
}
```
- Diameter ranges live in the **label only** (documentation) — no enforced numeric thresholds (per locked decision: skip the over-engineered diameter math / per-soil L-factor).
- New pure resolver `resolve_size_classes()` in `crop_thresholds.py`, wholesale deepest-wins (same as phenology). Returns `[]` if none defined.

### 1.3 Block-level additions

**Tenant migration (off 0039):** add to `block_crops`
- `canopy_size_class` (text, nullable) — one of the resolved `size_classes` codes for the block's `crop_path`. Validated on write.
- `growth_stage_locked` (boolean, not null, default `false`) — when true, the auto-advance task **skips** this block (manual stage is authoritative).

Both live on **`BlockCrop`** (not `Block`): size and stage are properties of the *current planting* and reset on replant — they travel with `planting_date`/`plant_density_per_ha`/`row_spacing_m`.

### 1.4 Plan template tables (from the parked design, **extended** for stage anchoring)

**Public migration (off the new size-classes head):**
- `plan_templates` — `id`, `code` (unique), `name`, `crop_path` (text, btree-indexed for prefix lookup), `crop_id` (denormalised first segment), `country`/`region` (nullable), `description`, `status` (`draft|published|archived`), timestamps.
- `plan_template_milestones` — `id`, `template_id` (cascade), `code` (unique/template), `name`, `day_from_start` (≥0), `sort_order`.
- `plan_template_activities` — `id`, `template_id` (cascade), `activity_type`, **`anchor` (`start|milestone|stage`)**, `milestone_id` (nullable; required when `anchor=milestone`), **`stage_code` (nullable; required when `anchor=stage`)**, `offset_days` (int, negatives allowed), `duration_days` (≥1), `product_name`/`dosage`/`notes`/`start_time` (nullable), `sort_order`.
  - **New vs parked design:** `anchor` gains `stage`; new `stage_code` column. Validation: `stage`-anchored activities require `stage_code` to exist in the **resolved** phenology stages for the template's `crop_path`.

**Tenant migration (off the block-crops head):**
- `plan_activities` — add `source` (`manual|template|recommendation`, default `manual`), `applied_template_id` (nullable), `template_activity_id` (nullable), **`anchored_stage_code` (nullable text — for the board "scheduled at <stage>" badge)**.
- `vegetation_plans` — add `applied_template_id` (nullable).
- All nullable/defaulted adds → data-safe; supply data-safe downgrades for the CI roundtrip tests (see `project_ci_fully_green`).

---

## 2. Auto-advance engine

**New Celery beat task `phenology.advance_growth_stages`** (daily, after weather-derive completes so GDD is fresh).

Per active current `BlockCrop` (`is_current=true`, not harvested), **skip if `growth_stage_locked`**:
1. Resolve phenology stages for `crop_path` (`resolve_phenology_stages`). Skip if none.
2. Determine the **current stage code**:
   - **`is_perennial=true`** → evaluate `calendar_doy` windows against today's `MM-DD` (wrap-aware, same wrap logic as DOY baselines). Pick the highest-`order` stage whose window contains today.
   - **`is_perennial=false`** → compute elapsed since `planting_date`:
     - `days_from_planting`: `(today − planting_date).days` within `[start_day, end_day)`.
     - `gdd_from_planting`: cumulative GDD from planting using farm `WeatherDerivedDaily` daily temps + crop base/upper temp (base10 cumulative is reusable directly when `gdd_base_temp_c==10`; otherwise recompute from daily `temp_min/max` — see §6 follow-up). Match `[start_gdd, end_gdd)`.
3. If computed stage ≠ `BlockCrop.growth_stage`: call the **existing** `record_growth_stage_transition(stage=…, source='derived')` — appends `GrowthStageLog` + mirrors onto `BlockCrop` in one txn.
4. Idempotent: no-op when already on the computed stage.

**Precedence:** the lock flag is the explicit override (locked decision #4). A manual transition sets the stage; if the operator wants it frozen they set `growth_stage_locked=true`. Unlocked blocks always reflect the `derived` computation. (Manual-but-unlocked = the next daily run may move it — documented behaviour.)

**Downstream:** the recommendation engine needs **zero changes** to benefit — it already reads `growth_stage`. This closes the Gap-2 loop end-to-end.

---

## 3. Recommendation engine wiring (Gaps 1, 3, 4)

### 3.1 New block-source fields
Extend `BLOCK_FIELDS` (`shared/conditions/models.py:40`) from
`("crop_category","growth_stage","crop_path","crop_strain")` to add
`"soil_texture"`, `"salinity_class"`, `"canopy_size_class"`.

Populate in the recommendations service where `block_attributes` is built (it reads the current `BlockCrop` + `Block` already): add `Block.soil_texture`, `Block.salinity_class`, `BlockCrop.canopy_size_class`. Pass-through is automatic in `ConditionContext.from_block_signals` (it copies the dict verbatim). Equality/`in` operators already support categorical values — no evaluator change.

### 3.2 Mango decision-tree seeds (corrected agronomy)
New YAML seeds under `recommendations/seeds/`, targeted by `crop_path` (`mango`, or per-variety `mango.keitt` etc.), stage-gated via `block.growth_stage`:

- **Moisture standardised on NDMI** (`index_code: ndmi`), **not** `ndwi` (engine's NDWI = McFeeters surface water — wrong for leaf water). NDMI requires SWIR → **Sentinel-2 only**, unavailable on PlanetScope 3m (note in tree `evidence`/transferability).
- **Stress-induction tree** (stage `pre_flowering`): fire a warning only when **NDMI is high AND min air temp is in the cool-induction band** — i.e. moisture present *and* the cool window that would otherwise induce flowering, so high moisture risks vegetative flush instead. `all_of([ ndmi high, weather.forecast/derived temp low ])`. (Study-backed: water stress alone at warm temp → vegetative only; cool temp ~15 °C required.)
- **NDRE post-harvest flush tree** (stage `post_harvest_flush`): low NDRE → nitrogen/chlorophyll deficiency alert (NDRE penetrates the dense, saturating mango canopy where NDVI flattens).
- **Canopy-size-aware health tree:** `if canopy_size_class == 'small' (or soil_texture sandy)` → evaluate **SAVI** path; else NDVI. Expressed as explicit branches (no auto-index-switching in the engine).
- Keep the **z-score `baseline_deviation`** "sudden drop → stress" detector as the core, self-calibrating per block — the AI-improvised absolute-value matrix is **not** seeded.
- Each tree carries `evidence.citations` (flowering-induction, NDVI-saturation/NDRE, SAVI) and `transferability.egypt`.

---

## 4. Plan templates + plan-object integration (Option 1)

Carries over all 7 locked decisions from the parked doc (platform-curated public catalog; `crop_path` hard-gate via `path_matches`; per-block start date; one `VegetationPlan` per farm+season; idempotent re-apply preserving manual/completed). **The single change is stage anchoring.**

### 4.1 Apply resolver (extended)
Signature gains the block's crop context: `(template, block_start_date, block_crop_ctx) → [{activity_type, scheduled_date, duration_days, anchored_stage_code?, defaults…}]`.

`scheduled_date` by anchor:
- **`start`** → `block_start_date + offset_days`.
- **`milestone`** → `block_start_date + milestone.day_from_start + offset_days`.
- **`stage`** → resolve the stage's **start date for this block**, then `+ offset_days`:
  - **Annual block** → `planting_date + stage.start_day` (or GDD→date by walking accumulated GDD to `start_gdd`).
  - **Perennial block** → map `stage.start_doy` onto the plan's `season_year` (wrap-aware), giving a concrete date.
  - Store `anchored_stage_code` on the generated `PlanActivity` for the board badge.

So a mango template's "post-harvest nitrogen flush fertilization" activity auto-lands relative to the `post_harvest_flush` stage **per variety** (Keitt's calendar differs from Sukkary's), because the stage windows are variety-resolved.

### 4.2 Plan object / board
- `PlanActivity.source='template'` + `applied_template_id` + `template_activity_id` + `anchored_stage_code`. Board shows a "from template" badge and, when stage-anchored, "scheduled at <stage>".
- Re-apply idempotency unchanged: regenerate `source='template'` `status='scheduled'` rows for selected blocks; preserve manual/completed/in-progress.

### 4.3 Caps & endpoints (unchanged from parked design)
- Caps: `plan_template.manage` (platform), `plan_template.read` + `plan_template.apply` (tenant).
- Authoring: `GET/POST/PUT/DELETE /v1/plan-templates`, `/publish`, `/archive`.
- Apply: `GET /v1/plan-templates/appliable?farm_id=`, `POST /{id}/preview`, `POST /{id}/apply`.
- Authoring UI activity editor: anchor dropdown now offers **Start / Milestone / Stage**; when **Stage** is chosen, the stage picker is **populated from the resolved phenology stages for the template's `crop_path`** (same resolver the engine/advancer use).

---

## 5. Staged PR rollout

Spine first (independent value — closes Gap-2 and powers the engine without waiting on plan-templates), then engine wiring, then plan-templates on top.

**Track A — Taxonomy spine**
- **PR-A1** Phenology Pydantic shape + validators (cross-checked vs `is_perennial`); `size_classes` public migration (off 0031) + `resolve_size_classes()`; catalog authoring validates stage/size JSON on write; `GET` resolved stages + sizes per `crop_path`. *(public migration)*
- **PR-A2** Seed mango (5 varieties: **Keitt, Yasmina, Sukkary, Zebda, Crimson**) — perennial `calendar_doy` stages (veg_flush → pre_flowering → flowering → fruit_development → post_harvest_flush) + size classes; seed **potato** as the annual exemplar (`days_from_planting`/`gdd_from_planting`). *(public migration/loader)*

**Track B — Block wiring**
- **PR-B1** Tenant migration (off 0039): `block_crops.canopy_size_class` + `growth_stage_locked`; backend CRUD + validation against resolved size classes; data-safe downgrade.
- **PR-B2** Frontend: size dropdown on the block-crop form (options = resolved `size_classes` for the block's `crop_path`), lock-stage toggle, growth-stage display + manual-set control; i18n en/ar.

**Track C — Auto-advance**
- **PR-C1** `phenology.advance_growth_stages` beat task (perennial DOY + annual days/GDD), respects lock, writes `source='derived'`; unit tests (DOY wrap, GDD accumulation, idempotency, lock honoured).

**Track D — Engine + mango rules**
- **PR-D1** Extend `BLOCK_FIELDS` + service population with `soil_texture`/`salinity_class`/`canopy_size_class`; tests.
- **PR-D2** Mango tree seeds (NDMI moisture, stress-induction = NDMI high **AND** cool temp at `pre_flowering`, NDRE post-harvest, SAVI-for-small-canopy/sandy, soil-aware) with evidence/citations.

**Track E — Plan templates + integration** *(builds on A; un-parks the prior doc)*
- **PR-E1** Plan-template data model (public 3 tables incl. `anchor=stage`/`stage_code`; tenant column adds incl. `anchored_stage_code`); migrations chained off the new heads; data-safe downgrades.
- **PR-E2** Apply engine + resolver with stage-date resolution (annual + perennial) + tenant endpoints (appliable/preview/apply) + caps; tests (stage-anchor math per cycle, path-prefix gate, idempotent re-apply).
- **PR-E3** Platform authoring API + `/platform/plan-templates` UI (cascading crop picker, milestones, activities with Start/Milestone/**Stage** anchor + stage picker, timeline preview).
- **PR-E4** Tenant apply wizard + board integration (badges, `source`/`anchored_stage_code`); i18n.
- **PR-E5** Seed a mango stage-anchored starter template + docs + polish.

**Dependency order:** A → (B, C, D) in parallel → E. A is the hard prerequisite for C, D2, and E (all consume resolved stages); B1 (lock flag) gates C1.

---

## 6. Open items / follow-ups (non-blocking)

- **Per-block GDD for non-base-10 crops:** the cumulative column is base-10; crops with other `gdd_base_temp_c` need recompute from daily `temp_min/max`. V1 mango is calendar (no GDD); potato is base-10. Flag a helper if a third crop needs a different base.
- **Event-driven re-anchoring for perennials:** mango `post_harvest_flush` ideally triggers off the *actual* harvest event (`BlockCrop.actual_harvest_date`) rather than pure calendar. V1 = calendar; consider an event hook later.
- **Stage-overlap authoring guardrails:** warn (not block) on overlapping windows; resolver deterministically picks highest `order`.
- **Template versioning:** still deferred (apply snapshots into `plan_activities`, so edits don't mutate applied plans).
- **Manual-vs-derived UX:** consider auto-setting `growth_stage_locked=true` for a configurable window after a manual transition, so a manual set isn't immediately overwritten by the next daily run.
```
