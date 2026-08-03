# Implementation Plan — Closing the Decision-Tree / Recommendations Engine Gaps for the Scientific Agronomic Knowledge Base

**Status:** ✅ **5 of 6 gaps CLOSED and shipped to `main`.** Only **G6** (authoring UI) remains open.
**Date:** 2026-06-06 (original plan) · **status verified against `origin/main` 2026-08-03**

> **Read this before acting on anything below.** The plan body is preserved as the original
> design record — it still reads as forward-looking ("we will…"), but most of it is now
> **built**. Every KB PR was **squash-merged**, which rewrites the SHA, so the old
> `feat/kb-*` branches looked unmerged (`~330 behind main`) long after their content
> landed. Those branches and their worktrees were deleted 2026-08-03; do not resurrect
> them — their diffs now *revert* later work (#296 targeting, #315 archive/restore).

### Gap status as built

| # | Gap | Status | Shipped as |
|---|-----|--------|-----------|
| G1 | Temporal/trend fields | ✅ closed | #199 NDMI `7109f54`, #200 index trends `a7ab688`, #208 signal trends `f388bc7` |
| G2 | Crop growth-stage model | ✅ closed (exceeded) | #202 `a9e530d` exposed `block.growth_stage`; **#238 phenology spine** went further |
| G3 | 4-horizon recommendations | ✅ closed | #197 `0ce7c55` (tenant migration 0037 `recommendations.actions`) |
| G4 | Evidence / transferability | ✅ closed | #197 `0ce7c55` |
| G5 | Weather climatology baseline | ✅ closed *sideways* | #271 weather-indices first-class — `baseline_deviation` z-score vs day-of-year climatology |
| G6 | Authoring UI nesting / `not` / `between` / `in` | ❌ **OPEN** | see § 7 |

**Two deliberate deviations from this plan, as built:**

1. **§ 4 P1-A said** store `evidence`/`transferability` as new JSONB *columns* on
   `decision_tree_versions` behind a public migration. **As built** they ride inside the
   existing `tree_compiled` JSONB — parsed/validated in `loader.py`, **no migration**.
2. **§ 5 P2-A said** *persist* index trends via a sweep into a sibling table. **As built**
   they are computed at context-load time by the pure `indices/trends.py::compute_trend`
   — **no new table, no sweep**. Same for signal trends in `signals/snapshot.py`.

**The § 8 blocker is gone.** Content seeding of stage-gated N/P/K was parked because
`growth_stage` was free text with no canonical vocabulary. #238 created exactly that:
per-crop `phenology_stages` JSONB on crops/varieties/strains with validation
(`farms/phenology.py`), a daily auto-advance Beat task (`farms/phenology_advance.py`),
`growth_stage_logs` + `growth_stage_locked`, seeded for mango + potato (migration 0033)
and date palm (0038). Stage-gated nutrient rules are now unblocked.

**Content track as built:** mango 6 seed trees, potato 3 (#198 salinity / heat / frost),
**date palm 0**, N/P/K none.

**Author context:** Driven by the "Scientific Agronomic Knowledge Base and Decision Tree Catalog" research task (Mango / Date Palm / Potato; Egypt → Middle East → global). That research produces, per condition: signals, *temporal* signal relationships, a YAML decision-tree candidate, thresholds-with-sources, 4-horizon recommendations, confidence, transferability scores, and citations.

This plan turns the gap analysis into a phased, PR-level implementation roadmap so the seeded knowledge base can actually be expressed in our engine.

---

## 1. Background — what we have today

Canonical engine: the **decision-tree engine** (`backend/app/modules/recommendations/`). The legacy rules engine is sunset (tables dropped in migrations `0025` / `0033`); trees own both **alerts** (`kind: alert`) and **recommendations** (`kind: recommendation`).

Core pieces (audited 2026-06-06):

- **Evaluator** — `recommendations/engine.py`. Pure, deterministic, **point-in-time** tree walk. `_MAX_STEPS = 64`. Captures full visited path for explainability.
- **Condition AST** — `shared/conditions/evaluator.py` + `shared/conditions/models.py`. Operators: `lt le gt ge eq ne between in` + boolean `all_of any_of not`. Missing data → `None` → predicate `False` (permissive).
- **Signal sources** in `ConditionContext` (`shared/conditions/context.py`):
  - `indices` — keys `mean`, `baseline_deviation` (z-score vs day-of-year baseline). 6 indices live: NDVI, NDRE, EVI, GNDVI, SAVI, NDWI.
  - `weather` — scopes `latest_observation`, `forecast_24h`, `forecast_72h`, `derived_today`, `derived_yesterday`. Fields incl. ET₀, precip (+ `precip_mm_7d/30d`), temp, humidity, wind, solar, GDD.
  - `signals` — custom tenant signals; keys `value_numeric/categorical/event/boolean`; def-level aggregation `latest/mean/median/max/min` + optional `aggregation_window_days`.
  - `block` — only `crop_category` today.
  - `params` — tree-declared, tenant-overridable parameters.
- **Outcome / Recommendation** — single `action_type`, single `text_en/text_ar`, free-form `parameters` JSONB, `confidence` (0–1), `severity` (info/warning/critical), `valid_for_hours`, `evaluation_snapshot`.
- **Loader** — `recommendations/loader.py` compiles YAML → JSON, validates, versions immutably into `decision_tree_versions`; `sync_from_disk()` seeds `seeds/*.yaml` at startup.
- **Authoring** — canvas + `ConditionBuilder` (V1: single comparison or one level of `all_of`/`any_of`; `not`/nested/`between`/`in` require raw YAML).
- **Crop scoping** — `crop_id` on a tree (NULL = crop-agnostic).
- **Notifications** — fan-out to in_app / email / webhook on `RecommendationOpenedV1` / `AlertOpenedV1`.

## 2. The six gaps

| # | Gap | Impact | Closes | Phase |
|---|-----|--------|--------|-------|
| G1 | No temporal/trend operators — evaluator is point-in-time; can't express "NDMI decreasing", deltas, slope, or cross-signal divergence | **Highest** — most of the catalog's "early detection" logic | P2 |
| G2 | No crop growth-stage model — conditions can only see `crop_category`, not phenological stage | **High** — most Mango/Date-Palm conditions are stage-keyed | P3 |
| G3 | Recommendations are single-action, not Immediate/Short-term/Long-term/Monitoring | Medium | P1 |
| G4 | No evidence/source/reference/transferability/evidence-confidence metadata | Medium (credibility of a *scientific* KB) | P1 |
| G5 | No weather climatology baseline — can't express "rainfall deficit" / "ET₀ above seasonal average" relative to normal | Medium | P2b |
| G6 | Authoring UI can't express nested groups / `not` / `between` / `in` | Low (platform seeds via YAML) | P4 |

**Design principle that shapes everything below:** *model trends and stages as data (new resolvable keys/fields), not as new operators.* This keeps the evaluator pure and point-in-time, so existing `lt/gt/eq/in` predicates handle them (e.g. `ndmi.trend_direction == "falling"`, `growth_stage in [vegetative, flowering]`). The evaluator is touched as little as possible.

---

## 3. Phasing overview

```
P1  Knowledge-base schema readiness   (additive, low risk, no evaluator change)
      ├─ G4  Evidence / citation / transferability metadata
      └─ G3  4-horizon structured recommendations
P2  Temporal capability               (biggest catalog unlock)
      ├─ G1  Trend/delta derived fields for indices + custom signals
      └─ G5  Weather climatology baselines (P2b — data-heavy, can trail P2a)
P3  Phenology                         (domain-heavy: annual + perennial)
      └─ G2  Crop growth-stage resolver
P4  Authoring + polish
      └─ G6  ConditionBuilder nesting/not/between/in
Content track (parallel)  Seed the catalog as tree YAMLs, gated per phase
```

Rationale for order:
- **P1 first** — purely additive schema; lets us seed *static-threshold* conditions (much of the Potato nutrient/salinity set, absolute heat/cold thresholds) with full scientific metadata and rich recommendations *immediately*, before any temporal/stage work.
- **P2 second** — unlocks the bulk of the catalog (every "decreasing/increasing/deficit" relationship).
- **P3 third** — most domain-heavy and the only one needing new reference data per crop+region; unblocks Mango/Date-Palm stage-specific logic.
- **P4 last** — convenience for tenant self-authoring; platform seeding doesn't need it.

---

## 4. Phase P1 — Knowledge-base schema readiness

> **✅ SHIPPED (#197 `0ce7c55`).** Note deviation 1 in the status header: evidence and
> transferability ride inside `tree_compiled`, not new columns — there was no public
> migration. P1-B did add tenant migration 0037 for `recommendations.actions`.

Additive only. No evaluator change. No behavior change for existing trees (all new fields optional, default empty).

### P1-A — Evidence & transferability metadata (G4)

**Goal:** every seeded condition carries its scientific provenance and applicability, queryable and displayable.

**Schema (illustrative — finalize in PR):** extend the tree YAML head + compiled JSON:

```yaml
evidence:
  confidence: high          # very_high | high | medium | low  (evidence quality, distinct from result confidence)
  citations:
    - source_type: peer_reviewed   # peer_reviewed | fao | usda | extension | university | remote_sensing
      title: "..."
      doi: "10.xxxx/yyyy"          # optional
      url: "..."                   # optional
      year: 2019
  notes: "Threshold contested above 40 °C; see ..."   # free-text uncertainty statement
transferability:
  egypt: high               # very_high | high | medium | low | not_applicable
  middle_east: high
  global: medium
```

**Touchpoints:**
- `recommendations/loader.py` — `compile_tree()` parse + validate the optional `evidence` / `transferability` blocks (enum validation; all optional).
- `recommendations/models.py` — store on `decision_tree_versions` (JSONB columns `evidence`, `transferability`), immutable with the version.
- Migration (public) — add `evidence JSONB`, `transferability JSONB` to `decision_tree_versions`.
- API schemas — surface in tree read/detail responses.
- (Optional) denormalize `evidence_confidence` + citations snapshot onto `recommendations` row so the inbox/detail can show "why we believe this" without a tree lookup → migration (tenant) adds `evidence JSONB` to `recommendations`.
- Frontend — tree detail view + recommendation detail render citations / transferability / evidence-confidence badge.

**Note:** `applicable_regions` already exists on the tree but is **not enforced** at evaluation. Decide in PR whether `transferability`/regions become an *evaluation filter* (skip tree if block region not applicable) or remain **display/governance only**. Recommended: display/governance only in P1; evaluation-time region gating is a separate, riskier decision (needs block→region mapping).

**Acceptance:** a seed YAML with full `evidence`+`transferability` compiles, versions, and renders in UI; trees without the blocks behave exactly as before.

### P1-B — 4-horizon structured recommendations (G3)

**Goal:** a leaf can emit Immediate / Short-term / Long-term / Monitoring actions, not just one text blob.

**Schema (illustrative):** extend leaf `outcome`:

```yaml
outcome:
  kind: recommendation
  action_type: irrigate
  severity: warning
  confidence: 0.75
  text_en: "Early water stress likely."     # keep as one-line summary
  text_ar: "..."
  actions:                                    # NEW, optional
    immediate:
      - text_en: "Increase irrigation frequency by one cycle."
        text_ar: "..."
    short_term:
      - text_en: "Verify soil moisture at 30 cm."
        text_ar: "..."
    long_term: []
    monitoring:
      - text_en: "Track NDMI daily for 7 days."
        text_ar: "..."
```

**Touchpoints:**
- `recommendations/engine.py` — `TreeOutcome` gains optional `actions` dict; pass through unchanged (no logic).
- `recommendations/loader.py` — validate `actions` shape (4 known horizons, each a list of `{text_en, text_ar?}`); all optional.
- `recommendations/models.py` + migration (tenant) — `recommendations.actions JSONB`.
- Notifications — `subscribers.py` template rendering: summary stays as subject/body; categorized actions rendered into the body for in_app/email. Update `notification_templates` content.
- Frontend — recommendation detail renders four labelled sections; authoring `NodeDetailsPanel` edits them.
- i18n — section labels (immediate/short_term/long_term/monitoring) en + ar.

**Acceptance:** a seed with `actions` produces a recommendation whose detail view shows four sections; legacy single-text trees still render (summary only).

**P1 effort:** ~2 PRs (P1-A, P1-B). Low risk, additive, independently shippable.

---

## 5. Phase P2 — Temporal capability (G1, G5)

> **✅ SHIPPED.** NDMI #199, index trends #200, signal trends #208; G5 closed separately by
> #271 (weather indices first-class). Note deviation 2: trends are **computed at load**
> by a pure function, not persisted via a sweep — there is no trend table and no trend
> Beat job. `INDICES_KEYS` on `main` is `mean, baseline_deviation, slope, delta,
> trend_direction`.

The big unlock. Trends become **data**, exposed as new resolvable keys; the evaluator stays point-in-time.

### P2-A — Trend/delta derived fields for indices (G1)

**Approach decision:** *persist* trend fields via a sweep (reuse the existing `indices/baselines.py` weekly-sweep pattern) rather than computing in the evaluator. Benefits: keeps evaluation cheap & point-in-time; reusable by the Insights UI; avoids history queries in the hot path. Cost: extra storage + a sweep job.

**New fields per (block, index, time)** — stored either as new columns on `block_index_aggregates` or a sibling `block_index_trends` table (decide in PR; sibling table avoids bloating the hot aggregate row):
- `delta_7d`, `delta_14d` — `mean(now) − mean(t−N)`
- `slope_14d` — linear-regression slope of `mean` over the window (units/day)
- `trend_direction` — categorical `rising | stable | falling`, derived from `slope` vs a configurable dead-band

**Expose** as new index keys: `{source: indices, index_code: ndmi, key: trend_direction}` (categorical → `eq`/`in`), `key: slope_14d` / `delta_14d` (numeric → `lt/gt/between`).

> Note on NDMI: the research prompt leans heavily on **NDMI** (moisture). We currently compute **NDWI** (McFeeters, green/NIR) but **not NDMI** (NIR/SWIR). Adding NDMI is a prerequisite for the water-stress catalog — see P2 prerequisite below.

**Cross-signal divergence** ("NDMI falling while NDVI stable") needs **no new operator** — once each index has `trend_direction`, it's `all_of([ndmi.trend_direction == falling, ndvi.trend_direction == stable])`.

**Touchpoints:**
- New `indices/trends.py` (compute deltas/slope/direction) mirroring `baselines.py`.
- Beat task to populate trends (extend `recommendations/tasks.py` sweep or a new indices sweep).
- Migration (tenant) — trend columns/table.
- `shared/conditions/context.py` + `models.py` — load + expose new index keys; extend `IndicesValueRef` allowed keys.
- Loader validation — accept the new keys.
- Insights UI (optional reuse) — show trend direction.

### P2-B — Trend/delta for custom signals (G1)

Signals already query windows for aggregation in `signals/snapshot.py`. Add derived resolvable keys computed in the same query:
- `slope` / `delta` over `aggregation_window_days`
- `trend_direction` (categorical)

**Touchpoints:** `signals/snapshot.py` (compute), `shared/conditions/context.py` + `models.py` (expose `SignalsValueRef` keys `slope`/`delta`/`trend_direction`), loader validation. No new storage (computed at snapshot load).

### P2-C / P2b — Weather climatology baselines (G5)

**Goal:** express "rainfall deficit" / "ET₀ above seasonal average" vs a climatological **normal**, not a hard constant.

**Approach:** build per-(farm-or-grid, day-of-year) climatology baselines for ET₀, precipitation, temperature — analogous to `block_index_baselines`. Expose `anomaly` / `baseline_deviation` keys on weather sources.

**Touchpoints:** new `weather/climatology.py` + baseline table, sweep to populate, `weather_derived_daily` or sibling table, `shared/conditions/context.py` weather scopes gain `anomaly` fields, loader validation.

**Risk / dependency:** robust climatology needs multiple years of history. We currently cap fetches (48h/90d) and the 9-month backfill is parked (see memory `project_historical_backfill_todo`). **P2b is gated on a weather-history backfill decision.** Until then: either (a) compute low-confidence baselines from whatever history exists and flag them, or (b) fall back to hard-coded regional thresholds (weaker transferability). Recommend treating P2b as a trailing sub-phase, not a blocker for P2a/P2b-signals.

**P2 prerequisite — add NDMI index:** add NDMI (NIR/SWIR) to `indices/computation.py` + catalog seeding (the SWIR bands are already requested in the SentinelHub evalscript per the audit). Small, self-contained PR; do it first in P2.

**P2 effort:** ~4–5 PRs (NDMI add, index trends, signal trends, weather climatology, wiring/validation). Medium risk concentrated in the sweep/storage + history availability.

---

## 6. Phase P3 — Crop growth-stage resolver (G2)

> **✅ SHIPPED, and the delivered design is better than the one sketched below.** #202
> exposed `{source: block, field: growth_stage}`. #238 then built the full spine: stage
> definitions live as validated `phenology_stages` JSONB on the **crop taxonomy**
> (crop → variety → strain, deepest-wins) rather than in new `crop_phenology` reference
> tables, and `farms/phenology_advance.py` auto-advances blocks daily via
> `calendar_doy` (perennials) / `days_from_planting` (annuals). `gdd_from_planting` is
> declared but **skipped** in V1 — the task never supplies `gdd_cumulative`.

**Goal:** expose `{source: block, field: growth_stage}` (categorical) so conditions can branch on phenology; existing `eq`/`in` handle it.

**Two phenology models (the hard part):**
- **Annual crops (Potato):** stage from `planted_on` (already stored in `block_crops`) + cumulative GDD (already computed: `gdd_cumulative_base10_season`) **or** days-after-planting. Well-supported; map GDD/DAP ranges → stages (emergence, vegetative, tuber initiation, bulking, maturation).
- **Perennial crops (Mango, Date Palm):** no annual planting date; stages are a **regional phenological calendar** (e.g. date-palm: pollination → kimri → khalal → rutab → tamar; mango: flowering → fruit set → development → harvest), keyed by date + region, not GDD-from-planting.

**Reference data:** new `crop_phenology` reference tables (per crop, optionally per variety + region) holding stage definitions with GDD/DAP ranges (annual) or calendar windows (perennial). Seed for Mango, Date Palm, Potato (Egypt first).

**Resolver:** `phenology/resolver.py` — given block crop + planted_on + GDD + date + region → `current_stage`. Inject into `ConditionContext` as `block.growth_stage`.

**Touchpoints:** new phenology reference tables + seeds, resolver module, `recommendations/service.py` (compute stage when building context), `shared/conditions/context.py` + `models.py` (`BlockValueRef` gains `growth_stage`), loader validation, frontend (optional: show current stage on block).

**Open questions to settle in PR:** stage taxonomy per crop (align with FAO/extension); how region is determined per block; variety granularity; how perennial calendars handle hemisphere/latitude. This phase is **domain-heavy** — pair with an agronomist review of the stage tables.

**P3 effort:** ~3–4 PRs (reference schema + seeds, annual resolver, perennial resolver, wiring). Highest domain risk; lowest engine risk.

---

## 7. Phase P4 — Authoring UI + polish (G6)

> **❌ THE ONLY REMAINING GAP.** `frontend/src/modules/decisionTrees/lib/conditionEdit.ts`
> still parses only a single comparison or **one** level of `all_of`/`any_of`; nested
> groups, `not`, `between` and `in` fall back to the raw-YAML editor. The engine has
> supported all of them since day one — this is purely a builder gap.
>
> **Priority is no longer "lowest".** This section argued P4 could wait because the
> platform seeds via YAML. That changed: #315 promoted decision trees to a **top-level
> tenant-facing `/decision-trees` workspace**, so a tenant author who needs `not` or a
> nested group now hits a visible dead end.

**Goal:** let tenant authors (not just platform seeders) express the richer conditions.

- Extend `ConditionBuilder` to support nested `all_of`/`any_of`, `not`, `between`, `in`.
- Add UI affordances for the new sources/keys from P2/P3 (trend_direction dropdown, growth_stage multi-select, weather anomaly).
- Recommendation-authoring panel for the 4-horizon actions (if not fully done in P1-B).

Frontend-mostly; no backend/evaluator change. Lowest priority — platform knowledge base is seeded via YAML and doesn't need this.

**P4 effort:** ~1–2 PRs.

---

## 8. Content track (parallel) — seeding the catalog

> **PARTIALLY DONE — this is where the remaining work is.** Schema readiness is no longer
> the constraint; all three gates below are open. Delivered: mango 6 trees, potato 3
> (#198). Outstanding: **potato N/P/K stage-gated nutrient trees** (unblocked — see the
> status header) and **date-palm trees** (phenology seeded in migration 0038, but zero
> seed YAMLs exist).

The actual research output (per-crop, per-condition entries) is seeded as tree YAMLs under `recommendations/seeds/`. Gate content by schema readiness:

- **After P1:** seed static-threshold conditions with full evidence + 4-horizon recommendations (e.g. Potato N/P/K deficiency thresholds, salinity ECe thresholds, absolute heat/cold thresholds).
- **After P2:** seed trend/divergence conditions (early water stress via NDMI-falling/NDVI-stable, ET₀ anomaly, rainfall deficit).
- **After P3:** seed stage-specific conditions (mango flowering stress, date-palm dormancy/development, potato tuber-bulking water demand).

Each seeded entry should carry a `confidence` (result) **and** `evidence.confidence` (evidence quality), and explicitly state uncertainty in `evidence.notes` where the research flagged weak/contradictory evidence — per the research task's "do not fabricate" rule. The **Cross-Crop Knowledge Matrix** and **Reusable Rule Library** from the research map directly onto parameterized, crop-agnostic trees (`crop_code: null` + `parameters`) vs crop-scoped trees (`crop_id` set).

---

## 9. Cross-cutting decisions to lock before coding

1. **Trends as data, not operators** — confirmed design stance (keeps evaluator pure). ✅ recommended.
2. **Persist vs compute-on-eval for index trends** — recommend persist (sweep), sibling table.
3. **Region gating** — display/governance only in P1; evaluation-time gating deferred.
4. **Weather climatology history** — depends on the parked weather backfill; P2b may ship with low-confidence baselines + flag.
5. **Phenology taxonomy** — needs agronomist sign-off on stage tables per crop/region.
6. **NDMI** — add as a new index early in P2 (water-stress catalog depends on it).
7. **Migrations** — public (`decision_tree_versions` evidence/transferability) + tenant (`recommendations.actions`, `recommendations.evidence`, index trend table, weather climatology table, phenology reference). Sequence carefully against in-flight branches.

## 10. Dependency graph & suggested sequencing

```
P1-A ─┐
P1-B ─┴─► (content: static rules)         [no deps]
P2-NDMI ─► P2-A (index trends) ─┐
P2-B (signal trends) ───────────┼─► (content: trend rules)
P2b (weather climatology) ──────┘   [gated on weather backfill]
P3 (phenology) ─► (content: stage rules)   [needs agronomist review]
P4 (authoring UI)                          [after P2/P3 keys exist]
```

P1 and the P2-NDMI prerequisite can start in parallel. P2b and P3 carry external dependencies (history backfill, agronomist review) and should be scoped with those owners.

## 11. Effort summary (rough)

| Phase | PRs | Risk | External dependency |
|-------|-----|------|---------------------|
| P1 (G3+G4) | 2 | Low | none |
| P2 (G1) | 3–4 | Medium | NDMI add; sweep/storage |
| P2b (G5) | 1–2 | Medium | weather history backfill |
| P3 (G2) | 3–4 | Low engine / High domain | agronomist stage tables |
| P4 (G6) | 1–2 | Low | P2/P3 keys |

---

## 12. What does NOT need changing

- Evaluator core operators — `lt/le/gt/ge/eq/ne/between/in` + `all_of/any_of/not` cover everything once trends/stages are data.
- Crop scoping (`crop_id`), parameter overrides, versioning, dry-run, notifications fan-out — all reusable as-is.
- The seed/loader/`sync_from_disk` pipeline — extended (new optional blocks) but not redesigned.

---

*Audit basis: `recommendations/engine.py`, `recommendations/loader.py`, `recommendations/service.py`, `recommendations/tasks.py`, `recommendations/seeds/*.yaml`, `shared/conditions/{evaluator,models,context}.py`, `indices/{computation,baselines}.py`, `weather/{models,derivations}.py`, `signals/{models,schemas,snapshot}.py`, notifications subscribers/models. Reviewed 2026-06-06.*
