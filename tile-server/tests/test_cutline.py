"""The cutline algorithm: what it masks, and what it leaves alone.

Images here are built in EPSG:4326 so the reprojection step is an
identity and every assertion can name an exact pixel. The rule under
test is the one the border depends on: a pixel belongs to the farm when
its CENTRE is inside the boundary.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely.geometry
from rasterio.crs import CRS
from rio_tiler.models import ImageData

from agripulse_tiles import cutline as mod
from agripulse_tiles.cutline import Cutline

WGS84 = CRS.from_epsg(4326)

# A 10x10 image over 0..10 degrees, so one pixel is one degree and pixel
# centres sit on the half degrees.
IMAGE_BOUNDS = (0.0, 0.0, 10.0, 10.0)

# Covers pixel centres 2.5 .. 7.5 in both axes: five pixels of ten.
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[2.0, 2.0], [8.0, 2.0], [8.0, 8.0], [2.0, 8.0], [2.0, 2.0]]],
}


# The same polygon as a shapely geometry, for the tests that call the mask
# builder directly rather than through the algorithm.
SHAPE = shapely.geometry.shape(SQUARE)


@pytest.fixture(autouse=True)
def _clear_caches():
    mod.reset_caches()
    yield
    mod.reset_caches()


def make_image(value: float = 0.5, mask: np.ndarray | None = None) -> ImageData:
    data = np.full((1, 10, 10), value, dtype="float32")
    array = np.ma.MaskedArray(data, mask=np.zeros_like(data, dtype=bool) if mask is None else mask)
    return ImageData(array, crs=WGS84, bounds=IMAGE_BOUNDS)


def publish(monkeypatch, geometry) -> None:
    """Stand in for the boundary object in storage."""
    monkeypatch.setattr(mod, "_load_cached", lambda aoi: geometry)


def test_masks_outside_and_keeps_inside(monkeypatch):
    publish(monkeypatch, SQUARE)

    out = Cutline(aoi="abcd1234")(make_image())

    inside = ~out.array.mask[0]
    assert inside.sum() == 36  # 6x6 pixel centres fall inside 2..8
    assert inside[5, 5]
    assert not inside[0, 0]
    assert not inside[9, 9]


def test_row_above_the_border_is_cut(monkeypatch):
    """The row whose centres sit at 8.5 is outside a boundary ending at 8."""
    publish(monkeypatch, SQUARE)

    out = Cutline(aoi="abcd1234")(make_image())

    # Rows are top-down: row 1 holds y=8.5, row 2 holds y=7.5.
    assert out.array.mask[0][1].all()
    assert not out.array.mask[0][2][2:8].any()


def test_existing_mask_is_kept(monkeypatch):
    """A cloud pixel inside the farm stays masked."""
    publish(monkeypatch, SQUARE)
    mask = np.zeros((1, 10, 10), dtype=bool)
    mask[0, 5, 5] = True

    out = Cutline(aoi="abcd1234")(make_image(mask=mask))

    assert out.array.mask[0][5, 5]
    assert not out.array.mask[0][5, 4]


def test_missing_boundary_returns_the_image_untouched(monkeypatch):
    publish(monkeypatch, None)
    img = make_image()

    out = Cutline(aoi="abcd1234")(img)

    assert out is img


def test_bad_aoi_never_reads_storage(monkeypatch):
    def explode(aoi):  # pragma: no cover - the point is that it is not called
        raise AssertionError("storage was read for a rejected aoi")

    monkeypatch.setattr(mod, "_load_cached", explode)
    img = make_image()

    assert Cutline(aoi="../../etc/passwd")(img) is img
    assert Cutline(aoi="ab")(img) is img


def test_image_clear_of_the_boundary_is_fully_masked(monkeypatch):
    publish(monkeypatch, SQUARE)
    far = ImageData(
        np.ma.MaskedArray(np.full((1, 10, 10), 0.5, dtype="float32")),
        crs=WGS84,
        bounds=(100.0, 40.0, 110.0, 50.0),
    )

    out = Cutline(aoi="abcd1234")(far)

    assert out.array.mask.all()


def test_multipolygon_is_supported(monkeypatch):
    publish(
        monkeypatch,
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0], [0.0, 0.0]]],
                [[[7.0, 7.0], [10.0, 7.0], [10.0, 10.0], [7.0, 10.0], [7.0, 7.0]]],
            ],
        },
    )

    out = Cutline(aoi="abcd1234")(make_image())

    inside = ~out.array.mask[0]
    assert inside.sum() == 18  # 3x3 pixels in each of the two parts
    assert inside[9, 0]  # bottom-left part
    assert inside[0, 9]  # top-right part
    assert not inside[5, 5]


@pytest.mark.parametrize(
    "document",
    [
        SQUARE,
        {"type": "Feature", "geometry": SQUARE, "properties": {}},
        {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": SQUARE}]},
    ],
)
def test_reads_geometry_feature_or_collection(document):
    assert mod._geometry_of(document) == SQUARE


@pytest.mark.parametrize(
    "document",
    [None, {}, {"type": "Point", "coordinates": [1, 2]}, {"type": "FeatureCollection", "features": []}],
)
def test_rejects_documents_that_are_not_an_area(document):
    assert mod._geometry_of(document) is None


def test_missing_boundary_is_not_re_read_within_the_ttl(monkeypatch):
    calls = []

    def count(aoi):
        calls.append(aoi)
        return None

    monkeypatch.setattr(mod, "_load_cached", count)

    assert mod.boundary_geometry("abcd1234") is None
    assert mod.boundary_geometry("abcd1234") is None

    assert len(calls) == 1


def test_missing_boundary_is_re_read_after_the_ttl(monkeypatch):
    calls = []

    def count(aoi):
        calls.append(aoi)
        return None

    monkeypatch.setattr(mod, "_load_cached", count)
    clock = [0.0]
    monkeypatch.setattr(mod, "_now", lambda: clock[0])

    assert mod.boundary_geometry("abcd1234") is None
    clock[0] = mod.MISSING_TTL_S + 1.0
    assert mod.boundary_geometry("abcd1234") is None

    assert len(calls) == 2


def test_a_tile_wholly_inside_the_farm_is_returned_untouched(monkeypatch):
    """The common case once a viewer zooms in: nothing to cut, no work."""
    publish(monkeypatch, SQUARE)
    img = ImageData(
        np.ma.MaskedArray(np.full((1, 10, 10), 0.5, dtype="float32")),
        crs=WGS84,
        bounds=(3.0, 3.0, 4.0, 4.0),
    )

    assert Cutline(aoi="abcd1234")(img) is img


@pytest.mark.parametrize("block", [8, 16, 32, 64])
def test_the_block_decomposition_agrees_with_rasterio(block):
    """`_inside_mask` must answer exactly what a full rasterise would.

    The blocks are an optimisation, not a different rule, so the invariant
    is equality with `geometry_mask` - including for a block size that does
    not divide the image.
    """
    from rasterio.features import geometry_mask
    from rasterio.transform import from_bounds

    from agripulse_tiles.cutline import _inside_mask

    # 100 is not a multiple of any block size here, so the trailing partial
    # block is exercised every time.
    transform = from_bounds(0.0, 0.0, 10.0, 10.0, 100, 100)
    reference = geometry_mask(
        [SHAPE], out_shape=(100, 100), transform=transform, invert=True, all_touched=False
    )

    got = _inside_mask(SHAPE, transform, 100, 100, block=block)

    assert got.shape == reference.shape
    assert (got == reference).all()
