"""Pure zonal-statistics helper for the grid module.

Given an in-memory raster (numpy array + rasterio Affine transform)
and a cell polygon's WKT, compute mean/min/max/std_dev/valid_pixel_count
over the pixels that fall inside the polygon.

Kept rasterio-local (rasterio.features.geometry_mask is the cheapest
way to project a polygon onto an existing raster grid) but otherwise
free of IO. The Celery task hands in arrays it already loaded for the
per-index COG write; we don't re-read from S3.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping


@dataclass(frozen=True, slots=True)
class CellAggregates:
    """Per-(scene, cell, index) summary — maps 1:1 to block_grid_aggregates
    columns (minus the percentiles, which add little signal at cell grain).
    """

    mean: Decimal | None
    min: Decimal | None
    max: Decimal | None
    std_dev: Decimal | None
    valid_pixel_count: int
    total_pixel_count: int


def _quantize(value: float | np.floating[Any]) -> Decimal:
    """Round to 4 fractional digits to match NUMERIC(7,4)."""
    return Decimal(f"{float(value):.4f}")


def compute_cell_aggregates(
    *,
    raster: NDArray[np.float32],
    transform: Any,
    cell_polygon_wkt: str,
) -> CellAggregates:
    """Mask ``raster`` to the cell polygon and aggregate.

    ``transform`` is a ``rasterio.Affine`` — taken from the index COG's
    profile. ``cell_polygon_wkt`` must be in the same CRS as the
    raster (the grid module stores cell geometry in the imagery
    product's UTM SRID; raw COGs are written in that same SRID, so the
    SRIDs match by construction).

    Returns NULL-valued ``mean``/``min``/``max``/``std_dev`` when no
    pixel inside the cell carries a non-NaN value (cloud-masked cell,
    cell falling entirely off the raster, etc.). ``valid_pixel_count``
    and ``total_pixel_count`` are always set.
    """
    poly = shapely_wkt.loads(cell_polygon_wkt)
    if poly.is_empty:
        return CellAggregates(None, None, None, None, 0, 0)

    # geometry_mask returns True OUTSIDE the polygon; invert to get the
    # "inside" mask, then combine with the raster's NaN/valid mask.
    inside = ~geometry_mask(
        [mapping(poly)],
        out_shape=raster.shape,
        transform=transform,
        invert=False,
        all_touched=False,
    )
    total = int(inside.sum())
    if total == 0:
        return CellAggregates(None, None, None, None, 0, 0)

    values = raster[inside]
    valid_mask = ~np.isnan(values)
    valid_count = int(valid_mask.sum())
    if valid_count == 0:
        return CellAggregates(None, None, None, None, 0, total)

    valid_values = values[valid_mask]
    return CellAggregates(
        mean=_quantize(np.mean(valid_values)),
        min=_quantize(np.min(valid_values)),
        max=_quantize(np.max(valid_values)),
        std_dev=_quantize(np.std(valid_values)) if valid_count >= 2 else None,
        valid_pixel_count=valid_count,
        total_pixel_count=total,
    )
