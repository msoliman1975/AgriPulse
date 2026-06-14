# PR-A2 — Seed mango (5 varieties) + potato phenology & size classes

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §1.1, §1.2, §5 (Track A2). **Depends on:** PR-A1.

## Goal
Seed real, validated taxonomy data so every downstream track (auto-advance, engine, plan templates) has something to resolve.

## Data to seed (public migration/loader, idempotent upsert by code/path)
### Mango (`is_perennial=true`, advance mode = `calendar_doy`)
- Crop `mango` with default phenology stages + default size classes (small `<2 m` / medium `2–4 m` / large `>4 m`).
- 5 varieties under mango: **`keitt`, `yasmina`, `sukkary`, `zebda`, `crimson`** (paths `mango.keitt` … `mango.crimson`).
  - Stage list per variety (calendar-DOY windows for Egypt; varieties may override windows where they differ — e.g. Keitt is late-season). Stages: `veg_flush` → `pre_flowering` (stress-induction window, ~Dec–Jan) → `flowering` → `fruit_development` → `post_harvest_flush`. Give each `code, name_en, name_ar, order, advance{mode:calendar_doy,start_doy,end_doy}`.
  - Where a variety doesn't differ from the crop default, leave `phenology_stages_override` null (resolver falls back).
  - Local-vs-foreign size defaults: Sukkary/Zebda (large local) vs Keitt/Yasmina/Crimson (high-density, smaller) — set sensible default size class lists / labels.
- **Do NOT seed absolute index-threshold matrices** (the AI-improvised tables are not study-backed; the engine self-calibrates via baselines).

### Potato (annual exemplar, `is_perennial=false`)
- Stages with `advance.mode` ∈ {`days_from_planting` or `gdd_from_planting`} (use `gdd_from_planting` if `gdd_base_temp_c` set, else days): emergence → vegetative → tuber_initiation → tuber_bulking → maturation. This proves the annual path of the auto-advancer.

## Notes
- Arabic names required (`name_ar`) — RTL app.
- Keep seed idempotent (re-runnable). Use the loader pattern if catalog seeds use one; else a data migration.

## Tests / acceptance
- After seed, `GET …/phenology` for `mango.keitt`, `mango.sukkary`, `potato` return the resolved stage lists; `…/size-classes` returns the size lists.
- All seeded JSON passes PR-A1 validation (perennial→DOY, annual→days/GDD).
- Migration roundtrips clean (downgrade removes seeded rows or is data-safe per CI rules).
