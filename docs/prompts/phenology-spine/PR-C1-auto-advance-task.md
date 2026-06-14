# PR-C1 — Growth-stage auto-advance beat task

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §2. **Depends on:** PR-A2 (seeded stages), PR-B1 (lock flag).

## Goal
A daily task that moves each block to its computed phenology stage, writing `GrowthStageLog(source='derived')`, honouring the lock flag. The recommendation engine needs **no** change (it already reads `growth_stage`).

## Backend
1. **New beat task** `phenology.advance_growth_stages` (register in `workers/beat/main.py`; schedule daily, after weather-derive so GDD is fresh).
2. **Logic per active current `BlockCrop`** (`is_current=true`, not harvested):
   - Skip if `growth_stage_locked`.
   - Resolve phenology stages for `crop_path` (`resolve_phenology_stages`). Skip if none.
   - Compute current stage code:
     - **`is_perennial=true`** → evaluate `calendar_doy` windows against today `MM-DD`, **wrap-aware** (reuse/mirror the DOY-wrap logic from `indices/baselines.py`). Pick highest `order` whose window contains today.
     - **`is_perennial=false`** → from `planting_date`: `days_from_planting` ⇒ elapsed days in `[start_day,end_day)`; `gdd_from_planting` ⇒ cumulative GDD from planting using farm `WeatherDerivedDaily` + crop base/upper temp (base-10 cumulative reusable directly when `gdd_base_temp_c==10`; otherwise recompute from daily `temp_min/max` — leave a TODO helper for non-base-10 per proposal §6).
   - If computed ≠ `BlockCrop.growth_stage`: call existing `record_growth_stage_transition(stage=…, source='derived')` (appends log + mirrors onto block_crop in one txn).
   - Idempotent: no-op when already on computed stage.
3. Structured logging: counts of evaluated / advanced / skipped(locked) / no-stages.

## Tests
- perennial DOY match incl. wrap (Dec→Jan window on a Jan date and a Dec date).
- annual days + GDD threshold crossing.
- lock honoured (locked block never advances).
- idempotency (second run = 0 transitions).
- no phenology → skipped cleanly.

## Acceptance
- Task runs without error against seeded mango + potato; a mango block lands on the stage matching today's date; rerun is a no-op. CI green.
