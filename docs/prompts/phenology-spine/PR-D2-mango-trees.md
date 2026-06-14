# PR-D2 — Mango decision-tree seeds (corrected agronomy)

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §3.2. **Depends on:** PR-A2 (stages), PR-D1 (block fields).

## Goal
Seed mango decision trees that use the right indices and stage gating, and that are study-backed (carry `evidence` citations).

## Trees (YAML under `recommendations/seeds/`, targeted by `crop_path` `mango` or per-variety; stage-gated via `block.growth_stage`)
1. **Moisture on NDMI, not NDWI.** All mango moisture/water-stress logic uses `index_code: ndmi` (NIR−SWIR). Engine `ndwi` = McFeeters surface water = wrong for leaf water. Note in `evidence`/`transferability` that NDMI needs SWIR → Sentinel-2 only, not PlanetScope 3m.
2. **Stress-induction warning** (gate `growth_stage == 'pre_flowering'`): fire **only** when `all_of([ NDMI high (well-watered), weather min air temp in the cool induction band ])` → warn "high moisture during the cool induction window may drive vegetative flush instead of flowering." Study-backed: water stress alone at warm temp → vegetative only; cool temp (~15 °C) required. Use `weather` `forecast_*`/`derived_*` min-temp refs + a tunable `params` threshold.
3. **NDRE post-harvest flush** (gate `growth_stage == 'post_harvest_flush'`): low NDRE → nitrogen/chlorophyll deficiency alert (NDRE penetrates the saturating mango canopy where NDVI flattens).
4. **Canopy-size / soil aware health:** when `block.canopy_size_class == 'small'` OR `block.soil_texture == 'sandy'` → evaluate the **SAVI** branch; else NDVI. Explicit branches (no engine-level auto-switch).
5. Keep the **`baseline_deviation` z-score "sudden drop → stress"** detector as the core self-calibrating alert. **Do NOT** seed the AI-improvised absolute-value matrix.

Each tree: `evidence.confidence` + `citations` (flowering-induction temp×water study; NDVI-saturation/NDRE; SAVI/L=0.5) and `transferability.egypt`. Use `params` for tunable thresholds so tenants can override.

## Tests
- loader compiles each YAML; predicate trees validate.
- engine eval: stress-induction fires only when NDMI-high AND cool; NDRE alert fires on low NDRE at post_harvest_flush; size/soil branch picks SAVI vs NDVI.

## Acceptance
- Trees seed + compile; targeted evaluation produces expected outcomes on a seeded mango block; CI green.
