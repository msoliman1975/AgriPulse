"""Pure geometry helpers for the grid module.

Two responsibilities:

  * :func:`validate_cell_size` — enforce the four guardrails from the
    V1 design (hard floor, soft floor, multiple-of-native, cell-count
    ceiling). Returns ``None`` if valid, else a human-readable reason.

  * :func:`generate_cells` — given a block's UTM polygon (as WKT), a
    cell size in metres, and the UTM SRID's natural snap-to origin
    ``(0, 0)``, yield (row_idx, col_idx, cell_polygon_wkt,
    clipped_area_m2). The caller does the DB writes.

The grid is anchored at ``(floor(min_x / s) * s, floor(min_y / s) * s)``
so neighbouring blocks in the same UTM zone with the same ``cell_size_m``
produce perfectly aligned cells — a key V1 requirement (we don't want a
block-split to desync the grid).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon, box

# Guardrail tunables. The values are intentionally conservative for V1;
# raise them only when there's evidence the limit is wrong, not because
# someone wants a one-off bigger grid.
MIN_PIXELS_PER_CELL: int = 4
MAX_CELLS_PER_BLOCK: int = 5_000


@dataclass(frozen=True)
class GeneratedCell:
    """One cell produced by :func:`generate_cells`."""

    row_idx: int
    col_idx: int
    geom_wkt: str  # Polygon in the same SRID as the input boundary.
    area_m2: float


def validate_cell_size(
    *,
    cell_size_m: Decimal,
    native_pixel_m: Decimal,
    block_area_m2: Decimal,
) -> str | None:
    """Return ``None`` if the cell size passes every guardrail, else the
    first violation as a user-facing string.

    Order matters: cheap checks first, so the error message points at
    the most fundamental problem rather than a downstream symptom.
    """
    cs = float(cell_size_m)
    np_ = float(native_pixel_m)

    # 1. Hard floor — never finer than native pixel.
    if cs < np_:
        return (
            f"Cell size {cs:g}m is below the source's native pixel "
            f"({np_:g}m). Aggregation at this size would be interpolation, not signal."
        )

    # 2. Integer multiple — clean raster alignment.
    ratio = cs / np_
    if not math.isclose(ratio, round(ratio), abs_tol=1e-3):
        return (
            f"Cell size must be an integer multiple of the source's "
            f"native pixel ({np_:g}m). Try {math.floor(ratio) * np_:g}m or "
            f"{math.ceil(ratio) * np_:g}m."
        )

    # 3. Soft floor — at least N native pixels per cell so aggregation
    # has statistical meaning.
    pixels_per_cell = (cs / np_) ** 2
    if pixels_per_cell < MIN_PIXELS_PER_CELL:
        recommended = math.ceil(np_ * math.sqrt(MIN_PIXELS_PER_CELL))
        return (
            f"Cell size {cs:g}m gives only {int(pixels_per_cell)} native "
            f"pixels per cell. Minimum {recommended}m recommended (≥{MIN_PIXELS_PER_CELL} pixels)."
        )

    # 4. Ceiling — don't blow up storage. Use square approximation;
    # the actual count after clipping to the block boundary is smaller,
    # so this is a generous bound.
    if block_area_m2 > 0:
        cells = float(block_area_m2) / (cs**2)
        if cells > MAX_CELLS_PER_BLOCK:
            return (
                f"Cell size {cs:g}m would create about {int(cells)} cells "
                f"for this block (cap: {MAX_CELLS_PER_BLOCK}). Use a larger cell."
            )

    return None


def estimate_cell_count(
    *,
    boundary_utm_wkt: str,
    cell_size_m: Decimal,
) -> int:
    """Cheap upper-bound estimate — bounding-box cells, not clipped count."""
    poly = shapely_wkt.loads(boundary_utm_wkt)
    if poly.is_empty:
        return 0
    cs = float(cell_size_m)
    min_x, min_y, max_x, max_y = poly.bounds
    cols = math.ceil((max_x - min_x) / cs)
    rows = math.ceil((max_y - min_y) / cs)
    return cols * rows


def generate_cells(
    *,
    boundary_utm_wkt: str,
    cell_size_m: Decimal,
) -> Iterator[GeneratedCell]:
    """Yield (row_idx, col_idx, polygon_wkt, area_m2) for each cell that
    intersects ``boundary_utm``.

    Cells are clipped to the block boundary so each cell's area_m2 is
    the portion actually inside the block (matters for edge cells and
    for pivot blocks where the square grid spills outside the circle).

    The grid is snapped to ``(floor(min_x / s) * s, floor(min_y / s) * s)``
    in the source SRID — i.e. to the UTM zone's natural origin, not to
    the block's bounding box. Two adjacent blocks at the same cell size
    therefore share cell edges.
    """
    poly = shapely_wkt.loads(boundary_utm_wkt)
    if poly.is_empty:
        return

    cs = float(cell_size_m)
    min_x, min_y, max_x, max_y = poly.bounds

    # Snap origin so the grid aligns to the UTM zone's natural axes.
    # Row/col indices are *global* (relative to UTM (0, 0)) so two
    # adjacent blocks at the same cell size share indices on shared
    # cells — see test_generate_cells_assigns_global_indices.
    start_col = math.floor(min_x / cs)
    start_row = math.floor(min_y / cs)
    end_col = math.ceil(max_x / cs)
    end_row = math.ceil(max_y / cs)

    for global_row in range(start_row, end_row):
        for global_col in range(start_col, end_col):
            cell_min_x = global_col * cs
            cell_min_y = global_row * cs
            cell = box(cell_min_x, cell_min_y, cell_min_x + cs, cell_min_y + cs)
            if not cell.intersects(poly):
                continue
            clipped = cell.intersection(poly)
            # Filter sub-meter slivers: anything below 1 m² rounds to 0.00
            # under NUMERIC(10,2) and trips ck_grid_cells_area_positive,
            # and a sub-meter cell has no analytic value anyway.
            if clipped.is_empty or clipped.area < 1.0:
                continue
            # Force to a single Polygon (some intersections produce a
            # MultiPolygon at concave edges; keep the largest piece).
            if clipped.geom_type == "MultiPolygon":
                pieces = sorted(clipped.geoms, key=lambda g: g.area, reverse=True)
                clipped = pieces[0]
            if not isinstance(clipped, Polygon):
                continue
            yield GeneratedCell(
                row_idx=global_row,
                col_idx=global_col,
                geom_wkt=clipped.wkt,
                area_m2=float(clipped.area),
            )


