"""Is this farm small enough to fetch in one request?

A block AOI is sub-kilometre and the fetch path never had to ask. A farm is
not: Sentinel Hub's Process API caps output at 2500 pixels per side, which at
10 m is 25 km. Most farms are nowhere near it, but the failure mode for one
that is would be a 400 from the provider on every poll forever, recorded as a
generic fetch error — the sort of thing that reads as "imagery is broken"
rather than "this farm is too big for one request".

So the size is checked before the request is made, and refused with a reason
that says what to do about it.
"""

from __future__ import annotations

from typing import Any, NamedTuple

#: Sentinel Hub Process API output limit, per side, in pixels.
PROCESS_API_MAX_PX_PER_SIDE = 2500


class FarmAoiTooLargeError(Exception):
    """The farm's bounding box exceeds what one provider request can return."""

    def __init__(self, *, width_px: int, height_px: int, max_px: int) -> None:
        self.width_px = width_px
        self.height_px = height_px
        self.max_px = max_px
        super().__init__(
            f"farm AOI is {width_px}x{height_px} px at this resolution, "
            f"over the {max_px} px/side provider limit"
        )


def utm_bbox(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    """2D bbox of a Polygon/MultiPolygon whose coordinates are already metres."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(node: Any) -> None:
        # A coordinate is the first list of two-or-more numbers we reach.
        if (
            isinstance(node, list | tuple)
            and len(node) >= 2
            and all(isinstance(v, int | float) for v in node[:2])
        ):
            xs.append(float(node[0]))
            ys.append(float(node[1]))
            return
        if isinstance(node, list | tuple):
            for child in node:
                walk(child)

    walk(geojson.get("coordinates", []))
    if not xs:
        raise ValueError("geometry has no coordinates")
    return min(xs), min(ys), max(xs), max(ys)


def aoi_size_px(
    boundary_utm_geojson: dict[str, Any],
    *,
    resolution_m: float,
) -> tuple[int, int]:
    """How many pixels a fetch of this AOI would return, (width, height)."""
    if resolution_m <= 0:
        raise ValueError("resolution_m must be positive")
    min_x, min_y, max_x, max_y = utm_bbox(boundary_utm_geojson)
    # Ceil, because a partially covered pixel is still a pixel returned.
    width = int(-(-(max_x - min_x) // resolution_m))
    height = int(-(-(max_y - min_y) // resolution_m))
    return width, height


def check_fetchable(
    boundary_utm_geojson: dict[str, Any],
    *,
    resolution_m: float,
    max_px_per_side: int = PROCESS_API_MAX_PX_PER_SIDE,
) -> tuple[int, int]:
    """Return the AOI size, or raise if the provider could not return it.

    Called before the request rather than after the 400, so a farm that is too
    big says so once with its actual size instead of failing opaquely on every
    poll.
    """
    width, height = aoi_size_px(boundary_utm_geojson, resolution_m=resolution_m)
    if width > max_px_per_side or height > max_px_per_side:
        raise FarmAoiTooLargeError(width_px=width, height_px=height, max_px=max_px_per_side)
    return width, height


def product_resolution_m(product: dict[str, Any]) -> float | None:
    """The product's native ground sample distance, if it is known.

    The farm grid is pinned to this rather than to whatever grid the first
    block happened to arrive on — see farm_raster's module docstring. It lives
    here beside the size check because the API needs the same number to tell an
    operator whether a farm can be fetched at all, and the API must not import
    the worker's task module to get it.
    """
    raw = product.get("resolution_m")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class FarmAoiFit(NamedTuple):
    """Whether one farm fits in one provider request, and by how much."""

    fits: bool
    width_px: int | None
    height_px: int | None
    max_px: int


def measure_fit(
    boundary_utm_geojson: dict[str, Any] | None,
    *,
    resolution_m: float | None,
    max_px_per_side: int = PROCESS_API_MAX_PX_PER_SIDE,
) -> FarmAoiFit:
    """Non-raising twin of `check_fetchable`, for read paths.

    Returns ``fits=True`` with no measurement when the inputs are unknown: a
    missing boundary or an unpublished resolution is not evidence that the farm
    is too big, and reporting it as too big would tell an operator to redraw a
    farm that is fine.
    """
    if boundary_utm_geojson is None or resolution_m is None:
        return FarmAoiFit(True, None, None, max_px_per_side)
    try:
        width, height = aoi_size_px(boundary_utm_geojson, resolution_m=resolution_m)
    except ValueError:
        return FarmAoiFit(True, None, None, max_px_per_side)
    return FarmAoiFit(
        width <= max_px_per_side and height <= max_px_per_side,
        width,
        height,
        max_px_per_side,
    )
