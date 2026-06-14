# PR-B2 — Block-crop form: size dropdown + stage lock + stage display (frontend)

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §1.3, §5 (B2). **Depends on:** PR-B1, PR-A2.

## Goal
Let users pick canopy size (from the taxonomy list, not free text), lock the growth stage, and see the current stage.

## Frontend
1. In the block-crop edit form (the block drawer / DetailPanel area used on `/labs/map`):
   - **Canopy size**: a `<select>` whose options are the **resolved `size_classes` for the block's `crop_path`** (fetch from PR-A1 `…/size-classes`). Show `name_en`/`name_ar` per locale; value = `code`. Empty option allowed.
   - **Lock growth stage**: a toggle bound to `growth_stage_locked`.
   - **Growth stage**: display the current `growth_stage` (resolve label from the crop's phenology stages) + keep the existing manual "set stage" control if present; show `growth_stage_updated_at` and source if available.
2. Wire to the block-crop update API (PR-B1 fields). Add `api/` calls if needed.
3. i18n keys en + ar (RTL).

## Acceptance
- Selecting a size persists and reloads correctly; options change with the block's crop path.
- Toggling lock persists. Current stage renders with a human label.
- tsc + eslint clean.
