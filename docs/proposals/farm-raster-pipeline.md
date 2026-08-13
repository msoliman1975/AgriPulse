# One raster per farm

Status: **built, switched off**. Generation, rendering and farm-AOI ingestion
are all merged; no farm fetches its own boundary until someone sets
`fetch_farm_aoi` on its subscription. Written 2026-08-13 while the work was in
flight, so the measurements below are the real ones rather than estimates.

## The problem

Imagery is fetched, stored and computed **per block AOI**. A 36-block farm turns
one satellite pass into 36 rasters of roughly 50×50 pixels. Three things follow,
and all three are visible to a grower:

1. **Land outside blocks has no pixels at all.** On Bashier Elkhier the farm is
   203.4 feddan and the blocks union to 153.8 — **50.3 feddan, a quarter of the
   farm, is not "uncoloured" but unmeasured.** Abandoned ground is exactly the
   ground someone might want to bring back into production.
2. **Adjacent blocks show a dark seam.** Each block's raster is cut with
   `all_touched`, so ground on a shared edge is written into both files; drawing
   both stacks two translucent copies of it. The blocks do *not* geometrically
   overlap — measured, 4 pairs totalling ~0 m² — so the seam is entirely this
   duplication.
3. **The map cannot ask for fewer than one tile per block**, because every block
   is its own tile source. That is the floor the repaint work kept hitting.

One farm raster is about six times fewer pixels than the 36 it replaces, in one
file rather than 36.

## What is built

| Piece | State |
|---|---|
| `farms.aoi_hash`, `farm_scene_rasters` | merged (#430) |
| `merge_block_rasters` — stitch from stored bands | merged (#430) |
| `scene-assets` serves a nullable `farm` raster | merged (#430) |
| Console draws one source when a farm raster exists | merged (#431) |
| `block_masks_on_grid` + `verify_farm_raster_aggregates` | #432 |
| `imagery_farm_subscriptions` (+ migration from per-block) | #433 |
| Explicit merge grid | #434 |
| Farm-AOI ingestion (0076) | merged, gated off |

Nothing changes for a farm until `rebuild_farm_rasters` is run against it, or
`fetch_farm_aoi` is set on its farm subscription. Both are per-farm decisions
rather than deploys.

## Decision taken, 2026-08-13

Aggregates **stay on the per-block path**; the farm surface is display-only.
No stored number moves, so no series steps at the cutover. The cost is two
pipelines: an opted-in farm is fetched twice per pass — once per block for the
aggregates, once for the farm boundary for the picture. On the reference farm
that is roughly +44% fetched area (the farm's bounding box is 88 ha against
61 ha of blocks), not double, because a farm request replaces 36 small ones
rather than adding to them.

That cost is exactly why `fetch_farm_aoi` defaults to FALSE. Switching a farm
on is a deliberate act with a quota consequence.

## The grid, which was not what it looked like

Block rasters **do not share a pixel grid**. Three blocks of the same pass:

| pixel size | origin |
|---|---|
| 9.903 × 10.076 m | 464709.07, 3327497.56 |
| 10.036 × 10.056 m | 464703.99, 3328003.39 |
| 10.134 × 9.938 m | 465204.22, 3327500.58 |

The provider returns a fixed-**size** image fitted to each requested AOI, not a
fixed-**resolution** window on a shared lattice. This was caught only by merging
two real rasters and noticing that 5,000 input pixels produced 5,050 finite
ones, which is impossible on a shared grid.

So the merge pins an explicit grid — product resolution, extent snapped to a
whole multiple of it — rather than inheriting whichever block was read first.
A side effect worth naming: today's per-block rasters are each on their own
arbitrary grid, so two blocks of the same farm are not directly comparable
pixel to pixel. The farm raster fixes that.

## The number the cutover turns on

Stitching Bashier Elkhier's 2026-08-10 pass (35 blocks) and re-measuring every
block off the farm surface, against the means the per-block pipeline stored:

```
compared 35 blocks
mean |delta| = 0.00146 NDVI
max  |delta| = 0.00744 NDVI   (stored 0.2266 vs farm 0.2340)
```

About 0.7% relative, worst case 3%. It is resampling error from putting
9.9–10.13 m grids onto a common 10 m lattice, and it is **not zero**. Three ways
to take it, none of them free:

- **Accept it.** Every block's history gets a small step at the cutover date.
  Cheapest, and the step is smaller than the width of a legend class — but it is
  a real discontinuity in a series people read for trends.
- **Recompute all history from farm rasters.** No step, one consistent method,
  but every historical number moves slightly and the recompute is hours of
  worker time.
- **Keep aggregates on the per-block path** and use the farm raster only for
  display. No numbers move at all; two pipelines to maintain, and the abandoned
  land still has no measurements behind it.

## How ingestion was built

The block fetch path is block-shaped end to end: `imagery_ingestion_jobs.block_id`,
the AOI from `get_block_boundary`, the storage key from the block's `aoi_hash`.
Rather than widen any of that, 0076 adds a parallel set:

* `imagery_farm_ingestion_jobs` — its own table. The block table is the hot path
  for every farm's daily imagery and its idempotency key is
  `UNIQUE(subscription_id, scene_id)`; making it mean two things is how a working
  pipeline gets broken by a feature nobody has switched on.
* `imagery.discover_farm_scenes` / `imagery.acquire_farm_scene`, plus a beat
  sweep that enqueues nothing until `fetch_farm_aoi` is set.
* `farm_scene_rasters.source` — `stitched` or `fetched`. A fetched surface wins
  over a stitched one for the same pass, because it covers ground no block was
  drawn around; letting a later stitch replace it would silently shrink the farm
  back to its blocks.

A fetched pass writes the same outputs a stitched one does — index COGs under the
farm's aoi hash and a `farm_scene_rasters` row — so the console draws it with no
change at all. The difference is only that the pixels are real everywhere inside
the boundary instead of only inside the blocks.

**One limit worth knowing.** Sentinel Hub's Process API returns at most 2500 px
per side, which at 10 m is 25 km. Farms are checked against that *before* the
request, so a farm too large to fetch says so once with its measured size rather
than 400-ing on every poll forever. The reference farm is 80×110 px.

Once a farm is fetched rather than stitched, the 50.3 feddan outside its blocks
finally has pixels behind it, and the "Outside blocks · X feddan" legend line
deliberately left out of #431 has something true to say.
