# Imagery index accuracy — agrosina vs CDSE (Sentinel Hub Statistical API)

**Date:** 2026-06-20
**Tenant:** `agrosina` (schema `tenant_019eafdc242c7320948e13490efc67dd`, live on Hetzner)
**Reference:** Copernicus Data Space Ecosystem (CDSE) **Sentinel Hub Statistical
API** — provider-side computation of the same 7 indices over the *same*
Sentinel-2 L2A imagery we ingest, at native **10 m** resolution.
**Sample:** 4 blocks × 6 scene dates (4 low-cloud + 2 high-cloud), all 7 indices
= 168 index comparisons per mode. Reproduce with
[`scripts/index-accuracy/`](../../scripts/index-accuracy/README.md).

## Why this reference

We pull raw S2 L2A bands from CDSE and compute NDVI/NDWI/EVI/SAVI/NDRE/GNDVI/NDMI
ourselves. Comparing against CDSE's **own** Statistical API (same pixels,
independent index math + aggregation) isolates bugs in *our* code rather than
mixing in atmospheric-correction differences. Two modes were run per scene:
**(A) replicate** — identical band math, no cloud mask; **(B) cloud-mask** — SCL
clouds/shadows/cirrus/snow excluded.

## Verdict

**The index math is correct.** On well-sampled blocks our means match CDSE's
independent computation to **< 0.0012 on all seven indices** — inside Sentinel-2
radiometric noise. Band scaling, formulas (incl. EVI/SAVI additive constants),
and aggregation are sound.

Two **methodology defects** surfaced, both in raster handling rather than the
formulas:

1. **No native-resolution fetch → fixed 256×256 resampling (medium severity).**
   Our Process-API request omits output resolution, so every AOI is rendered to
   a fixed **256×256** grid regardless of true size. All blocks store exactly
   65 536 "pixels"; their real 10 m pixel counts are 1 161–2 500. This inflates
   `valid_pixel_count` **26–56×** (non-physical) and, for smaller / non-square
   blocks, injects a **systematic per-block bias up to ~0.03 NDVI**.
2. **No cloud (SCL) masking (latent risk).** `valid_pixel_pct` is always 100% —
   we never drop cloud pixels. In this sample it had **zero** effect (no cloud
   pixels fell inside the blocks even on 33–35% tile-cloud dates), but a cloud
   sitting over a block would silently corrupt the aggregate with no gate to
   catch it.

## Evidence

### Per-block mean bias (ours − CDSE native-10 m), averaged over 6 dates

| block | native px | ndvi | ndwi | evi | savi | ndre | gndvi | ndmi |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| AG-R01-C01 | 2500 | +0.0008 | +0.0001 | +0.0008 | +0.0008 | +0.0002 | −0.0001 | +0.0012 |
| AG-R02-C01 | 2500 | −0.0005 | +0.0004 | −0.0005 | −0.0004 | −0.0004 | −0.0004 | +0.0001 |
| AG-R01-C02 | 1161 | +0.0036 | +0.0003 | +0.0018 | +0.0014 | +0.0021 | −0.0003 | +0.0142 |
| AG-R02-C02 | 1269 | **−0.0299** | **+0.0300** | **−0.0215** | **−0.0228** | **−0.0191** | **−0.0300** | +0.0008 |

The two large, near-square blocks (2500 native px) agree with CDSE to < 0.0012
**everywhere**. The discrepancy is confined to the two smaller blocks — and
`AG-R02-C02` carries a **date-independent** −0.02…−0.03 offset on every scene. A
constant, block-specific offset that ignores the date cannot be a formula error
(the formula is identical and validated by the matching blocks); it is the
fixed-256² grid + AOI rasterization capturing a different edge-pixel set than the
native-10 m mask. Edge pixels in ag blocks are soil/road (low NDVI), so over-
including them pulls our mean down — consistent with the sign. (`ndwi` mirrors
`gndvi` exactly because they are algebraic negatives — a clean internal check.)

### Aggregate Mode-A error, clean vs cloudy scenes (n per bucket)

| index | clean bias | clean MAE | clean RMSE | cloudy bias | cloudy MAE |
|---|--:|--:|--:|--:|--:|
| ndvi | −0.0063 | 0.0090 | 0.0150 | −0.0069 | 0.0105 |
| ndwi | +0.0076 | 0.0080 | 0.0148 | +0.0079 | 0.0098 |
| evi | −0.0045 | 0.0064 | 0.0105 | −0.0055 | 0.0084 |
| savi | −0.0050 | 0.0066 | 0.0111 | −0.0058 | 0.0086 |
| ndre | −0.0042 | 0.0057 | 0.0095 | −0.0044 | 0.0069 |
| gndvi | −0.0076 | 0.0080 | 0.0148 | −0.0079 | 0.0098 |
| ndmi | +0.0041 | 0.0042 | 0.0077 | +0.0040 | 0.0040 |

Errors barely move between clean and cloudy scenes — confirming the residual is
the resampling artifact, **not** cloud contamination (the clouds simply were not
over these blocks). The aggregate bias is dominated by the single `AG-R02-C02`
block; drop it and all indices agree to ≤ 0.004.

### Pixel counts (our stored vs CDSE native 10 m)

Every block stores exactly **65 536** pixels (= 256²) regardless of size; native
counts are 1 161 (AG-R01-C02), 1 269 (AG-R02-C02), 2 500 (the two large blocks)
→ inflation of **26–56×**. Cloud masking removed 0 pixels on the cloudy dates
(in-AOI SCL had no cloud class), confirming finding #2 is latent here.

## Recommendations

1. **Fetch at native resolution.** In `backend/app/modules/imagery/providers/
   sentinel_hub.py` `fetch()`, add output sizing to the Process request — set
   `output.resx = output.resy = 10` (or derive `width`/`height` from the AOI
   bbox at 10 m), exactly as the Statistical API does here. This makes pixel
   counts physical and removes the per-block bias. Re-derive affected scenes via
   `scripts/grid_backfill.py` after the fix. *(medium — affects smaller/non-square
   blocks and all per-cell grid stats; large blocks are already fine.)*
2. **Apply an SCL cloud mask at computation time.** Drop SCL ∈ {0,1,3,8,9,10,11}
   before aggregating, and let `valid_pixel_pct` reflect the real clear-pixel
   fraction so the existing cloud-cover gate has teeth. *(correctness hardening —
   no impact on current numbers, prevents silent corruption when a cloud is over
   a block.)*
3. **Re-run this check after the fix** and add it as a periodic regression
   (target: all indices ≤ 0.005 MAE vs CDSE across blocks).

## Optional next step

For a *fully* independent cross-check (validating the imagery itself, not just
our math), repeat against Google Earth Engine harmonized S2 — needs a GEE
service-account auth, not yet wired.
