#!/usr/bin/env python
"""Grid-size accuracy experiment — re-grid historical scenes at many cell sizes.

Runs INSIDE the heavy worker pod (reuses the app's exact rasterio / index /
grid code + the pod's R2 creds). Read-only: reads raw_bands COGs from object
storage, recomputes the 7 indices per-pixel, then re-aggregates to the block
level at a sweep of grid cell sizes plus a whole-block baseline. Writes one
CSV summary row per (block, scene, index, grid_size).

The math mirrors production (app.modules.imagery.tasks.compute_indices):
  * load_raw_bands_and_aggregate -> bands + aoi_mask + transform
  * compute_all_indices          -> per-pixel index rasters
  * compute_aggregates           -> AOI-clipped full-res block truth (BASELINE)
  * per cell: rasterio.geometry_mask (all_touched=False, like grid/zonal.py),
    then mean/min/max of valid pixels.

Cell->block rollup is done TWO ways:
  * weighted   = sum(cell_mean * valid_px) / sum(valid_px)  == grid-invariant truth
  * unweighted = mean(cell_mean)                            == naive, drifts on edges

Usage (in-pod):
  python regrid_experiment.py --manifest manifest.json --out grid_results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from decimal import Decimal

import numpy as np
from rasterio.features import geometry_mask
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape

from app.modules.grid.geometry import generate_cells
from app.modules.imagery._rasterio_io import load_raw_bands_and_aggregate
from app.modules.indices.computation import (
    S2_L2A_BAND_ORDER,
    compute_aggregates,
    compute_all_indices,
)
from app.shared.storage import get_storage_client

# Grid cell sizes (metres). 10 m is intentionally excluded: it is a single
# native S2 pixel, blocked by the >=4-pixel soft floor, and statistically
# meaningless. "block" (whole-block single cell) is appended as the coarse
# endpoint of every curve.
GRID_SIZES_M = [20, 30, 40, 50, 60, 70, 80]
Z_ANOMALY = 2.0  # |z| threshold for "anomalous cell" detectability metric

CSV_FIELDS = [
    "block", "date", "index", "grid_m",
    "n_cells_total", "n_cells_valid", "n_cells_dropped",
    "baseline_mean", "baseline_std", "baseline_valid_px",
    "weighted_mean", "unweighted_mean",
    "w_minus_base", "u_minus_base",
    "cellmean_std", "cellmean_iqr", "cellmean_cov",
    "cellmean_min", "cellmean_max", "cellmean_range",
    "pix_min", "pix_max",
    "anom_n_z2", "anom_frac_z2", "max_abs_z",
    "cloud_pct",
]


def _f(x: object) -> float | None:
    return None if x is None else float(x)


def _cell_inside_masks(cells_wkt: list[str], out_shape: tuple[int, int], transform: object):
    """Yield (inside_mask, n_inside) per cell — geometry_mask exactly as grid/zonal.py."""
    for wkt_str in cells_wkt:
        poly = shapely_wkt.loads(wkt_str)
        if poly.is_empty:
            continue
        inside = ~geometry_mask(
            [mapping(poly)],
            out_shape=out_shape,
            transform=transform,
            invert=False,
            all_touched=False,
        )
        n = int(inside.sum())
        if n == 0:
            continue
        yield inside


def process_scene(block: dict, scene: dict, bucket: str, writer: csv.DictWriter) -> int:
    """Re-grid one scene across all grid sizes; write rows. Returns rows written."""
    raw_uri = f"s3://{bucket}/{scene['raw_key']}"
    boundary_geojson = block["boundary_utm_geojson"]
    boundary_wkt = shape(boundary_geojson).wkt

    bands, aoi_mask, profile = load_raw_bands_and_aggregate(
        raw_uri,
        band_names=tuple(S2_L2A_BAND_ORDER),
        aoi_geojson_utm36n=boundary_geojson,
    )
    transform = profile["transform"]
    out_shape = aoi_mask.shape

    indices = compute_all_indices(bands)
    # Baseline (AOI-clipped full-res truth) + AOI-masked rasters for cells.
    baseline: dict[str, object] = {}
    masked: dict[str, np.ndarray] = {}
    for code, raster in indices.items():
        baseline[code] = compute_aggregates(raster, aoi_mask)
        masked[code] = np.where(aoi_mask, raster, np.float32("nan"))

    # Precompute the cell list (and inside-masks) per grid size ONCE, reused
    # across all 7 indices — geometry_mask is the hot path.
    grid_levels: list[tuple[str, list[np.ndarray]]] = []
    for g in GRID_SIZES_M:
        cells_wkt = [c.geom_wkt for c in generate_cells(
            boundary_utm_wkt=boundary_wkt, cell_size_m=Decimal(str(g)))]
        grid_levels.append((str(g), list(_cell_inside_masks(cells_wkt, out_shape, transform))))
    grid_levels.append(("block", list(_cell_inside_masks([boundary_wkt], out_shape, transform))))

    rows = 0
    for grid_label, inside_masks in grid_levels:
        n_total = len(inside_masks)
        for code in indices:
            mr = masked[code]
            cell_means: list[float] = []
            cell_weights: list[int] = []
            pix_lo: list[float] = []
            pix_hi: list[float] = []
            for inside in inside_masks:
                vals = mr[inside]
                valid = vals[~np.isnan(vals)]
                if valid.size == 0:
                    continue
                cell_means.append(float(valid.mean()))
                cell_weights.append(int(valid.size))
                pix_lo.append(float(valid.min()))
                pix_hi.append(float(valid.max()))

            n_valid = len(cell_means)
            base = baseline[code]
            row = {
                "block": block["block"], "date": scene["date"][:10], "index": code,
                "grid_m": grid_label,
                "n_cells_total": n_total, "n_cells_valid": n_valid,
                "n_cells_dropped": n_total - n_valid,
                "baseline_mean": _f(base.mean), "baseline_std": _f(base.std_dev),
                "baseline_valid_px": base.valid_pixel_count,
                "cloud_pct": scene.get("cloud_pct"),
            }
            if n_valid == 0:
                writer.writerow(row)
                rows += 1
                continue

            cm = np.asarray(cell_means, dtype=float)
            w = np.asarray(cell_weights, dtype=float)
            weighted = float((cm * w).sum() / w.sum())
            unweighted = float(cm.mean())
            std_cm = float(cm.std()) if n_valid >= 2 else 0.0
            iqr = float(np.percentile(cm, 75) - np.percentile(cm, 25)) if n_valid >= 2 else 0.0
            base_mean = _f(base.mean)
            if std_cm > 0:
                z = (cm - cm.mean()) / std_cm
                anom_n = int((np.abs(z) >= Z_ANOMALY).sum())
                max_abs_z = float(np.abs(z).max())
            else:
                anom_n, max_abs_z = 0, 0.0
            row.update({
                "weighted_mean": weighted, "unweighted_mean": unweighted,
                "w_minus_base": None if base_mean is None else weighted - base_mean,
                "u_minus_base": None if base_mean is None else unweighted - base_mean,
                "cellmean_std": std_cm, "cellmean_iqr": iqr,
                "cellmean_cov": (std_cm / abs(unweighted)) if unweighted else None,
                "cellmean_min": float(cm.min()), "cellmean_max": float(cm.max()),
                "cellmean_range": float(cm.max() - cm.min()),
                "pix_min": min(pix_lo), "pix_max": max(pix_hi),
                "anom_n_z2": anom_n, "anom_frac_z2": anom_n / n_valid,
                "max_abs_z": max_abs_z,
            })
            writer.writerow(row)
            rows += 1
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        blocks = json.load(fh)

    bucket = get_storage_client().bucket
    print(f"[regrid] bucket={bucket} blocks={[b['block'] for b in blocks]}", flush=True)

    total_rows = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for block in blocks:
            scenes = block.get("scenes") or []
            print(f"[regrid] {block['block']}: {len(scenes)} scenes", flush=True)
            for i, scene in enumerate(scenes, 1):
                if not scene.get("raw_key"):
                    print(f"  ! {block['block']} {scene.get('date')}: no raw_key, skip", flush=True)
                    continue
                try:
                    n = process_scene(block, scene, bucket, writer)
                    total_rows += n
                    print(f"  [{i}/{len(scenes)}] {scene['date'][:10]} -> {n} rows", flush=True)
                    fh.flush()
                except Exception as exc:  # keep going; one bad scene shouldn't kill the run
                    print(f"  ! {block['block']} {scene.get('date')}: {exc}", flush=True)
                    traceback.print_exc()
    print(f"[regrid] DONE rows={total_rows} -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
