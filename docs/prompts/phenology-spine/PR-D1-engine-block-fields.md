# PR-D1 — Expose soil + canopy size to the rules engine

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §3.1 (Gaps 1 & 3). **Depends on:** PR-B1.

## Goal
Make `soil_texture`, `salinity_class`, and `canopy_size_class` usable as `block`-source condition refs in decision trees.

## Backend
1. **`shared/conditions/models.py`:** extend `BLOCK_FIELDS` from
   `("crop_category","growth_stage","crop_path","crop_strain")` to also include
   `"soil_texture"`, `"salinity_class"`, `"canopy_size_class"`.
2. **Populate** these in the recommendations service where `block_attributes` is built — it already loads the current `BlockCrop` + `Block`. Add `Block.soil_texture`, `Block.salinity_class`, `BlockCrop.canopy_size_class` to the dict. `ConditionContext.from_block_signals` copies the dict verbatim → pass-through is automatic.
3. No evaluator change needed — `eq`/`ne`/`in` already handle categorical strings. Missing/null still short-circuits to False (existing behaviour).

## Tests
- a tree condition `block.soil_texture == 'sandy'` evaluates true/false against a context with/without the field.
- `block.canopy_size_class in ['small']` works.
- snapshot/evaluation captures the new refs.

## Acceptance
- New refs resolvable in trees; existing trees unaffected; CI green.
