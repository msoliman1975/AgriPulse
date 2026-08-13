"""Refusing a farm the provider could not return in one request.

A block AOI is sub-kilometre and the fetch path never had to ask. A farm is
not, and Sentinel Hub's Process API caps output at 2500 px per side. Without
this check a farm over the cap would 400 on every poll forever and record a
generic fetch error — "imagery is broken" rather than "this farm is too big
for one request".
"""

from __future__ import annotations

import pytest

from app.modules.imagery.farm_aoi import (
    PROCESS_API_MAX_PX_PER_SIDE,
    FarmAoiTooLargeError,
    aoi_size_px,
    check_fetchable,
    utm_bbox,
)

# Bashier Elkhier's real extent, in metres (EPSG:32636).
REFERENCE_FARM = {
    "type": "Polygon",
    "coordinates": [
        [
            [464690.0, 3326890.0],
            [465490.0, 3326890.0],
            [465490.0, 3327990.0],
            [464690.0, 3327990.0],
            [464690.0, 3326890.0],
        ]
    ],
}


def _square(side_m: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [side_m, 0.0], [side_m, side_m], [0.0, side_m], [0.0, 0.0]]],
    }


def test_reference_farm_is_the_size_the_cog_actually_was():
    # The stitched raster for this farm measured 80x110 at 10 m; the fetch
    # path must predict the same, or the guard is measuring something else.
    assert aoi_size_px(REFERENCE_FARM, resolution_m=10.0) == (80, 110)


def test_reference_farm_passes():
    assert check_fetchable(REFERENCE_FARM, resolution_m=10.0) == (80, 110)


def test_bbox_ignores_ring_structure():
    assert utm_bbox(REFERENCE_FARM) == (464690.0, 3326890.0, 465490.0, 3327990.0)


def test_multipolygon_spans_every_part():
    # A farm split into two detached parcels is bounded by both, which is
    # exactly the case where a fetch quietly becomes enormous.
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            _square(100.0)["coordinates"],
            [[[10000.0, 10000.0], [10100.0, 10000.0], [10100.0, 10100.0], [10000.0, 10000.0]]],
        ],
    }
    assert utm_bbox(multi) == (0.0, 0.0, 10100.0, 10100.0)


def test_a_partly_covered_pixel_still_counts():
    # 105 m at 10 m is 11 pixels, not 10 — the provider returns the pixel that
    # the AOI clips into.
    assert aoi_size_px(_square(105.0), resolution_m=10.0) == (11, 11)


def test_a_farm_over_the_cap_is_refused_before_the_request():
    # 25.01 km at 10 m is 2501 px — one over.
    too_big = _square(25_010.0)
    with pytest.raises(FarmAoiTooLargeError) as exc:
        check_fetchable(too_big, resolution_m=10.0)
    assert exc.value.width_px == 2501
    assert exc.value.max_px == PROCESS_API_MAX_PX_PER_SIDE
    # The message has to name the size, or an operator cannot tell how far
    # over the farm is.
    assert "2501" in str(exc.value)


def test_exactly_at_the_cap_is_allowed():
    assert check_fetchable(_square(25_000.0), resolution_m=10.0) == (2500, 2500)


def test_resolution_changes_the_verdict():
    # The same farm that is too big at 10 m fits at 20 m; the guard is about
    # the request, not the land.
    farm = _square(30_000.0)
    with pytest.raises(FarmAoiTooLargeError):
        check_fetchable(farm, resolution_m=10.0)
    assert check_fetchable(farm, resolution_m=20.0) == (1500, 1500)


def test_one_long_side_is_enough_to_refuse():
    # Cap is per side, so a thin 40 km strip is refused even though its area
    # is small.
    strip = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [40_000.0, 0.0], [40_000.0, 500.0], [0.0, 500.0], [0.0, 0.0]]],
    }
    with pytest.raises(FarmAoiTooLargeError) as exc:
        check_fetchable(strip, resolution_m=10.0)
    assert (exc.value.width_px, exc.value.height_px) == (4000, 50)


def test_empty_geometry_is_an_error_not_a_zero_sized_fetch():
    with pytest.raises(ValueError, match="no coordinates"):
        aoi_size_px({"type": "Polygon", "coordinates": []}, resolution_m=10.0)


def test_nonpositive_resolution_is_rejected():
    with pytest.raises(ValueError, match="must be positive"):
        aoi_size_px(REFERENCE_FARM, resolution_m=0.0)
