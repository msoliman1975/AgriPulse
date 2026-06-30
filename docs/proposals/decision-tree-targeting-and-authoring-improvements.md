# Decision Tree — Multi-Axis Targeting + Authoring Improvements

**Status:** Proposed (2026-06-29) · **Sequenced before** per-cell execution scope
**Owner:** Mohamed Soliman

## Locked decisions
- **Location granularity:** Country only (Egypt, Jordan, …). New `public.countries` catalog; `Farm.country_id`; blocks inherit country via farm.
- **Soil type:** Reuse the existing closed 7-value `soil_texture` vocabulary (`sandy, sandy_loam, loam, clay_loam, clay, silty_loam, silty_clay`). No new catalog / admin UI.
- **Sequencing:** Ship these DT improvements first; per-cell execution scope extends the resulting targeting layer afterward.

## Problem
Today a Decision Tree targets **exactly one** crop (`decision_trees.crop_path` single-prefix, matched in `recommendations/service.py:206-220`), authored as a free-text crop code (`DecisionTreeCreatePage.tsx:143`). There is no location or soil targeting. The engine runs every tree against every block whose crop matches. Authoring is half-YAML, the "Scientific basis" band eats canvas real-estate, several condition fields are free text, and the bilingual form has gaps.

## Target design

### Targeting model (multi-axis)
A tree carries three **multi-value** targeting sets:
- `crop_paths: text[]` — hierarchical path prefixes (reuses `crop_taxonomy.path_matches`).
- `country_codes: text[]` — ISO-ish country codes from the new catalog.
- `soil_textures: text[]` — subset of the existing 7-value enum.

**Matching semantics (critical for coverage safety):**
- **Empty set on an axis = "matches any"** on that axis. A legacy tree with all sets empty keeps matching every block.
- **AND across axes, OR within an axis.** A block matches a tree iff:
  `(crop_paths empty OR any prefix matches block crop) AND (country_codes empty OR block.country ∈ set) AND (soil_textures empty OR block.soil_texture ∈ set)`.
- **Crop is required in the UI** (per requirement) but stored as a non-empty `crop_paths`. DB stays nullable/empty-tolerant so legacy + crop-agnostic platform trees still evaluate.

> **Coverage guardrail:** because country is net-new, every block starts with `country_id = NULL`. A tree with a non-empty `country_codes` would match **zero** blocks until farms are backfilled. The matcher MUST treat a block with unknown country as *not matching* a country-filtered tree — so we backfill `Farm.country_id` (Egypt default for existing agrosina/demo tenants) **before** enabling country filters, and surface "0 blocks match" in dry-run.

### Country catalog (net-new)
- `public.countries` — `code` (PK, e.g. `EG`/`JO`), `name_en`, `name_ar`, `is_active`. Seed Egypt + Jordan initially.
- `Farm.country_code` FK → `public.countries.code` (nullable). Blocks resolve country via parent farm (no block column).
- Block→country resolver alongside the existing crop/soil resolution in `service.evaluate_block` context build.
- Admin management: minimal platform CRUD (mirror the crops admin pattern) — list/add/retire countries. Picker via a new `frontend/src/api/countries.ts`.

## PR breakdown

### Track 1 — Targeting foundation (backend-led, gates the engine)
- **PR-1 Country catalog.** `public.countries` migration + seed (EG, JO); ORM + repo; `Farm.country_code` column + migration; tenant farm read/write threads country; backfill script sets existing farms → `EG`. Platform admin CRUD + API.
- **PR-2 Multi-axis tree columns.** `decision_trees`: add `crop_paths text[]`, `country_codes text[]`, `soil_textures text[]` (keep legacy `crop_path`/`crop_id` readable; migrate existing single `crop_path` → `crop_paths`). Loader/YAML validation accepts the arrays; schemas + create/update API carry them. Crop required at API + UI layer (non-empty `crop_paths`).
- **PR-3 Engine matcher.** Replace the single-prefix check in `service.py:206-220` with the AND/OR multi-axis matcher; add `block.country_code` to the context build; unit tests for empty-set=any, OR-within, AND-across, unknown-country exclusion.

### Track 2 — Dry-run + authoring UX (frontend-led)
- **PR-4 Dry-run block dropdown + match filtering.** Replace free-text UUID input (`CanvasDryRunPanel.tsx:48`, `DecisionTreeEditorPage.tsx:290`) with a block **dropdown showing block names**, populated only with blocks that match the tree's crop/country/soil sets; descriptive empty state ("No blocks match this tree's crop/country/soil — adjust targeting or assign blocks"). Backend: dry-run candidate-blocks endpoint reusing the PR-3 matcher.
- **PR-5 Targeting pickers in authoring.** Create/edit form: required **multi-select crop** (reuse `CropPathFilter` cascading picker), **multi-select country** (new picker), **multi-select soil texture** (7 fixed values). Remove the free-text crop input. Show readable crop/country names in the list page (today it prints a truncated UUID, `DecisionTreeListPage.tsx:73`).
- **PR-6 Condition value dropdowns.** Wire `index_code` (indices catalog), signal `code`, and grid `index_code` from free text → dropdowns in `ConditionBuilder.tsx`, sourced from the existing catalogs; keep TS lists in lockstep with `backend/app/shared/conditions/`.
- **PR-7 Scientific basis → tooltip.** Demote `ProvenancePanel` from the full-width band (`DecisionTreeViewerPage.tsx:563`) to a tooltip/popover trigger near the node/leaf; reclaim canvas vertical space.
- **PR-8 Canvas real-estate.** Widen the viewer page to max width, ensure the tree renders without horizontal scroll (`TreeCanvas.tsx` / `layout/treeLayout.ts`); collapse side panels when idle.
- **PR-9 Bilingual gap-fill.** Structured `name_ar`/`description_ar` inputs in the create/edit form (today only via raw YAML); Arabic surfaced in the list + metadata panel; verify RTL on the new pickers.

### Nav (folded into PR-5/PR-8)
- DT list/setup already lives under `/settings/decision-trees`. Promote it to a direct, always-visible Settings menu entry (it currently shows only with `decision_tree.manage`); confirm IA with the Settings hub.

## Sequencing & dependencies
- Track 1 is prerequisite-free and gates the engine behavior. **PR-1 → PR-2 → PR-3 in order.**
- Track 2 can start in parallel after PR-2 lands (UI needs the array fields); PR-4's match-filtering needs PR-3.
- **Do not enable country filters in any seeded tree until farm `country_code` backfill (PR-1) has run**, else those trees match zero blocks.

## Relationship to per-cell scope (next phase)
Per-cell execution changes the *iteration unit* (cells instead of blocks); this work changes the *targeting model*. They compose: per-cell iterates "the cells of every block that matches the tree's crop/country/soil sets." Building targeting first avoids reworking the matcher and authoring UI twice.

## Open / deferred
- Whether country should later deepen to governorate/region (deferred; country chosen now).
- Admin-editable soil catalog (deferred; reuse enum now).
- Per-tree `scope: block|cell` flag and notification grouping — belong to the per-cell phase.
