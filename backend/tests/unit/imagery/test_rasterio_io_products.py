"""Unit tests for the product-aware raster IO path.

`_rasterio_io` used to assume Sentinel-2 in two places: the trailing
quality band was always read as SCL, and the index set was always the
optical nine. Both now follow the product code, and these tests pin that
against real COGs rather than mocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.modules.imagery._rasterio_io import (
    compute_and_write_indices,
    load_raw_bands_and_aggregate,
)
from app.modules.indices.computation import STANDARD_INDEX_CODES, THERMAL_INDEX_CODES

# Clear land under Landsat's bitmask; cloud high-probability under
# Sentinel-2's class enum. The same array read under the wrong ruleset
# gives the opposite answer, which is the whole point.
_QA_CLEAR_LAND = 21824
_QA_CLOUD = 22280

_AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [300000.0, 3330000.0],
            [300300.0, 3330000.0],
            [300300.0, 3329700.0],
            [300000.0, 3329700.0],
            [300000.0, 3330000.0],
        ]
    ],
}


class _FakeStorage:
    """Captures uploads instead of talking to R2."""

    bucket = "test-bucket"

    def __init__(self) -> None:
        self.put: dict[str, bytes] = {}

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.put[key] = body


def _write_cog(path: Path, bands: list[np.ndarray]) -> None:
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 10,
        "count": len(bands),
        "dtype": "float32",
        "crs": "EPSG:32636",
        "transform": from_origin(300000.0, 3330000.0, 30.0, 30.0),
    }
    with rasterio.open(path, "w", **profile) as dst:
        for index, band in enumerate(bands, start=1):
            dst.write(band.astype(np.float32), index)


def _thermal_bands(qa_value: int) -> list[np.ndarray]:
    """lwir11 (kelvin), red, nir08, then the trailing quality band."""
    return [
        np.full((10, 10), 305.0, dtype=np.float32),
        np.full((10, 10), 0.12, dtype=np.float32),
        np.full((10, 10), 0.38, dtype=np.float32),
        np.full((10, 10), float(qa_value), dtype=np.float32),
    ]


def test_landsat_quality_band_is_read_as_a_bitmask(tmp_path: Path) -> None:
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLEAR_LAND))

    _bands, _aoi_mask, cloud_mask, _profile = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )

    # 21824 is clear land: bit 6 set, no failure bits.
    assert not cloud_mask.any()


def test_landsat_cloud_bits_mask_the_scene(tmp_path: Path) -> None:
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLOUD))

    _bands, _aoi_mask, cloud_mask, _profile = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )

    assert cloud_mask.all()


def test_the_two_rulesets_disagree_on_the_same_quality_values(tmp_path: Path) -> None:
    """Reading QA_PIXEL with SCL rules is not a near-miss, it is wrong.

    21824 is clear land to Landsat. To the SCL class list it is simply
    not a member, so it also reads clear — but 22280 is *cloud* to
    Landsat and equally a non-member to SCL. Applying the wrong ruleset
    therefore lets a fully clouded scene through as clean data.
    """
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLOUD))

    _b, _a, landsat_mask, _p = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )
    _b2, _a2, s2_mask, _p2 = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="s2_l2a",
    )

    assert landsat_mask.all(), "Landsat rules see the cloud bit"
    assert not s2_mask.any(), "SCL rules see nothing at all — the wrong answer"


def test_default_product_code_keeps_the_sentinel2_behaviour(tmp_path: Path) -> None:
    """Existing callers pass no product_code and must be unaffected."""
    cog = tmp_path / "raw.tif"
    # Seven science bands + SCL class 9 (cloud high-probability).
    bands = [np.full((10, 10), 0.2, dtype=np.float32) for _ in range(7)]
    bands.append(np.full((10, 10), 9.0, dtype=np.float32))
    _write_cog(cog, bands)

    _b, _a, cloud_mask, _p = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        aoi_geojson_utm36n=_AOI,
    )
    assert cloud_mask.all()


def test_thermal_product_writes_exactly_the_thermal_indices(tmp_path: Path) -> None:
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLEAR_LAND))
    bands, aoi_mask, cloud_mask, profile = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )
    storage = _FakeStorage()

    aggregates, keys, rasters = compute_and_write_indices(
        bands_arrays=bands,
        aoi_mask=aoi_mask,
        cloud_mask=cloud_mask,
        profile=profile,
        storage=storage,  # type: ignore[arg-type]
        provider_code="landsat_pc",
        product_code="landsat_c2_l2_st",
        scene_id="LC08_TEST",
        aoi_hash="deadbeef",
        air_temp_c=31.0,
    )

    assert set(keys) == set(THERMAL_INDEX_CODES)
    assert set(rasters) == set(THERMAL_INDEX_CODES)
    assert not set(keys) & set(STANDARD_INDEX_CODES)
    assert len(storage.put) == len(THERMAL_INDEX_CODES)
    # 305 K == 31.85 degC.
    assert float(aggregates["lst"].mean) == pytest.approx(31.85, abs=0.01)


def test_missing_air_temperature_drops_cwsi_but_keeps_the_scene(tmp_path: Path) -> None:
    """One missing weather hour must not cost LST and SMI too."""
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLEAR_LAND))
    bands, aoi_mask, cloud_mask, profile = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )
    storage = _FakeStorage()

    _aggregates, keys, _rasters = compute_and_write_indices(
        bands_arrays=bands,
        aoi_mask=aoi_mask,
        cloud_mask=cloud_mask,
        profile=profile,
        storage=storage,  # type: ignore[arg-type]
        provider_code="landsat_pc",
        product_code="landsat_c2_l2_st",
        scene_id="LC08_TEST",
        aoi_hash="deadbeef",
        air_temp_c=None,
    )

    assert set(keys) == {"lst", "smi"}
    assert "cwsi" not in keys


def test_lst_aggregates_are_a_temperature_not_a_ratio(tmp_path: Path) -> None:
    """Guards the NUMERIC(7,4) column against a unit mistake.

    Degrees Celsius fits (max 999.9999); kelvin would too, but storing
    kelvin here while the catalog advertises 0-60 would render every LST
    chart as a flat line pinned above the axis.
    """
    cog = tmp_path / "raw.tif"
    _write_cog(cog, _thermal_bands(_QA_CLEAR_LAND))
    bands, aoi_mask, cloud_mask, profile = load_raw_bands_and_aggregate(
        str(cog),
        band_names=("lwir11", "red", "nir08"),
        aoi_geojson_utm36n=_AOI,
        product_code="landsat_c2_l2_st",
    )

    aggregates: dict[str, Any] = compute_and_write_indices(
        bands_arrays=bands,
        aoi_mask=aoi_mask,
        cloud_mask=cloud_mask,
        profile=profile,
        storage=_FakeStorage(),  # type: ignore[arg-type]
        provider_code="landsat_pc",
        product_code="landsat_c2_l2_st",
        scene_id="LC08_TEST",
        aoi_hash="deadbeef",
        air_temp_c=31.0,
    )[0]

    mean = float(aggregates["lst"].mean)
    assert 0.0 < mean < 60.0, "LST must be stored in degC, matching the catalog bounds"
