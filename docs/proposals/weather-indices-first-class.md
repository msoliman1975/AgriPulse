# Weather Indices as First-Class Indices — Design & Implementation Plan

**Status:** Designed, approved for implementation (pending the open questions in §10). **Date:** 2026-06-16.
**Source material:** `weather indices(Sheet1).csv` — a bilingual (EN/AR) catalog of **7 weather indices**, each annotated with its relationships to *other indices*, to *diseases*, and to *insects*. The disease/insect columns are **rules-engine knowledge**, not display metadata — they become the Phase-2 risk model.

This initiative promotes weather from "a forecast widget + a condition source" to a **first-class index family** that sits alongside the 7 vegetation/"health" indices (NDVI, NDRE, NDWI, EVI, SAVI, GNDVI, NDMI) — with a catalog, climatology baselines, anomaly z-scores, a unified timeseries API, map/Replay surfaces, and (Phase 2) weather-driven **disease/pest risk indices** that finally give weather a *per-block, spatial* expression.

> **Core architectural stance (locked with stakeholder, 2026-06-16).**
> Health indices are raster-derived → naturally per-cell/per-block. Weather from Open-Meteo is a **single ~9 km grid point per farm** — every cell on a farm gets the *identical* value, so a per-cell heatmap would be a lie. Therefore:
> 1. **Raw weather indices are farm-level, temporal first-class indices** — their idiom is a timeline / gauge / Replay lane, **not** a spatial cell heatmap.
> 2. **Weather earns its spatial expression through derived *risk* indices** (disease/pest), which vary per block by crop/canopy/stage and *do* belong on the map per-block.
> 3. The disease/pest **risk model is a derived index** (an accumulation model, computed like ET₀/GDD), **not** a decision tree. The decision tree consumes the risk index as a condition and decides the *action* — exactly as a tree fires on `ndvi < 0.4` today.

---

## 0. What already exists (do not rebuild)

The weather module is mature; this is an **abstraction + presentation + risk-modeling** layer, not a data-collection project.

| Asset | Location | State |
|---|---|---|
| `weather_observations` (hypertable, per-farm hourly) — `air_temp_c`, `humidity_pct`, `precipitation_mm`, `wind_speed_m_s`, `wind_direction_deg`, `pressure_hpa`, `solar_radiation_w_m2`, `cloud_cover_pct`, `et0_mm` | `weather/` · tenant `0005` | **Live** — covers indices #1–#5 raw inputs |
| `weather_forecasts` (hypertable, keep-all-issuances) | `weather/` · tenant `0005` | **Live** |
| `weather_derived_daily` — `gdd_base10/15`, `gdd_cumulative_base10_season`, `et0_mm_daily`, `precip_mm_daily/7d/30d`, `temp_min/max/mean_c` | `weather/` · tenant `0005` | **Live** — index #7 inputs present |
| Open-Meteo provider + fetch/derive/discover Celery tasks + backfill | `weather/providers/open_meteo.py`, `weather/tasks.py`, `weather/derivations.py` | **Live**, idempotent, cold-start safe |
| `weather_providers` (public catalog) + `weather_derived_signals_catalog` (6 i18n signals) | public `0009`/`0010` | **Live** — pattern to copy for the index catalog |
| Weather as a **condition source** — `WeatherValueRef(source="weather", scope, field)`; scopes `latest_observation`/`forecast_24h`/`forecast_72h`/`derived_today`/`derived_yesterday` | `shared/conditions/`, `weather/snapshot.py` | **Live, wired into recommendations** |
| Weather REST — providers, subscriptions, refresh, forecast, observations, derived | `weather/router.py`, `frontend/src/api/weather.ts` | **Live** |
| **Vegetation index pipeline to mirror** — `indices_catalog` (public), `block_index_aggregates`/`block_index_baselines` (tenant hypertable + DOY baselines), z-score at write, `…/indices/{code}/timeseries`, daily/weekly CAGGs | `indices/` · tenant `0003`/`0008` | **Live** — the template for everything below |
| Map page index picker/heatmap/popup/Replay, DetailPanel `IndexChart` | `frontend/src/modules/labs/map/*` | **Live** — surfaces NDVI/NDRE/NDWI today |
| Weather+GDD report | `reports/` | **Live** — extend with anomaly columns |
| GDD / phenology spine (reads `block.growth_stage`) | `weather/derivations.py`, `farms/`, phenology proposal | **Live/in-flight** — risk models become stage-aware |

**Migration heads at time of writing:** public **`0036`**, tenant **`0046`**. All new migrations chain off the then-current heads (rebase `down_revision` at integration).

---

## 1. The catalog — 7 weather indices (seed straight from the CSV)

A new **public** `weather_indices_catalog` table, seeded verbatim from the sheet so EN/AR names come from the agronomists. Mirrors `indices_catalog`.

| code | name_en | name_ar | unit | source field(s) | agg over day | phase |
|---|---|---|---|---|---|---|
| `temperature` | Max/Min Temperature | مؤشر درجة الحرارة العظمى والصغرى | °C | `temp_min_c`, `temp_max_c`, `temp_mean_c` | min/max/mean | 1 |
| `radiation` | Solar Radiation | مؤشر كمية الأشعة | W/m² (→ MJ/m²/day) | `solar_radiation_w_m2` | mean + daily sum | 1 |
| `wind` | Wind Speed & Direction | مؤشر سرعة واتجاه الرياح | m/s, ° | `wind_speed_m_s`, `wind_direction_deg` | mean/max + vector mean dir | 1 |
| `rainfall` | Rainfall Amount & Density | مؤشر كمية وكثافة المطر | mm | `precip_mm_daily`, `precip_mm_7d/30d` | sum | 1 |
| `evapotranspiration` | Plant Water Loss (ET₀) | مؤشر نتح النبات للمياه | mm | `et0_mm_daily` | sum | 1 |
| `evaporation_coeff` | Soil Dry-down / Water Deficit | مؤشر معامل البخر | mm | **derived** rolling `Σ(et0_mm_daily − precip_mm_daily)` trailing 30d | window sum (stock) | 1 |
| `rain_et_balance` | Rainfall ↔ ET Balance | علاقة المطر والنتح | mm | **derived** `precip_mm_daily − et0_mm_daily` | sum (daily flux) | 1 |

Catalog columns (per row): `code` (unique), `name_en`, `name_ar`, `unit`, `description_en/ar`, `value_min`, `value_max` (for color ramp), `source_kind` (`observed`|`derived`), `default_visible` (bool), `sort_order`, plus the **relationship metadata** from the sheet carried as i18n text (`relation_indices_en/ar`, `relation_disease_en/ar`, `relation_insect_en/ar`) so the UI can show "why this matters" tooltips and the Phase-2 risk authoring can reference it.

> **#6 vs #7 — resolved (2026-06-16).** Originally proposed as `epan = et0/0.7`, but that is a *linear rescale of #5 ET₀* → identical anomalies → a degenerate duplicate. **Rejected.** Instead #6 is redefined as a **soil dry-down / water-deficit stock**: rolling `Σ(et0 − precip)` over a trailing window (default 30d). This makes #6 (cumulative **stock** — how depleted the soil is, drives wilt + soil-larvae per the sheet) genuinely distinct from #7 (daily **flux** — today's supply vs demand). Both stay as separate first-class rows (catalog matches the agronomists' 7-index sheet 1:1). No new ingestion — both are pure functions of data we already store. The "real" version of #6 (soil-water-balance bucket with rooting depth / Kc / runoff) is Phase-2 territory; the rolling deficit is a parameter-free V1 stand-in. Window is configurable; "days since last ≥X mm rain" is a possible later companion.

---

## 2. Data model (tenant)

Three additive tenant tables, modeled on `block_index_aggregates` / `block_index_baselines`.

### 2.1 `weather_index_daily` (regular table, per-farm/day) — **Phase 1**
We do **not** create a new hypertable for raw indices: the values are pure projections of `weather_observations` + `weather_derived_daily`. Materialize one row per `(farm_id, date, index_code)` in the existing `derive_weather_daily` task so the timeseries API is a single fast read.

`farm_id`, `date`, `index_code`, `value` (numeric — the headline daily value), `value_min`, `value_max`, `value_aux` (jsonb — e.g. wind mean direction, 7d/30d rainfall, radiation sum), `baseline_deviation` (z-score, nullable), `computed_at`. PK `(farm_id, date, index_code)`.

> Alternative considered: a `weather_index_values` hypertable keyed on `time`. Rejected for Phase 1 — daily granularity matches the agronomic decision cadence, the source hypertables already keep the hourly truth, and a regular table makes the climatology join trivial. Revisit if we need sub-daily index surfaces.

### 2.2 `weather_index_baselines` (regular table) — **Phase 1, climatology**
Direct port of `block_index_baselines`, **farm-scoped**: `farm_id`, `index_code`, `day_of_year` (1–366), `baseline_mean`, `baseline_std`, `sample_count`, `window_days` (default 7), `years_observed`, `computed_at`. PK `(farm_id, index_code, day_of_year)`. Seeded from the **weather backfill** so anomalies work from day one ("today is 2σ hotter than normal for this date").

### 2.3 `weather_risk_daily` (regular table, per-**block**/day) — **Phase 2**
The spatial payoff. `block_id`, `date`, `risk_code` (`powdery_mildew` | `anthracnose` | `fruit_fly` | …), `score` (0–100), `level` (`low`|`moderate`|`high`), `inputs` (jsonb — the favorable-condition accumulation that produced the score), `computed_at`. PK `(block_id, date, risk_code)`. Per-block because the model folds in block crop/canopy/stage (from the taxonomy + phenology spine), even though the weather driver is farm-uniform.

---

## 3. Derivations & tasks

| What | Where | Trigger | Phase |
|---|---|---|---|
| Project observations/derived → `weather_index_daily` (incl. `epan` proxy + balance) | `weather/index_derivations.py` (new, pure fns + unit tests) | chained from existing `derive_weather_daily` (today + yesterday) | 1 |
| **Climatology baseline sweep** — per `(farm, index, DOY)` rolling window, ≥3 samples | `weather/index_tasks.py:recompute_weather_baselines_*` | weekly Beat (mirror `indices.recompute_baselines_sweep`) | 1 |
| **Z-score at write** — `baseline_deviation = (value − baseline_mean)/baseline_std` | in the projection task, on lookup of `weather_index_baselines` | per derivation | 1 |
| **Backfill seeding** — replay historical observations through the projection + run baseline sweep | extend the weather backfill script | one-shot per farm | 1 |
| **Risk model library** — accumulation models per pathogen/pest, parameterized per crop (start as rule-of-thumb from the sheet's disease/insect columns; upgradeable to published infection models) | `weather/risk/*.py` (pure, unit-tested) | daily, per active block with a crop | 2 |
| Risk → `weather_risk_daily` | `weather/index_tasks.py:compute_weather_risk_*` | daily Beat after derivation | 2 |

**Risk model shape (Phase 2).** Each model is a pure function `(daily_weather_window, block_crop_context) → {score, level, inputs}` that integrates favorable-condition exposure over a trailing window (e.g. powdery-mildew = hours with temp in band + high humidity; anthracnose = wet-hours after rain; fruit-fly = humid-warm degree-day accumulation). Stage-aware via `block.growth_stage` (phenology spine) and canopy size (taxonomy). Start simple; the architecture is the contract, not the coefficients.

---

## 4. Conditions / recommendations integration (the bridge to alerts)

Two new value-ref sources alongside the existing `source: weather`, so decision trees can branch on indices and risk **with near-zero new plumbing** (the engine already aggregates weather):

- **`source: weather_index`** — `{scope: anomaly | latest | derived_today, index_code, field}` → e.g. `{source: weather_index, index_code: temperature, field: zscore} >= 2` ("2σ hotter than normal").
- **`source: weather_risk`** — `{risk_code, field: score|level}` → e.g. `{source: weather_risk, risk_code: powdery_mildew, field: score} >= 70`.

The tree's leaf fires the alert with the **agronomist diagnosis/prescription** — which is literally the Arabic text already in the sheet's disease/insect columns. This is the clean split: **risk math = derivation; risk policy/action = authored tree YAML.** Resolution stays permissive (missing data → `None` → predicate fails closed), matching the existing weather snapshot contract.

Files: `shared/conditions/models.py` (+2 value-ref types), `shared/conditions/context.py` (+ snapshot scopes), `weather/snapshot.py` (load index + risk into the `ConditionContext`), `recommendations/service.py` (already loads the weather snapshot once per pass — extend it).

---

## 5. REST API

New router `weather_indices/router.py` (cap `weather_index.read`, farm-scoped), shaped to match `…/indices/{code}/timeseries`:

- `GET /v1/config` → include `weather_indices_catalog` (7 entries, EN/AR, units, ranges, relationship text) so the SPA can render the picker + tooltips. *(Same place the vegetation `indices_catalog` is surfaced.)*
- `GET /v1/farms/{farm_id}/weather-indices/{code}/timeseries?granularity=daily&from=&to=` → `{points: [{date, value, value_min, value_max, baseline_mean, baseline_std, zscore}]}`.
- `GET /v1/farms/{farm_id}/weather-indices/summary` → latest value + zscore + trend for all 7 (the map/dashboard "current state" row, mirroring `blocks/summary`).
- `GET /v1/blocks/{block_id}/weather-risk?since=&until=` → `weather_risk_daily` series per `risk_code` *(Phase 2)*.
- `GET /v1/farms/{farm_id}/weather-risk/summary` → latest risk level per block per pathogen, for the map overlay *(Phase 2)*.

---

## 6. Application surface area — everything that must be aware / integrated / showing weather indices

This is the full touchpoint inventory the stakeholder asked for. **B = backend, F = frontend, P1/P2 = phase.**

### 6.1 Catalog & config
- **B/P1** `weather_indices_catalog` public table + seed migration (from CSV) + repo/schema.
- **B/P1** `/v1/config` payload extended to ship the weather-index catalog (parallel to `indices_catalog`).
- **F/P1** SPA config store / typed `WeatherIndexCode` union (mirror `frontend/src/api/indices.ts`) + `api/weatherIndices.ts` client.

### 6.2 /labs/map (the map experience — primary surface)
- **F/P1** **Index picker / toolbar** — add a *Weather* group beside the vegetation indices. Selecting a weather index switches the panel into the **farm-level temporal idiom** (timeline + current-value gauge + anomaly badge), **not** a cell heatmap (with an explicit "farm-wide" affordance so users understand it isn't per-cell).
- **F/P1** **DetailPanel** — a weather-index series card reusing `IndexChart` with a **climatology band** (baseline_mean ± std) so the anomaly is visible; current value + zσ + 7-day trend (mirrors the NDVI/NDRE/NDWI cards).
- **F/P1** **Replay timeline** — weather indices become a selectable Replay series + a **weather event lane** (already designed as an event lane in `index-replay-timeline.html`): rain spikes, heat-stress days, high-ET days scrub in sync with the imagery.
- **F/P2** **Per-block risk overlay** — `weather_risk` colors blocks (low/moderate/high) like alert severity; this is weather's *spatial* expression on the map. Block popup shows the active pathogen risks + the "why" (relationship text + accumulation inputs).
- **F/P1** `health.ts` / block fill — *unchanged* in P1 (weather stays farm-level); **P2** lets a risk index optionally drive the block fill when the user selects a risk layer.

### 6.3 Dashboard / Insights
- **F/P1** Farm-health overview gains a **weather strip** — the 7 current values with anomaly chips (re-use `weather-indices/summary`). Ties into the parked "Insights health overview" proposal.
- **F/P2** "Active risks" widget — count of blocks at moderate/high pathogen risk, linking to the map overlay.

### 6.4 Reports
- **B/F/P1** Extend the existing **Weather + GDD report** with the 7 indices + their climatology anomaly columns.
- **B/F/P2** New **"Disease/Pest pressure" report** — per-block risk history + the weather drivers (the report registry is registry-driven; add one entry).

### 6.5 Recommendations / Alerts / Decision-tree authoring
- **B/P1** `source: weather_index` value-ref + snapshot scopes.
- **B/P2** `source: weather_risk` value-ref + the risk-model library + daily risk task.
- **F/P1+P2** **Decision-tree authoring UI** — the condition builder must offer the new sources/fields (index + zscore, risk score/level) in its field picker, with EN/AR labels from the catalog. (Authoring V2 canvas — `tree_authoring_v2` work.)
- **B/P2** Seed starter trees transcribing the sheet's disease/insect rows into authored diagnoses/prescriptions (mango first, per the mango-reco extension).

### 6.6 Signals / conditions engine
- **B/P1** `weather/snapshot.py` loads index + (P2) risk scopes into `ConditionContext`; `recommendations/service.py` already loads the weather snapshot once per evaluation pass — extend, don't duplicate.

### 6.7 Phenology / planning / mango ruleset (cross-initiative)
- **B/P2** Risk models read `block.growth_stage` (phenology spine) + canopy size (taxonomy resolver) so risk is stage-aware — aligns with `phenology-spine-and-stage-aware-planning.md` and `project_mango_reco_extension`.
- The corrected mango ruleset (stress-induction = low-NDMI **AND** cool-temp) becomes a tree consuming `weather_index` temperature + the existing NDMI index — a concrete first customer of `source: weather_index`.

### 6.8 Capabilities & RBAC
- **B/P1** ~~New cap `weather_index.read`~~ → **DECIDED (PR-W4): reuse the existing `weather.read` cap** — weather indices are a view over weather data, so a separate cap added RBAC surface for zero isolation benefit and would touch 9 roles. **P2** `weather_risk.read` (new — risk is a distinct, more actionable surface). Authoring caps reuse the existing `decision_tree.manage`.

### 6.9 i18n
- **F/P1** `frontend/src/i18n/locales/{en,ar}/weatherIndices.json` — but most names come **from the catalog** (DB-sourced EN/AR), so the static bundle only covers chrome (picker labels, "farm-wide" notice, anomaly wording). RTL already handled.

### 6.10 Backfill / ops / health
- **B/P1** Weather backfill seeds `weather_index_daily` + baselines (replay historical observations).
- **B/P1** Integration-health surfaces (weather attempt log already exists) — no change needed; the index tables derive from already-monitored ingestion.

---

## 7. Staged PR rollout

### Phase 1 — raw weather indices as first-class (pure abstraction, no new science)
- **PR-W1** — Public `weather_indices_catalog` table + CSV-derived seed + `/v1/config` surface + repo/schemas. *(public migration off `0036`)*
- **PR-W2** — Tenant `weather_index_daily` + `weather_index_baselines` (off `0046`, data-safe downgrades) + projection in `derive_weather_daily` (incl. `epan` proxy + balance) + z-score at write.
- **PR-W3** — Climatology baseline sweep (weekly Beat) + backfill seeding + tests (rolling window, ≥3 samples, DOY wrap).
- **PR-W4** — REST: `weather-indices/{code}/timeseries` + `…/summary` + caps.
- **PR-W5** — Frontend: map index-picker *Weather* group + DetailPanel series w/ climatology band + dashboard weather strip + i18n.
- **PR-W6** — Replay weather lane + Weather+GDD report anomaly columns.
- **PR-W7** — `source: weather_index` condition value-ref + snapshot scope + decision-tree authoring field picker.

### Phase 2 — weather-driven risk indices (the table's real payoff, spatial)
- **PR-R1** — Risk-model library (pure fns + unit tests; powdery mildew, anthracnose, fruit fly; rule-of-thumb from CSV) + `weather_risk_daily` table.
- **PR-R2** — Daily risk task + stage/canopy context (phenology + taxonomy) + `/weather-risk` endpoints + caps.
- **PR-R3** — `source: weather_risk` value-ref + seed starter trees (mango first) transcribing the sheet's diagnoses/prescriptions.
- **PR-R4** — Map per-block risk overlay + popup + dashboard "active risks" widget.
- **PR-R5** — Disease/Pest pressure report + polish + i18n + docs.

---

## 8. What this reuses vs. builds new

**Reuses (do not re-implement):** the baseline math + weekly-sweep pattern (`indices/baselines.py`, `indices/tasks.py`), the timeseries API shape, the CAGG/derivation idempotency patterns, the conditions snapshot/value-ref machinery (weather already wired), the map index-picker + `IndexChart` + Replay lane scaffolding, the report registry, the public-catalog seed pattern (`weather_derived_signals_catalog`), the capabilities/RBAC plumbing, the i18n-from-catalog convention.

**Builds new:** the weather-index catalog + seed, the projection + `epan` derivation, the **farm-scoped** climatology baselines, the two new condition sources, the farm-level *temporal* map idiom (genuinely new — every prior index is spatial), and the Phase-2 risk-model library + per-block risk overlay.

---

## 9. Risks & decisions already settled
- **Spatial honesty** — raw weather is farm-uniform; the map idiom is temporal, not a fake per-cell heatmap. *(locked)*
- **Risk = index, not tree** — accumulation model as a derivation; tree decides the action. *(locked)*
- **Evaporation Coefficient (#6)** — **redefined as soil dry-down stock** `Σ(et0 − precip)` trailing 30d (NOT `epan = et0/0.7`, which is degenerate with ET₀). Distinct stock-vs-flux complement to #7. Both rows kept. *(locked 2026-06-16, resolves §10 #5)*
- **Anomalies = climatology** — `(farm, index, DOY)` baselines seeded from backfill. *(locked)*
- **Phasing** — raw indices + baselines first; risk model second. *(locked)*

---

## 10. Open questions (non-blocking for Phase 1 scaffolding)
1. **Risk pathogen scope for P2 V1** — start with the three named in the sheet (powdery mildew, anthracnose, fruit fly) for mango only, or a broader pest set? *(recommend: those three, mango-first.)*
2. **Risk model fidelity** — ship rule-of-thumb scores transcribed from the sheet's relationship text first and upgrade to published infection models later, or hold P2 until a validated model is sourced? *(recommend: rule-of-thumb first — architecture is the contract.)*
3. **Map idiom for raw weather** — timeline + gauge in the DetailPanel is the baseline; do we also want a small always-on "farm weather" chip on the map header, independent of the index picker?
4. **Anomaly thresholds** — default zσ alert bands (e.g. |z|≥2 = notable) global, or per-index in the catalog?
5. ~~**`epan` vs balance** — keep both catalog rows, or collapse #6?~~ **RESOLVED 2026-06-16:** keep both; #6 redefined as soil dry-down stock `Σ(et0 − precip)` 30d (degenerate `epan=et0/0.7` dropped). See §1 caveat.

---

## Existing structures this builds on (reference)
- `backend/app/modules/indices/` — `models.py` (`IndicesCatalog`, `BlockIndexAggregate`, `BlockIndexBaseline`), `baselines.py` (rolling-window + z-score math), `tasks.py` (`recompute_baselines_*`), `router.py` (`…/indices/{code}/timeseries`).
- `backend/app/modules/weather/` — `tasks.py` (`fetch_weather`, `derive_weather_daily`, `discover_due_subscriptions`), `derivations.py` (GDD/ET₀/rolling-precip), `snapshot.py` (condition snapshot), `router.py`.
- `backend/app/shared/conditions/` — `models.py` (`WeatherValueRef` + `BLOCK_FIELDS`), `context.py` (`WeatherSnapshot`, allowed scopes).
- `backend/migrations/public/versions/0009_weather_catalog.py` + `0010_seed_weather_catalog.py` — catalog + seed pattern to copy.
- `frontend/src/modules/labs/map/` — `MapExperiencePage.tsx`, `MapCanvas.tsx`, `DetailPanel.tsx`, `IndexChart.tsx`, `api.ts`, `health.ts`.
- `frontend/src/api/indices.ts`, `frontend/src/api/weather.ts` — client + typed code unions to mirror.
- `docs/proposals/index-replay-timeline.html` (+ `-v2`) — Replay event-lane design (weather lane).
- `docs/proposals/phenology-spine-and-stage-aware-planning.md` + `project_mango_reco_extension` — stage-aware risk + corrected mango ruleset.
</content>
</invoke>
