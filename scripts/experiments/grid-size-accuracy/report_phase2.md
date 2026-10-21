# Grid-size accuracy experiment — Phase 2: external baseline

**Question:** how do our block-level index values compare to an *independent* computation
over the same AoI ("the baseline")?

**Method.** Used the **CDSE Sentinel Hub Statistical API** (`sh.dataspace.copernicus.eu/api/v1/statistics`)
with our existing in-cluster OAuth creds — zero new accounts. For each pilot block polygon
(UTM 36N, so `resx/resy=10` means 10 m) it computes server-side zonal stats (mean/stDev/min/max/
sampleCount) for all 7 indices, per acquisition day, over the **same Sentinel-2 L2A data** our
pipeline ingests, with an SCL cloud mask. The 7 index formulas in the evalscript are byte-for-byte
ours. This is an **independent engine over the same source** — differences isolate
clipping / aggregation / resolution, not the sensor.

Three sources joined on (block, date, index), 42 cloud-free matches per index:
- **SH** — independent 10 m baseline
- **ours** — our harness full-res baseline, AOI-clipped (Phase 1)
- **stored** — the persisted production block aggregate

> **On "flexible AoI":** not needed. Because the Statistical API *computes* over our own
> polygon on demand, we get an independent baseline on **any** AoI without depending on
> sparse public pre-baked index products. We validated on agrosina's actual blocks/dates.

---

## Result 1 — our pipeline is validated (near-exact agreement)

| index | n | bias (ours−SH) | RMSE | Pearson r |
|---|---|---|---|---|
| ndvi | 42 | +0.0004 | 0.0018 | 0.996 |
| ndmi | 42 | +0.0004 | 0.0007 | 0.999 |
| ndre | 42 | +0.0006 | 0.0011 | 0.998 |
| evi | 42 | +0.0003 | 0.0015 | 0.993 |
| savi | 42 | +0.0003 | 0.0015 | 0.996 |
| gndvi | 42 | +0.0004 | 0.0014 | 0.999 |
| ndwi | 42 | −0.0004 | 0.0014 | 0.999 |

All 7 indices agree with the independent engine to **bias ≤ ±0.0006, RMSE ≤ 0.0018, r ≥ 0.993**.
Our index math and AOI-clipped aggregation are correct. *(See `ext_scatter_ndvi.png`,
`ext_timeseries_ndvi.png`.)*

## Result 2 — the production AOI-clip bug, independently confirmed & quantified

| index | RMSE (stored vs SH) | vs ours | r (stored vs SH) |
|---|---|---|---|
| ndvi | 0.0035 | 1.9× worse | 0.984 |
| **ndmi** | **0.0087** | **12× worse** | **0.741** |
| ndre | 0.0024 | 2.2× worse | 0.987 |
| evi | 0.0030 | 2.0× worse | 0.972 |
| savi | 0.0029 | 2.0× worse | 0.983 |
| gndvi | 0.0024 | 1.7× worse | 0.997 |
| ndwi | 0.0024 | 1.7× worse | 0.997 |

The stored production aggregate (computed over the full 256² window, **not clipped to the block
polygon**) agrees 2–12× worse with the independent baseline. **NDMI is hit hardest** (r collapses
0.999 → 0.741) — the off-farm desert pixels pulled in by the un-clipped window distort the
water-stress index the most. *(See `ext_rmse_by_index.png`.)*

## Result 3 — imagery is oversampled ~5× from native resolution

The raw COG for a block is **256×256 px at ~1.96 m/pixel** (verified via rasterio:
`size=256×256, res≈1.96 m, EPSG:32636`). Our ingestion requests a **fixed 256² output**, so
Sentinel-2's native **10 m** data is resampled ~5× finer (~26× more pixels) — pure interpolation,
no real sub-10 m detail. Consequences:
- **~26× storage bloat** for zero accuracy gain (our means still matched SH to RMSE ≤ 0.002,
  *because* averaging interpolated pixels ≈ averaging native pixels).
- It's why stored `valid_pixel_count = 65536 = 256²` is constant for every block — that's the
  whole raster, which is also the mechanism of the AOI-clip bug.
- Pixel size **varies per block** (bbox/256), so the grid module's `native_pixel_m = 10 m` /
  "≥4 pixels" guardrails don't match the actual stored raster grid.

---

## Recommendations

1. **Fix the AOI clipping** in the stored block aggregate (confirmed 2–12× error, worst on NDMI)
   and backfill. This is the highest-value fix.
2. **Fetch at native 10 m**, not a fixed 256² grid — ~26× storage savings, no accuracy loss.
   (Verify first *why* 256² is requested — possibly a tile-display assumption — before changing.)
3. **Adopt the CDSE Statistical API as an ongoing QA cross-check** — it's free, uses creds we
   already have, and catches clipping/resolution regressions automatically.

## Optional next layer — true sensor independence

CDSE Statistical API shares our source data. For sensor/processing independence, **Google Earth
Engine** (S2_SR_HARMONIZED, its own cloud masking) over the same polygons/dates would be the
gold-standard cross-check — needs a Google/GEE account + auth (user action).

*Artifacts: `external_baseline.py`, `external_baseline.csv`, `stored_aggregates.csv`,
`compare.py`, `out/compare_joined.csv`, `out/ext_*.png`.*
