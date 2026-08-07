# AgriPulse Observer — pipeline transparency for platform admins

**Status:** design / for review
**Date:** 2026-08-06
**Surface:** `/platform/observer` (Platform portal, new top-level nav entry)
**Capability:** `platform.observe_pipeline` (new, read-only)
**API prefix:** `/api/v1/admin/observer`
**Mockup:** [`agripulse-observer-mockup.html`](agripulse-observer-mockup.html)

> **New to the terminology?** § 9 is a glossary of every abbreviation and piece of
> jargon used here — bands, indices, statistics, pipeline and storage terms. The
> same definitions are meant to ship inside the product as info popovers, not only
> in this document.

---

## 1. Why

Every number a customer sees — an NDVI trend, a cell anomaly, an irrigation
recommendation — is the output of a five-hop pipeline that is currently a black
box. When a value looks wrong there is no way to answer, without SSH and a
Python REPL:

- Were the scenes even discovered for that window?
- Did the scene download succeed but the index computation die?
- Why is `valid_pixel_pct` 43% — cloud, no-data, or an AOI that half-misses the raster?
- Does the stored block mean actually match what the COG contains today?
- Was this row computed by the current formula, or by the pre-#288 resampling defect?
- Which alert / recommendation did this number go on to produce?

Observer makes each arrow in the pipeline inspectable, from raw scene count down
to a single pixel's arithmetic, and back up into the consumers.

**Observer is not a second integration-health page.** Platform → Health answers
*"did the fetch work?"* (attempts, queue depth, provider errors). Observer
answers *"is the number right, and where did it come from?"*. The two cross-link;
they do not overlap.

---

## 2. Ground truth — what the pipeline does today

### 2.1 Imagery lane (per `block × product × scene`)

| # | Task | Queue | Writes |
|---|------|-------|--------|
| 1 | `imagery.discover_scenes` (Beat → `imagery.discover_active_subscriptions`) | default | `imagery_ingestion_jobs` (`pending`), stamps `imagery_aoi_subscriptions.last_attempted_at` |
| 2 | `imagery.acquire_scene` | heavy | `raw_bands.tif` COG → object storage at `{provider}/{product}/{scene_id}/{aoi_hash}/raw_bands.tif`; job → `succeeded`, `stac_item_id` set |
| 3 | `imagery.register_stac_item` | default | `pgstac.items` row |
| 4 | `imagery.compute_indices` | heavy | 7 index COGs + `block_index_aggregates` + `block_grid_aggregates` + pgstac asset map |

Step 4 (`app/modules/imagery/tasks.py:953`) is where the calculation lives:

1. `load_raw_bands_and_aggregate` reads the raw COG over `/vsis3/`, rasterizes the
   block boundary in UTM into `aoi_mask`, and derives `cloud_mask` from the SCL
   band (`S2_SCL_MASKED_CLASSES = 0, 1, 3, 8, 9, 10, 11`).
2. `compute_all_indices` runs 7 pure-numpy formulas (`indices/computation.py`).
3. Cloud pixels are set to `NaN`, then `compute_aggregates(clouded, aoi_mask)`
   reduces each index to mean/min/max/p10/p50/p90/std + `valid_pixel_count` +
   `total_pixel_count`.
4. Each index COG is written masked to the AOI.
5. `record_aggregate_row` upserts `block_index_aggregates` and stamps
   `baseline_deviation` from `block_index_baselines`.
6. If a `grid_config` was active **at scene time** (not "now" — tenant migration
   0054), `compute_cell_aggregates` does zonal stats per cell from the
   in-memory index rasters → `block_grid_aggregates`.
7. pgstac item upsert, `IndexAggregatedV1` per index, audit `imagery.indices_computed`.

**Trends:** `block_index_daily` / `block_index_weekly` — real-time continuous
aggregates with rolling 3d/21d refresh policies plus the hourly full-refresh
sweep added in #336. `block_index_baselines` is a weekly sweep.

### 2.2 Weather lane (farm-scoped — no blocks, no pixels)

`weather_subscriptions` → `weather_ingestion_attempts` → `weather_observations`
(hourly hypertable, keyed `(time, farm_id, provider_code)`) → `weather_derived_daily`
(GDD / ET₀ / precip rollups) → `weather_index_daily` (8 indices via
`weather/index_projection.py`) → `weather_index_baselines`.

### 2.3 Four gaps this design has to work around

1. **No pixel data exists in Postgres.** Pixel drill-down can only be answered by
   reading the COG at request time. TiTiler is already deployed (`tiles.*`, its own
   bucket credentials), so tiles + `/cog/point` + `/cog/statistics` are free.
2. **Aggregate rows are upserts with no lineage.** Re-running `compute_indices`
   silently overwrites the same `(time, block_id, index_code, product_id)` row.
   Job-grain history exists (`imagery_ingestion_jobs`); row-grain history does not.
   No code version, no formula version, no mask-ruleset stamp, no `computed_at`.
3. **The pixel budget does not reconcile.** We store `valid_pixel_count` and
   `total_pixel_count` (= AOI footprint) but not how many pixels died to SCL
   masking vs. no-data vs. divide-by-zero. "Why is this scene 43% valid?" is
   unanswerable from the database alone.
4. **`block_index_aggregates` carries two continuous aggregates.** Any schema
   change to it has to be checked against the CAGG dependency — see § 5.

---

## 3. Information architecture

### 3.1 Selection rail (persistent, URL-encoded)

```
Source: [ Imagery | Weather ]
Tenant ▾   Farm ▾   Blocks ▾ (multi, default = all)   Window ▾   Product ▾   Index ▾
```

State lives in query params so a view is shareable with another admin:
`/platform/observer?src=imagery&tenant=…&farm=…&blocks=…&from=…&to=…&product=…&index=ndvi`

Pickers are new thin endpoints rather than a reuse of the Backfill Console's —
those are gated on `platform.run_backfill`, and read access must not imply the
right to spend CDSE units. They call the same underlying queries plus an
"is there anything to observe here" summary per farm: block count, blocks with an
active imagery subscription, blocks with a grid config, weather subscription
yes/no, first and last scene date.

Blocks are optional; empty = all blocks in the farm. On the **Weather** lane the
block picker is disabled with an inline note — weather is farm-centroid data.

### 3.2 Five levels of drill

```
L0  Pipeline overview   stage counts + drop-off, scene histogram by date bucket
L1  Scene table         one row per (scene × block), status + outputs at a glance
L2  Scene detail        inputs · raster + pixel inspector · pixel budget · roll-up chain
L3  Verify              recompute from source, diff against stored (no writes)
L4  Forward lineage     which alerts / recommendations / anomalies this fed
```

---

## 4. The views

### 4.1 L0 — Pipeline overview

A stage ribbon showing the real pipeline with counts for the current selection,
each node carrying the drop-off to the next:

| Stage | Count source |
|-------|--------------|
| Discovered | `imagery_ingestion_jobs` rows in window (any status) |
| Acquired | `status = 'succeeded' AND stac_item_id IS NOT NULL` |
| Registered | `pgstac.items` for the collection |
| Indices computed | distinct `(time, block_id, product_id)` in `block_index_aggregates` |
| Cell aggregates | distinct `(time, block_id, product_id)` in `block_grid_aggregates`, **denominated by** jobs whose block had an active `grid_config` at scene time |
| Trend coverage | distinct bucket days in `block_index_daily` vs. distinct scene days |
| Consumers | alerts + recommendations referencing those `(block, date)` |

Two of these are diagnostic by construction:

- **Cell aggregates** without the valid-time denominator reads as "0 of 412
  broken" on an ungridded farm. With it, it reads "n/a — no grid configured",
  which is the truth.
- **Trend coverage** compares CAGG buckets against scene days, which is exactly
  the failure class of #336 (backfilled history invisible because the rolling
  refresh policy never covered it). Observer surfaces that as a red node instead
  of a support ticket.

Below the ribbon: **scene histogram** — count of scenes per day / week / month
bucket across the window, stacked by outcome (succeeded · failed · skipped-cloud ·
pending). This is the "count of scenes grouped by date range" ask, and clicking a
bucket or a ribbon node filters L1.

### 4.2 L1 — Scene table

One row per `(scene, block)`: scene datetime · scene id · block · product · job
status · cloud % · valid pixel % · indices written (`7/7` chip) · cells written
(`n/N`) · baseline z available · calc version · computed at · duration · error
code. Row expands inline to the 7 per-index stat rows
(mean/min/max/p10/p50/p90/std, valid/total px).

Sorting and filtering on `valid_pixel_pct` and `error_code` is what makes this
usable — "show me every scene under 40% valid in the last quarter".

### 4.3 L2 — Scene detail (the calculation view)

Three panes.

**Inputs.** Raw COG key + size + band list, AOI hash and boundary, whether SCL was
present, product resolution and revisit, the mask ruleset (the SCL class list,
named and versioned), and the `grid_config` resolved at scene time (cell size,
UTM SRID, cell count).

**Raster + pixel inspector.** The selected index COG rendered through TiTiler
with the block outline and grid cells overlaid. Clicking a pixel calls the
explain endpoint and returns the full arithmetic:

```
Pixel (row 41, col 78) — 2026-06-14 · NDVI
blue 0.0412   green 0.0655   red 0.0871   nir 0.3140   swir1 0.1802
SCL = 4 (vegetation) → not masked
inside AOI ✓   inside cell R3C5

NDVI = (nir − red) / (nir + red)
     = (0.3140 − 0.0871) / (0.3140 + 0.0871)
     = 0.2269 / 0.4011
     = 0.5657

contributes to: block mean 0.5123 · cell R3C5 mean 0.5490
```

The endpoint reads one window from the raw-bands COG (a single GDAL range
request), applies the same `scl_cloud_mask` and AOI test the task uses, and
reuses `indices/computation.py` for the formula — so the panel cannot drift from
the pipeline. It reports masked pixels honestly ("SCL = 9 high-probability cloud
→ masked, excluded from all statistics") rather than showing a value.

**Product-driven, degrading gracefully.** The inspector is not written against
the Sentinel-2 band set. It renders whatever `imagery_products.bands` declares for
the product and only the indices in `supported_indices`. On PlanetScope — 4 bands,
no SWIR, no SCL — it shows the four reflectances present, reports masking as
`n/a — product has no scene-classification band`, and offers NDVI/GNDVI/EVI/SAVI
while greying NDMI with the reason ("requires SWIR1, absent from this product").
The panel never invents a band and never implies a mask decision was made when
none was possible.

**Pixel budget + roll-up chain.** A waterfall: AOI footprint → minus SCL-masked →
minus no-data/NaN → valid. Then the roll-up: pixel → cell → block, with cell
means listed and an explicit reconciliation check against the block mean. (They
are not identical — the block mean is over all AOI pixels while cells partition
the block on a different lattice — so the check states the expected tolerance
rather than pretending they must match.)

### 4.4 L3 — Verify (read + diff, no writes to pipeline tables)

Two tiers:

- **Fast check** — TiTiler `/cog/statistics` over the index COG with the AOI as
  feature. Instant, but it verifies *aggregation only*: the index COG already has
  masking baked in.
- **Full check** — a heavy Celery task that re-runs `load_raw_bands_and_aggregate`
  + `compute_all_indices` + `compute_aggregates` from the raw COG. Verifies the
  whole chain including masking and formula.

Output is a per-index diff: stored vs. recomputed mean and valid-pixel count,
delta, verdict (`match` / `drift` / `source missing`). Nothing in
`block_index_aggregates` is touched — a drift finding is a signal to open the
Backfill Console, not something Observer silently repairs.

**Anything beyond a single scene is a named run.** A full verify of one year for a
36-block farm is ~2.5k heavy-task executions, which is not a button that returns a
response. Multi-scene verify follows the Backfill Console's model exactly:

```
tenant_<id>.observer_verify_runs
  id · tenant_id · farm_id · block_ids[] · window_from/to · product_id
  mode          -- fast | full
  status        -- queued | running | succeeded | failed | cancelled
  progress      -- jsonb: {scenes_total, scenes_done, match, drift, error}
  created_by_email · created_at · started_at · completed_at · error
```

- One active verify run per farm, enforced by a partial unique index — the same
  guard Backfill uses, for the same reason (a second run would re-read the same
  COGs while the first is still working).
- `POST /runs/{id}:cancel` from day one. The lesson from #332 is that any run
  which can hang needs an operator escape hatch that is not "edit the table".
- Per-scene results land in `observer_verifications` keyed by the run, so a
  finished run is a browsable report and repeat views cost nothing.
- Single-scene verify from the scene-detail view stays synchronous — it is one
  task and the operator is already looking at that scene.

Verify is the only thing in Observer that consumes worker time, so it is also the
only thing that is audited (§ 6).

### 4.5 L4 — Forward lineage

From a `(block, date, index)`: which alerts fired, which recommendations were
produced and by which decision tree, which cells crossed the anomaly z-threshold.
Bidirectional — from an alert, jump back to the scene whose pixels produced it.

### 4.6 Weather lane

Same shell, different spine, because weather has no scenes and no pixels:

```
Subscription → fetch attempts → hourly observations → derived daily → weather_index_daily → baselines → consumers
```

- The scene analogue is a **fetch attempt** (`weather_ingestion_attempts`).
- The pixel analogue is an **hourly observation row**.
- The `valid_pixel_pct` analogue is **hour coverage**: a per-day heat strip of
  hours present out of 24. This is genuinely invisible today and is the single
  most useful weather-side diagnostic — a day computed from 9 hours of
  observations produces a confident-looking ET₀ that is wrong.
- The explain view for one `weather_index_daily` cell shows the hourly rows that
  fed it, the `weather_derived_daily` intermediate, and the projection formula
  from `index_projection.py` with the numbers substituted — same "show the
  arithmetic" idea, no raster.

Weather needs less new plumbing: `weather_derived_daily` and `weather_index_daily`
already carry `computed_at`.

---

## 5. Lineage — `indices_calc_runs`

The decision is to stamp calculations so "history per scene/date" is truthful.
Proposal: a **side table**, not new columns on the aggregate hypertables.

Rationale for the side table over columns:

- `block_index_aggregates` carries two continuous aggregates
  (`block_index_daily`, `block_index_weekly`). Altering it is a schema change with
  a CAGG dependency to validate, and the aggregates are on the customer read path.
- Columns can only ever hold the *latest* execution — a silent recompute-overwrite
  stays invisible, which is one of the things this feature exists to expose.
- One row per **execution** per `(scene, block, product)` covers all 7 indices at
  once, since they share masking and AOI footprint. That is ~1/7 the volume of a
  per-index run table, with per-index detail kept in a JSONB column.

```
tenant_<id>.indices_calc_runs
  id                  uuid pk
  job_id              uuid  → imagery_ingestion_jobs.id
  scene_time          timestamptz
  scene_id            text
  stac_item_id        text
  block_id            uuid
  product_id          uuid
  aoi_hash            text
  grid_config_id      uuid null      -- resolved at scene time
  cell_count          int null
  calc_version        text           -- e.g. "idx-2026.08"
  mask_ruleset        text           -- e.g. "s2_scl_v1"
  band_order          text[]
  aoi_pixel_count     int            -- AOI footprint
  masked_pixel_count  int            -- dropped by SCL
  per_index           jsonb          -- {ndvi:{valid,nodata,mean,…}, …}
  trigger             text           -- live | backfill | verify | manual
  outcome             text           -- ok | failed
  error               text null
  started_at          timestamptz
  completed_at        timestamptz
  duration_ms         int
```

`calc_version` is a backend constant. Per the constant-drift lesson from #345,
if the frontend ever renders a "computed with" label from its own copy, the pair
needs a lock-step test.

Migration lands in the tenant chain — next free number is **0059** at time of
writing (0058 is `block_crop_validity`, currently unmerged; re-check before
authoring).

**Plain table, no retention policy.** At roughly one row per scene per block the
growth is trivial — Bashayer's 36 blocks over a decade of dense backfill is ~25k
rows. A hypertable with a drop-chunks policy would be premature, and worse, a
retention policy on a *lineage* table silently deletes the audit trail that
justifies the table existing. Revisit if a tenant ever crosses ~10 M rows; the
conversion to a hypertable is not blocked by shipping it flat first.

---

## 6. Access, safety, cost

- New capability `platform.observe_pipeline`, `scope: platform`, granted to
  platform roles. Read-only. Deliberately separate from `platform.run_backfill`
  so viewing does not imply spending provider quota.
- Observer reads across tenants. That is the same trust boundary Backfill and
  Health already sit on, so no new exposure class.
- **Audit verify runs only.** A verify run consumes worker time and is an operator
  action with a start, an outcome and a cost, so it gets an audit event
  (`platform.observer_verify_started` / `…_completed`, with tenant, farm, window,
  mode and scene count). Drill-down views are not audited: an admin opening a
  scene is indistinguishable from an admin opening a farm page, and writing an
  audit row per pixel click would bury the events that matter under noise.
- **No cross-tenant board.** Observer always starts from a chosen tenant.
  A platform-wide "worst offenders" view (lowest valid-pixel farms, stalest CAGGs,
  most compute failures) belongs to Platform → Health, which already owns the
  cross-tenant rollup surface. Observer is the drill-in you reach *from* such a
  board, not a competing one — so a future Health row should deep-link into
  Observer with the tenant and farm pre-selected.
- **Hypertable time bounds must be interpolated, not bound.** A bound parameter
  gets no plan-time chunk exclusion — the lesson from the Farm Console 7 s load.
  Every Observer query is time-windowed over hypertables, so this applies to all
  of them.
- Require a farm and cap the window (2 years suggested) on the overview, which is
  6–7 aggregate queries per load.
- Pixel inspect is one GDAL range read per click. No caching needed for v1.

---

## 7. Implementation plan

| PR | Scope | Migration |
|----|-------|-----------|
| **OBS-1** | `observer` backend module: capability, pickers, L0 stage counts, scene histogram, L1 scene table. Read-only over existing tables. | — |
| **OBS-2** | `/platform/observer` shell: selection rail, stage ribbon, histogram, scene table + expand. | — |
| **OBS-3** | L2 backend: scene detail, pixel-explain endpoint (raw-COG window read reusing `computation.py`), live pixel-budget breakdown, product-driven band/index degradation. | — |
| **OBS-4** | L2 frontend: raster viewer via TiTiler, pixel inspector, pixel-budget waterfall, roll-up chain. | — |
| **OBS-5** | `indices_calc_runs` + `calc_version` constant; `compute_indices` writes a run row; Observer reads real history. | tenant 0059 |
| **OBS-6** | L3 verify: single-scene synchronous (fast + full) + `observer_verify_runs` named runs with progress, cancel, one-per-farm guard, `observer_verifications` results, diff panel, audit events. | tenant 0060 |
| **OBS-7** | Weather lane: backend spine + hour-coverage strip + daily-index explain, frontend source switch. | — |
| **OBS-8** | L4 forward lineage into alerts / recommendations / anomalies, bidirectional links. | — |

Sequencing note: OBS-1/2 carry most of the diagnostic value for the least work —
the stage ribbon alone would have caught #332, #335 and #336 on sight. OBS-5
should land before OBS-6, since verify is much more meaningful when it can say
*which* calc version produced the stored row.

---

## 8. Decisions

Resolved 2026-08-06 — recorded here so they are not relitigated mid-build.

| # | Question | Decision |
|---|----------|----------|
| 1 | Pixel drill depth | **Full "explain this pixel"** — band values, mask verdict, substituted formula, result (§ 4.3) |
| 2 | Mutation | **Read + verify, never repair.** Drift routes to the Backfill Console (§ 4.4) |
| 3 | v1 scope | Imagery **and** weather **and** forward lineage into consumers (§ 4.5, § 4.6) |
| 4 | Lineage | **Stamp calculations** — as the `indices_calc_runs` side table, not columns (§ 5) |
| 5 | Audit granularity | **Verify runs only.** Views are not audited (§ 6) |
| 6 | Cross-tenant board | **Not Observer's** — that is Platform → Health's surface; Health deep-links in (§ 6) |
| 7 | `indices_calc_runs` retention | **None for now.** Plain table; revisit past ~10 M rows (§ 5) |
| 8 | Verify budget | **Named run with progress**, cancel, one-per-farm — the Backfill model (§ 4.4) |
| 9 | PlanetScope / non-S2 | **Degrade per product** from `bands` + `supported_indices`; mask reads `n/a` (§ 4.3) |

Nothing is currently blocked on an answer. Two things to re-check at build time
rather than now: the next free tenant migration number, and whether Health wants
the deep-link into Observer in the same release or later.

---

## 9. Glossary

Observer's audience is wider than the people who wrote the pipeline — agronomy
and support will use it too. Every term below should also be available **in the
product**, as an info popover on the label that uses it, not only in this doc.

### Satellite imagery

| Term | Means |
|------|-------|
| **Scene** | One satellite pass over one place at one moment. The unit everything else hangs off. |
| **Scene ID** | The provider's name for that pass, e.g. `S2B_MSIL2A_20260614T083709` — satellite, product level, timestamp. |
| **Revisit** | How often the satellite comes back to the same spot. Sentinel-2 averages ~5 days; more revisits means a denser trend line. |
| **Band** | One slice of the light spectrum the sensor records. Each band is a separate greyscale image of the same patch of ground. |
| **Blue / Green / Red** | Visible light — what a normal camera sees. |
| **Red edge** | The narrow slice between red and near-infrared where healthy leaves brighten sharply. Sensitive to chlorophyll and early stress. |
| **NIR** (near-infrared) | Invisible to the eye; healthy leaf tissue reflects it strongly. The workhorse band for vegetation. |
| **SWIR** (short-wave infrared) | Longer infrared, absorbed by water. SWIR1 falling means leaf water content is falling. PlanetScope has no SWIR — which is why NDMI is impossible on it. |
| **Surface reflectance** | The fraction of light the ground actually reflects (0–1), after the atmosphere's effect has been removed. Comparable across dates; raw brightness is not. |
| **L2A** | Sentinel-2's atmospherically-corrected product level — i.e. surface reflectance. L1C is the uncorrected one. |
| **SCL** (Scene Classification Layer) | A per-pixel label Sentinel-2 ships alongside the bands: cloud, cloud shadow, cirrus, snow, water, vegetation, bare soil… We drop classes 0, 1, 3, 8, 9, 10, 11 before doing any maths. |
| **Cloud cover %** | Fraction of the scene under cloud, as reported by the provider for the whole scene — not for your block specifically. |
| **AOI** (area of interest) | The polygon we actually care about — here, one block's boundary. Pixels outside it are ignored. |
| **AOI hash** | A short fingerprint of that polygon (e.g. `a41f9c`). It is part of the stored file path, so redrawing a block produces a different hash and cannot silently overwrite the old block's imagery. |
| **Pixel** | One ground cell of the image. At Sentinel-2's 10 m resolution, one pixel is a 10 × 10 m square — one tenth of a feddan. |
| **Resolution** | The ground size of one pixel. 10 m for Sentinel-2, 3 m for PlanetScope. Smaller is more detail and more cost. |
| **Raster** | A grid of pixels — an image with geographic coordinates attached. |
| **COG** (Cloud-Optimized GeoTIFF) | The image file format we store. Structured so a reader can fetch just the few kilobytes covering one block instead of downloading the whole file. |
| **GDAL / `/vsis3/`** | The library that reads rasters, and its mode for reading them directly out of object storage without downloading first. |
| **STAC** / **pgstac** | A standard catalogue format for satellite imagery (SpatioTemporal Asset Catalog), and the Postgres implementation of it we run. The index of what imagery exists, separate from the imagery itself. |
| **STAC item** | One catalogue entry — one scene over one block, listing where each band and index file lives. |
| **TiTiler** | The service that turns a COG into map tiles the browser can display, and answers "what is the value at this coordinate". Already deployed at `tiles.*`. |
| **CDSE** | Copernicus Data Space Ecosystem — the EU's free Sentinel-2 source. Its processing allowance is shared across all tenants, which is why backfill is capability-gated. |
| **Sentinel Hub / PlanetScope** | Commercial imagery providers. Sentinel Hub served our 10 m subscription (expired); PlanetScope is 3 m, 4 bands, no SWIR. |

### Indices

An **index** is a formula that combines bands into one number per pixel that means
something agronomic. All seven are computed for every scene.

| Code | Name | Reads as |
|------|------|----------|
| **NDVI** | Normalized Difference Vegetation Index | Overall greenness / biomass. The default health signal. `(NIR − Red) / (NIR + Red)` |
| **NDRE** | Normalized Difference Red Edge | Like NDVI but via red edge — saturates later, so it still discriminates in a dense mature canopy where NDVI has flattened. |
| **GNDVI** | Green NDVI | Greenness via the green band; more responsive to chlorophyll and nitrogen status. |
| **EVI** | Enhanced Vegetation Index | NDVI corrected for atmosphere and soil background; better in dense canopy. |
| **SAVI** | Soil-Adjusted Vegetation Index | NDVI with a soil-brightness correction — for sparse canopy where bare ground dominates the pixel. |
| **NDMI** | Normalized Difference Moisture Index | **Leaf and canopy water content.** Falls as tissue dries — an early water-stress signal. Needs SWIR. |
| **NDWI** | Normalized Difference Water Index (McFeeters) | **Open surface water**, not leaf moisture. Negative over healthy canopy is normal and expected. Do not read it as "canopy water" — that is NDMI's job. |

### Statistics

| Term | Means |
|------|-------|
| **Aggregate** | The reduction of thousands of pixel values to a handful of numbers for a block or a cell. |
| **Mean / min / max** | Average, lowest, highest pixel value inside the AOI. |
| **P10 / P50 / P90** (percentiles) | 10% of pixels are below P10; P50 is the median; 90% are below P90. The P10–P90 spread shows in-field variability that a mean hides. |
| **Std dev** | How spread out the pixel values are. High std dev on a uniform block means something is patchy. |
| **Valid pixel count** | Pixels that produced a usable number — inside the AOI, not cloud-masked, not no-data. |
| **Total pixel count** | The AOI footprint: every pixel inside the block boundary, usable or not. |
| **Valid pixel %** | valid ÷ total. Low values mean the number is computed from a fraction of the field and should be trusted less. |
| **No-data / NaN** | "Not a number" — a pixel with no usable value, from a sensor gap or a division by zero in the formula. Excluded from every statistic. |
| **Baseline** | The long-run normal for this block, this index, this day of the year, built from history. |
| **Day of year** | 1–366. Baselines are keyed on it so 14 June is compared against mid-Junes, not against last month. |
| **Baseline deviation / z-score** | How far today sits from that normal, in standard deviations. −2.0 means "unusually low for this date"; ±1 is ordinary variation. |
| **Anomaly threshold** | The z-score at which a cell is flagged. Configurable per block. |

### Structure

| Term | Means |
|------|-------|
| **Tenant** | One customer organisation. Each has its own isolated database schema (`tenant_<id>`). |
| **Farm** | A customer's site. Weather is measured at farm level (one centroid). |
| **Block** | A managed parcel inside a farm — the unit imagery, indices and crops attach to. |
| **Cell / grid** | An optional finer subdivision of a block into a square lattice (e.g. 40 m cells), for spotting *where inside* a block a problem sits. |
| **Grid config** | The definition of that lattice for a block. Versioned by valid time, so a 2025 scene is gridded on the 2025 geometry, not today's. |
| **Zonal statistics** | Computing an aggregate over an arbitrary polygon — how a cell's mean is derived from the pixels falling inside it. |
| **UTM / SRID / EPSG** | Coordinate systems. Areas and distances are computed in a metre-based projection (UTM 36N for Egypt); map display uses lat/long (WGS 84 / EPSG 4326). SRID is just the numeric ID of a coordinate system. |
| **Subscription** | The standing instruction "fetch this product for this block at this cadence". No subscription, no imagery. |
| **Ingestion job** | One attempt to fetch and process one scene for one block. Carries status, timings and any error. |

### Pipeline & storage

| Term | Means |
|------|-------|
| **Celery** | The background job system. Anything slow runs there, not in the web request. |
| **Beat** | Celery's scheduler — the clock that kicks off recurring sweeps like scene discovery. |
| **Queue (default / heavy)** | Work is split so a long raster computation cannot starve quick tasks. Index computation runs on `heavy`. |
| **Worker** | A process that pulls jobs off a queue and runs them. |
| **Idempotent** | Safe to run twice — a re-run overwrites the same row rather than creating a duplicate. True of the whole imagery pipeline, which is what makes retries safe. |
| **Upsert** | Insert, or update in place if the row already exists. Why a recompute leaves no trace without `indices_calc_runs`. |
| **Backfill** | Loading historical data for a window in the past, rather than the live daily flow. |
| **Object storage / R2** | Where the image files live (Cloudflare R2, S3-compatible). The database stores paths, never pixels. |
| **Timescale / hypertable** | The time-series extension of Postgres, and a table it partitions by time under the hood. |
| **Chunk** | One of those time partitions. A query that names an explicit time range can skip whole chunks; one that hides the range in a bound parameter cannot — which is why Observer's queries interpolate their intervals. |
| **CAGG** (continuous aggregate) | A pre-computed rollup that refreshes on a policy — how daily and weekly trend lines are served fast. |
| **Refresh policy / watermark** | The rolling window a CAGG keeps up to date, and the boundary below which it serves only pre-computed results. Data written outside that window stays invisible until a manual refresh — the #336 failure. |
| **Migration** | A versioned, ordered schema change. Numbered per chain (`public`, `tenant`). |
| **Capability** | A named permission, e.g. `platform.observe_pipeline`. Roles grant capabilities; endpoints require them. |

### Weather

| Term | Means |
|------|-------|
| **Observation** | One measured hour at the farm — temperature, humidity, wind, rain, radiation. |
| **Hour coverage** | How many of a day's 24 hours actually arrived. The weather equivalent of valid-pixel %. |
| **ET₀** (reference evapotranspiration) | How much water a reference grass surface would lose in a day, in mm. The basis of irrigation demand. |
| **GDD** (growing degree days) | Accumulated warmth above a crop's base temperature — the clock crops actually grow on, rather than the calendar. |
| **Solar radiation / insolation** | Instantaneous energy arriving (W/m²) and the day's total (MJ/m²). Drives ET₀. |
| **Derived daily** | The per-day rollup computed from hourly observations, before it becomes an index. |
| **ERA5 / Open-Meteo** | Weather data sources. ERA5 is the ECMWF reanalysis archive reaching back to 1940, used for deep history. |

### Observer's own terms

| Term | Means |
|------|-------|
| **Stage ribbon** | The row of pipeline stages with counts and the drop-off between them. Where work is being lost, at a glance. |
| **Pixel budget** | The reconciliation of AOI footprint → masked → no-data → valid. Answers "why is valid % low". |
| **Roll-up chain** | Pixel → cell → block, shown together so a number can be traced to what produced it. |
| **Calc version** | Which release of the formulas and masking rules produced a stored row. Two versions in one window means the trend line mixes methodologies. |
| **Mask ruleset** | The named, versioned set of SCL classes treated as unusable (`s2_scl_v1`). |
| **Verify** | Recompute from the stored image and compare against the stored number. Never writes. |
| **Drift** | A verify result where stored and recomputed disagree beyond tolerance. |
| **Forward lineage** | What a number went on to cause — the alerts and recommendations downstream of it. |
