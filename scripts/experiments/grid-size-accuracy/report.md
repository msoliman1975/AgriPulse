# Grid-size accuracy experiment — agrosina-suez (Phase 1)

**Question:** does the grid cell size change the accuracy of the 7 vegetation indices when
results are aggregated back to the block level — and if a block-level number moves, *why*?

**Method.** Re-gridded the full back-catalogue for two pilot blocks at 8 grid levels
(20/30/40/50/60/70/80 m + whole-block), recomputing all 7 indices per-pixel from the raw
Sentinel-2 L2A COGs (10 m) and re-aggregating to the block two ways. Internal baseline =
the full-resolution, AOI-clipped block mean (every valid pixel; the grid→0 truth). Run
in-cluster reusing the production code paths (`load_raw_bands_and_aggregate`,
`compute_all_indices`, `generate_cells`, `compute_cell_aggregates`).

**Coverage.** 2 blocks × 22 scenes (2026-03-20 → 2026-06-11) × 7 indices × 8 grid levels =
**2,464 rows** (`grid_results.csv`). Pilot blocks: **AG-R01-C02** (heterogeneous, ~12 ha) and
**AG-R01-C01** (uniform control, ~31 ha), adjacent in row R01 with near-identical mean NDVI (~0.19).

---

## Headline findings

### 1. The block *mean* is grid-invariant — **if** you weight by pixel count
*(Panel 1 · `panel1_mean_drift.png`)*

| NDVI mean \|drift\| from baseline (×1000) | 20 | 30 | 40 | 50 | 60 | 70 | 80 |
|---|---|---|---|---|---|---|---|
| **weighted** (C01) | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 |
| **unweighted** (C01) | 1.80 | 1.84 | 2.34 | 2.14 | 0.89 | 5.23 | 5.28 |
| **weighted** (C02) | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 | 0.08 |
| **unweighted** (C02) | 0.38 | 0.38 | 1.53 | 3.31 | 1.16 | 0.55 | 3.67 |

The **pixel-weighted** rollup is dead flat across every grid size — re-partitioning the same
pixels and recombining them with weights returns the same grand mean. The residual (0.25 / 0.08
×10⁻³) is constant and is *not* a grid effect: it's the `all_touched` boundary convention
difference between the per-cell mask (`all_touched=False`) and the baseline AOI mask
(`all_touched=True`).

The **unweighted** mean-of-cell-means drifts 2–20× more and **wanders non-monotonically** with
grid size. At the `block` endpoint (single cell) it collapses back onto the weighted value.

### 2. Within-block heterogeneity is smoothed away as cells coarsen
*(Panel 2 · `panel2_heterogeneity.png`)*

Std of cell means (NDVI) falls ~22% from 20→80 m (C01 0.0353→0.0282; C02 0.0392→0.0302), and
to 0 at whole-block by definition. Across all indices the loss is **22–30%**.

### 3. Extremes & anomaly detectability collapse — the operationally decisive result
*(Panel 3 · `panel3a_range.png`, `panel3b_anomaly.png`)*

Per-index change, 20 m → 80 m (averaged over both blocks, all scenes):

| index | het. loss (std) | range loss | peak \|z\| @20 → @80 |
|---|---|---|---|
| ndvi | 22% | 43% | 3.61 → 2.61 |
| **ndmi** | **30%** | **62%** | **5.00 → 2.52** |
| **ndre** | **25%** | **63%** | **5.26 → 2.55** |
| evi | 23% | 44% | 3.68 → 2.64 |
| savi | 22% | 43% | 3.70 → 2.71 |
| gndvi | 26% | 50% | 4.65 → 3.13 |
| ndwi | 26% | 50% | 4.65 → 3.13 |

The dynamic range of cell means shrinks **43–63%**, and a localized anomaly that reads **>5σ at
20 m degrades to ~2.5σ at 80 m** for NDMI/NDRE. With a z≥3 alert threshold, a clearly-flagged
hotspot at fine grids becomes **undetectable** at coarse grids. NDMI and NDRE — the
water-stress / red-edge indices used for *early* stress detection — degrade the hardest.

*(`ndwi` and `gndvi` are numerically identical because ndwi = −gndvi over the same bands — a
clean internal sanity check.)*

---

## Why a block-level aggregation moves up or down

Because our pipeline computes each index **per-pixel and then averages**, the ratio
nonlinearity (Jensen's inequality) is **not** in play — it cannot move the block number. The
movement seen with grid size comes entirely from three mechanical sources:

1. **Edge re-weighting (the dominant one, only under unweighted rollup).** Boundary cells are
   clipped to the polygon and hold fewer pixels, but an unweighted mean-of-cell-means counts
   them equally. The direction is **set by the block's geometry**: whether its edge/partial
   cells sit on greener or browner ground than the interior.
   - **AG-R01-C01:** unweighted mean is **+2.8×10⁻³ above baseline in 99% of scenes** — its
     border consistently greener than its core → block number reads systematically *high*.
   - **AG-R01-C02:** **+/−** with no net direction (44% of scenes positive) → drift is scene-by-scene
     noise, not a bias.
   Finer grids create more, smaller edge cells and the UTM-snapped grid cuts the boundary
   differently at each size → the non-monotonic wandering in Panel 1.
2. **Coverage dropout.** Cells below validity (cloud/edge) are dropped; finer grids cross the
   valid/invalid boundary in more places, removing those pixels from the estimate. Direction
   depends on whether the dropped patch was high- or low-index.
3. **Boundary convention.** `all_touched` differs between the per-cell mask and the AOI baseline
   — a small, constant offset (not grid-dependent).

**Bottom line:** a correctly **pixel-weighted** block aggregate does not move with grid size.
Any movement you see in a naive average is an edge/coverage artifact, not new signal. What grid
size genuinely controls is the **spatial detail** — variance, extremes, and anomaly detectability.

---

## Side finding — a real production bug (AOI clipping)

The stored `block_index_aggregates.valid_pixel_count = 65536 = 256²` (the full fetch window)
for every block on every scene. The true AOI-clipped pixel counts are **59,174 (C01, stored
over-counts +11%)** and **28,608 (C02, +129%)**. The persisted production block mean appears to
be computed over the **whole raster window, not clipped to the block polygon** — pulling in
neighbouring off-farm land, and worst for small/irregular blocks. Our harness uses the real
`aoi_mask`, so its baseline is the correct one. Worth a separate fix + backfill.

*(Aside: `baseline_valid_px` is constant across all 22 scenes including the 33%-cloud scene —
consistent with `cloud_cover_pct` being whole-tile while the small AOI stays clear, but worth
confirming clouds are NaN-masked and not silently averaged in.)*

---

## Recommendations

1. **Make the cell→block rollup pixel-weighted** wherever block numbers are derived from cells;
   never use an unweighted mean of cell means.
2. **Fix the AOI clipping** in the stored block aggregate (the 65536 bug) and backfill.
3. **Choose grid size by purpose, not by a single default:** the *mean* is insensitive, but for
   anomaly/zone alerting on NDMI/NDRE the fine end matters — 20–30 m preserves >5σ hotspots that
   50–80 m smooth to ~2.5σ. Coarser grids are fine for whole-block trend lines, not for
   detecting localized stress.

---

## Phase 2 (next) — external AoI baseline

Validate against an independently-computed index over a flexible AoI (Sentinel Hub Statistical
API / Copernicus Browser / GEE) — a cross-platform agreement check, distinct from this
grid-size study and confounded by different cloud masking / atmospheric correction / band
definitions. AoI chosen for availability of public products, not tied to agrosina's blocks.

*Artifacts: `grid_results.csv` (raw), `summary_by_grid.csv` (aggregated), `panel1/2/3*.png`.*
