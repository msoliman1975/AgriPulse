# PR-A1 — Phenology shape validation + size-class lookup

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §1.1, §1.2. **Depends on:** public head `0031`.

## Goal
Turn the opaque `phenology_stages` JSON into a **validated** shape, and add a parallel **`size_classes`** taxonomy lookup with the same resolver pattern. No tenant changes.

## Backend
1. **Pydantic shapes** (in `farms/schemas.py` or a new `farms/phenology.py`):
   - `PhenologyStage`: `code` (str), `name_en`, `name_ar`, `order` (int), `advance` (discriminated union by `mode`):
     - `days_from_planting` → `start_day:int, end_day:int`
     - `gdd_from_planting` → `start_gdd:float, end_gdd:float`
     - `calendar_doy` → `start_doy:str (MM-DD), end_doy:str (MM-DD)` (wrap allowed)
     - `manual` → no params
   - `PhenologyStages`: `{stages: list[PhenologyStage]}`; validate unique `code` + unique `order`.
   - `SizeClass`: `code, name_en, name_ar, order`. `SizeClasses`: `{classes: list[SizeClass]}`; unique codes.
2. **Cross-validation vs `Crop.is_perennial`** at catalog write time (the crop/variety/strain authoring API): perennial ⇒ every stage mode ∈ {calendar_doy, manual}; annual ⇒ ∈ {days_from_planting, gdd_from_planting, manual}; `gdd_from_planting` requires `crop.gdd_base_temp_c`. Overlapping windows → **warn** (log), don't hard-fail; resolver picks highest `order`.
3. **Public migration off 0031:** add JSONB columns `crops.size_classes`, `crop_varieties.size_classes_override`, `crop_variety_strains.size_classes_override` (all nullable). Data-safe downgrade (drop columns).
4. **Resolver:** add `resolve_size_classes(*, crop_classes, variety_override, strain_override)` to `farms/crop_thresholds.py` — wholesale deepest-wins, mirror `resolve_phenology_stages`; return `[]` when none.
5. **Read endpoints:** expose resolved stages + size classes per `crop_path` (extend the existing crop-detail/catalog API, or add `GET /v1/crops/{path}/phenology` + `/size-classes`). Used by the auto-advancer, engine, block UI, and plan-template authoring.
6. Validate `phenology_stages` / `size_classes` JSON against the new Pydantic models in the existing crop/variety/strain create+update service paths.

## Tests
- Pydantic validation: each mode's required params; rejects wrong mode for is_perennial; rejects dup codes/orders.
- `resolve_size_classes`: crop-only, variety override replaces, strain override replaces, none → [].
- Migration upgrade+downgrade roundtrip.

## Acceptance
- Authoring a crop with a malformed stage list is rejected with a clear error.
- `GET …/phenology` and `…/size-classes` return resolved lists for a path.
- CI green; migration roundtrips clean.
