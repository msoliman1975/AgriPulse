# PR-E2 — Plan-template apply engine (stage-anchored) + tenant endpoints

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §4.1; `plan-templates-implementation.md` §2-§3. **Depends on:** PR-E1, PR-A2.

## Goal
Resolve a template to dated `plan_activities` per block, including **stage-anchored** activities, and expose appliable/preview/apply endpoints. Idempotent re-apply.

## Resolver (pure fn, unit-tested)
`(template, block_start_date, block_crop_ctx) → [{activity_type, scheduled_date, duration_days, anchored_stage_code?, defaults…}]`:
- `anchor=start` → `block_start_date + offset_days`.
- `anchor=milestone` → `block_start_date + milestone.day_from_start + offset_days`.
- `anchor=stage` → resolve the stage **start date for this block**, then `+ offset_days`; set `anchored_stage_code`:
  - **Annual block** (`is_perennial=false`) → `planting_date + stage.start_day` (or GDD→date by accumulating farm GDD to `start_gdd`).
  - **Perennial block** (`is_perennial=true`) → map `stage.start_doy` onto the plan's `season_year` (wrap-aware) → concrete date.
  - Resolve stages via `resolve_phenology_stages` for the block's `crop_path` (same path the engine/advancer use). If `stage_code` not in resolved stages → skip the activity + record a warning in the apply result.

## Service `apply_template({template_id, farm_id, season_label, season_year, blocks:[{block_id,start_date}]})`
1. Hard-gate match per block via `path_matches(template.crop_path, block_crops.crop_path)` (reuse `shared/crop_taxonomy.py`).
2. Find-or-create `VegetationPlan(farm, season_label, season_year)`; set `applied_template_id`.
3. Idempotent regen per block: `DELETE plan_activities WHERE plan_id=… AND block_id=… AND applied_template_id=template AND status='scheduled'`, then insert fresh with `source='template'`, `applied_template_id`, `template_activity_id`, `anchored_stage_code`, `status='scheduled'`. Preserve `source='manual'` + completed/in-progress.
4. **Preview** = same resolution, no writes.

## Endpoints (cap `plan_template.apply`, tenant, farm-scoped)
- `GET /v1/plan-templates/appliable?farm_id=` — published templates matching the farm's block crops; returns matching blocks + `planting_date` defaults.
- `POST /v1/plan-templates/{id}/preview` — dry-run schedule (per block, incl. stage-anchor dates + any skipped activities).
- `POST /v1/plan-templates/{id}/apply` — runs engine; returns `{plan_id, per-block counts, skipped, total}`.
- Add caps `plan_template.read` + `plan_template.apply` to the caps yaml.

## Tests
- resolver: start/milestone/stage anchors; annual vs perennial stage-date math; negative offset; missing stage → skip+warn.
- idempotent re-apply preserves manual/completed; path-prefix gate (crop/variety/strain depth).

## Acceptance
- preview + apply work against a seeded template on a mango block; stage-anchored activity lands on the resolved stage date; re-apply is idempotent; CI green.
