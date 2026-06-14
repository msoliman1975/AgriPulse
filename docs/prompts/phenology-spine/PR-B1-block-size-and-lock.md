# PR-B1 — Block-level canopy size + stage lock (backend)

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §1.3. **Depends on:** tenant head `0039`.

## Goal
Add the per-planting size pick and the auto-advance lock flag to `block_crops`, with validation.

## Backend
1. **Tenant migration off 0039:** `ALTER TABLE block_crops ADD`:
   - `canopy_size_class` TEXT NULL
   - `growth_stage_locked` BOOLEAN NOT NULL DEFAULT false
   Data-safe downgrade (drop columns). ASCII migration file.
2. **Model:** add both fields to `BlockCrop` (`farms/models.py`).
3. **Schemas + CRUD:** accept `canopy_size_class` + `growth_stage_locked` on block-crop create/update. **Validate** `canopy_size_class` is one of the **resolved** `size_classes` codes for the block's `crop_path` (use PR-A1 `resolve_size_classes` + the catalog lookup); null allowed.
4. **Repository:** persist both; include in read DTOs.

## Tests
- create/update block-crop with valid size class → ok; with a code not in the resolved list → 422.
- lock flag round-trips and defaults to false.
- migration upgrade+downgrade roundtrip.

## Acceptance
- `block_crops` has the two columns live; API accepts/validates them; CI green.
