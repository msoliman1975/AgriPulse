"""Unit tests for LandsatPlanetaryComputerProvider.

HTTP is respx-mocked; the raster path runs against real GeoTIFFs written
to a tmp dir (the `_gdal_path` seam swaps `/vsicurl/` for a local path),
so the window arithmetic and Collection-2 scaling are exercised for real
rather than asserted against a stub.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
import respx
from rasterio.transform import from_origin

from app.modules.imagery.providers import landsat_pc
from app.modules.imagery.providers.landsat_pc import (
    LandsatPlanetaryComputerProvider,
    _parse_sas_response,
    _read_window_to_cog,
    _scale_band,
    _sign_href,
)

_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
_SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
_BLOB = "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2"

# A farm-sized AOI on the 30 m grid, in EPSG:32636. Origin chosen so the
# window lands well inside the synthetic scene below.
_AOI_UTM = {
    "type": "Polygon",
    "coordinates": [
        [
            [300150.0, 3330150.0],
            [300450.0, 3330150.0],
            [300450.0, 3329850.0],
            [300150.0, 3329850.0],
            [300150.0, 3330150.0],
        ]
    ],
}


@pytest.fixture
def provider() -> LandsatPlanetaryComputerProvider:
    """Cloud masking off, so `bands` in == `band_order` out.

    Keeps the fetch assertions about the science bands themselves; the
    trailing quality band gets its own test below.
    """
    return LandsatPlanetaryComputerProvider(stac_url=_STAC, sas_url=_SAS, cloud_mask=False)


# A stand-in SAS query string. Not a credential — PC issues these to
# anyone anonymously, and this one is fabricated.
_FAKE_SAS = "sv=2021&sig=abc"


def _sas_body(token: str = _FAKE_SAS, expiry: str = "2099-01-01T00:00:00Z") -> dict:
    return {"token": token, "msft:expiry": expiry}


def _feature(scene_id: str, dt: str, cloud: float, platform: str = "landsat-8") -> dict:
    return {
        "id": scene_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[32.6, 30.0], [32.7, 30.0], [32.7, 30.1], [32.6, 30.1], [32.6, 30.0]]],
        },
        "properties": {"datetime": dt, "eo:cloud_cover": cloud, "platform": platform},
    }


# -- SAS token ----------------------------------------------------------


@pytest.mark.asyncio
async def test_sas_token_is_cached_across_calls(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    async with respx.mock as router:
        route = router.get(f"{_SAS}/landsat-c2-l2").mock(
            return_value=httpx.Response(200, json=_sas_body())
        )
        first = await provider._sas_token()
        second = await provider._sas_token()

    assert first == second == _FAKE_SAS
    assert route.call_count == 1, "second call should reuse the cached token"


def test_parse_sas_response_reads_the_expiry() -> None:
    cached = _parse_sas_response(_sas_body(expiry="2030-06-01T12:00:00Z"))
    assert cached.token == _FAKE_SAS
    assert cached.expires_at_epoch == datetime(2030, 6, 1, 12, tzinfo=UTC).timestamp()


def test_parse_sas_response_falls_back_on_a_bad_expiry() -> None:
    before = _parse_sas_response({"token": "t", "msft:expiry": "not-a-date"})
    # Falls back to the documented 1h TTL rather than raising: the token
    # is what matters, a short TTL only costs an extra refresh.
    assert before.token == "t"
    assert before.expires_at_epoch > 0


def test_sign_href_appends_the_token() -> None:
    assert _sign_href("https://x/y.TIF", "sv=1&sig=z") == "https://x/y.TIF?sv=1&sig=z"
    assert _sign_href("https://x/y.TIF?a=1", "sv=1") == "https://x/y.TIF?a=1&sv=1"


# -- Probe --------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_ok(provider: LandsatPlanetaryComputerProvider) -> None:
    async with respx.mock as router:
        router.get(f"{_SAS}/landsat-c2-l2").mock(return_value=httpx.Response(200, json=_sas_body()))
        result = await provider.probe()

    assert result.status == "ok"
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_probe_reports_http_error(provider: LandsatPlanetaryComputerProvider) -> None:
    async with respx.mock as router:
        router.get(f"{_SAS}/landsat-c2-l2").mock(return_value=httpx.Response(503))
        result = await provider.probe()

    assert result.status == "error"
    assert result.error_message == "HTTP 503"


# -- Discover -----------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_filters_to_tirs_platforms_and_sorts_ascending(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    async with respx.mock as router:
        route = router.post(f"{_STAC}/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "features": [
                        _feature("LC09_B", "2026-03-02T08:20:00Z", 12.5, "landsat-9"),
                        _feature("LC08_A", "2026-03-01T08:16:00Z", 4.0, "landsat-8"),
                    ],
                    "links": [],
                },
            )
        )
        scenes = await provider.discover(
            aoi_geojson={"type": "Point", "coordinates": [32.63, 30.07]},
            product_code="landsat_c2_l2_st",
            from_datetime=datetime(2026, 3, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 3, 31, tzinfo=UTC),
            max_cloud_cover_pct=20,
        )

    body = json.loads(route.calls[0].request.content)
    assert body["collections"] == ["landsat-c2-l2"]
    # L4/5/7 carry `lwir`, not `lwir11` — they must never reach fetch().
    assert body["query"]["platform"] == {"in": ["landsat-8", "landsat-9"]}
    assert body["query"]["eo:cloud_cover"] == {"lte": 20}

    assert [s.scene_id for s in scenes] == ["LC08_A", "LC09_B"]
    assert scenes[0].cloud_cover_pct is not None
    assert float(scenes[0].cloud_cover_pct) == 4.0


@pytest.mark.asyncio
async def test_discover_omits_the_cloud_filter_when_uncapped(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    async with respx.mock as router:
        route = router.post(f"{_STAC}/search").mock(
            return_value=httpx.Response(200, json={"features": [], "links": []})
        )
        await provider.discover(
            aoi_geojson={"type": "Point", "coordinates": [32.63, 30.07]},
            product_code="landsat_c2_l2_st",
            from_datetime=datetime(2026, 3, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 3, 31, tzinfo=UTC),
        )

    body = json.loads(route.calls[0].request.content)
    assert "eo:cloud_cover" not in body["query"]


@pytest.mark.asyncio
async def test_discover_follows_the_next_link(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    pages = [
        httpx.Response(
            200,
            json={
                "features": [_feature("A", "2026-03-01T08:16:00Z", 1.0)],
                "links": [{"rel": "next", "body": {"token": "next:1"}, "merge": True}],
            },
        ),
        httpx.Response(
            200,
            json={
                "features": [_feature("B", "2026-03-09T08:16:00Z", 2.0)],
                "links": [],
            },
        ),
    ]
    async with respx.mock as router:
        route = router.post(f"{_STAC}/search").mock(side_effect=pages)
        scenes = await provider.discover(
            aoi_geojson={"type": "Point", "coordinates": [32.63, 30.07]},
            product_code="landsat_c2_l2_st",
            from_datetime=datetime(2026, 3, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 3, 31, tzinfo=UTC),
        )

    assert route.call_count == 2
    assert json.loads(route.calls[1].request.content)["token"] == "next:1"
    assert [s.scene_id for s in scenes] == ["A", "B"]


@pytest.mark.asyncio
async def test_discover_rejects_a_foreign_product(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    with pytest.raises(ValueError, match="s2_l2a"):
        await provider.discover(
            aoi_geojson={"type": "Point", "coordinates": [0, 0]},
            product_code="s2_l2a",
            from_datetime=datetime(2026, 3, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 3, 31, tzinfo=UTC),
        )


# -- Scaling ------------------------------------------------------------


def test_lwir11_scales_to_kelvin_and_masks_fill() -> None:
    # 44000 DN -> 44000 * 0.00341802 + 149.0 = 299.39 K
    raw = np.array([[44000, 0]], dtype=np.uint16)
    out = _scale_band("lwir11", raw)

    assert out.dtype == np.float32
    assert out[0, 0] == pytest.approx(299.393, abs=0.01)
    assert np.isnan(out[0, 1]), "fill DN 0 must not read as a plausible 149 K"


def test_reflectance_bands_scale_to_zero_one() -> None:
    # 20000 DN -> 20000 * 0.0000275 - 0.2 = 0.35
    out = _scale_band("red", np.array([[20000]], dtype=np.uint16))
    assert out[0, 0] == pytest.approx(0.35, abs=1e-5)


def test_qa_pixel_passes_through_unscaled() -> None:
    # Bit-packed categorical codes, including a meaningful 0.
    raw = np.array([[21824, 0, 55052]], dtype=np.uint16)
    out = _scale_band("qa_pixel", raw)

    assert out.tolist() == [[21824.0, 0.0, 55052.0]]
    assert not np.isnan(out).any()


def test_qa_pixel_survives_the_float32_round_trip() -> None:
    """uint16 is 16 bits; float32's mantissa is 24 — exact, no rounding."""
    codes = np.arange(0, 65536, dtype=np.uint16).reshape(256, 256)
    out = _scale_band("qa_pixel", codes)
    assert np.array_equal(out.astype(np.uint16), codes)


# -- Raster read --------------------------------------------------------


def _write_scene(path: Path, value: int) -> None:
    """A small synthetic Landsat-like band on the 30 m UTM 36N grid."""
    profile = {
        "driver": "GTiff",
        "height": 100,
        "width": 100,
        "count": 1,
        "dtype": "uint16",
        "crs": "EPSG:32636",
        "transform": from_origin(299000.0, 3331000.0, 30.0, 30.0),
        "nodata": 0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((100, 100), value, dtype=np.uint16), 1)


def test_read_window_to_cog_stacks_bands_on_one_aligned_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    thermal = tmp_path / "ST_B10.TIF"
    red = tmp_path / "SR_B4.TIF"
    qa = tmp_path / "QA_PIXEL.TIF"
    _write_scene(thermal, 44000)
    _write_scene(red, 20000)
    _write_scene(qa, 21824)

    monkeypatch.setattr(landsat_pc, "_gdal_path", lambda href: href)

    cog = _read_window_to_cog(
        signed_hrefs=[str(thermal), str(red), str(qa)],
        bands=("lwir11", "red", "qa_pixel"),
        aoi_geojson_utm36n=_AOI_UTM,
    )

    with rasterio.MemoryFile(cog) as memfile, memfile.open() as ds:
        assert ds.count == 3
        assert ds.crs.to_epsg() == 32636
        assert ds.dtypes[0] == "float32"
        # A 300 m AOI covers 10 cells but straddles 11: it starts a third
        # of the way into one. Both edges round outward so the window
        # fully contains the AOI rather than clipping its margins.
        assert (ds.height, ds.width) == (11, 11)
        assert ds.read(1).mean() == pytest.approx(299.393, abs=0.01)
        assert ds.read(2).mean() == pytest.approx(0.35, abs=1e-5)
        assert ds.read(3).mean() == pytest.approx(21824.0)
        # Every band read the same window, so the stack is aligned —
        # that is what makes the LST/NDVI triangle behind SMI valid.
        # The origin snaps outward onto the source 30 m grid rather than
        # landing on the AOI edge: 299000 + floor((300150-299000)/30)*30.
        assert ds.transform.c == 300140.0
        assert ds.transform.a == 30.0


def test_read_window_rounds_outward_so_a_subpixel_aoi_still_yields_a_pixel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    band = tmp_path / "ST_B10.TIF"
    _write_scene(band, 44000)
    monkeypatch.setattr(landsat_pc, "_gdal_path", lambda href: href)

    # ~8 m across — far smaller than one 30 m pixel, like our 0.53 ha block.
    tiny = {
        "type": "Polygon",
        "coordinates": [
            [
                [300154.0, 3330154.0],
                [300162.0, 3330154.0],
                [300162.0, 3330146.0],
                [300154.0, 3330146.0],
                [300154.0, 3330154.0],
            ]
        ],
    }
    cog = _read_window_to_cog(signed_hrefs=[str(band)], bands=("lwir11",), aoi_geojson_utm36n=tiny)

    with rasterio.MemoryFile(cog) as memfile, memfile.open() as ds:
        assert ds.height >= 1
        assert ds.width >= 1


def test_read_window_rejects_an_aoi_outside_the_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    band = tmp_path / "ST_B10.TIF"
    _write_scene(band, 44000)
    monkeypatch.setattr(landsat_pc, "_gdal_path", lambda href: href)

    far_away = {
        "type": "Polygon",
        "coordinates": [
            [
                [500000.0, 3900000.0],
                [500300.0, 3900000.0],
                [500300.0, 3899700.0],
                [500000.0, 3899700.0],
                [500000.0, 3900000.0],
            ]
        ],
    }
    with pytest.raises(ValueError, match="does not intersect"):
        _read_window_to_cog(
            signed_hrefs=[str(band)], bands=("lwir11",), aoi_geojson_utm36n=far_away
        )


# -- Fetch --------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_resolves_assets_signs_them_and_returns_band_order(
    provider: LandsatPlanetaryComputerProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thermal = tmp_path / "ST_B10.TIF"
    nir = tmp_path / "SR_B5.TIF"
    _write_scene(thermal, 44000)
    _write_scene(nir, 30000)

    captured: list[str] = []

    def _local(href: str) -> str:
        captured.append(href)
        return href.split("?")[0]

    monkeypatch.setattr(landsat_pc, "_gdal_path", _local)

    scene_id = "LC08_L2SP_175039_20260301_02_T1"
    async with respx.mock as router:
        router.get(f"{_SAS}/landsat-c2-l2").mock(
            return_value=httpx.Response(200, json=_sas_body(token="sv=2021&sig=xyz"))
        )
        router.get(f"{_STAC}/collections/landsat-c2-l2/items/{scene_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": scene_id,
                    "assets": {
                        "lwir11": {"href": f"{_BLOB}/{scene_id}_ST_B10.TIF"},
                        "nir08": {"href": f"{_BLOB}/{scene_id}_SR_B5.TIF"},
                    },
                },
            )
        )
        # Point the hrefs at the local files via the seam.
        monkeypatch.setattr(
            landsat_pc,
            "_sign_href",
            lambda href, token: (
                f"{thermal}?{token}" if href.endswith("ST_B10.TIF") else f"{nir}?{token}"
            ),
        )
        result = await provider.fetch(
            scene_id=scene_id,
            scene_datetime=datetime(2026, 3, 1, 8, 16, tzinfo=UTC),
            product_code="landsat_c2_l2_st",
            aoi_geojson_utm36n=_AOI_UTM,
            bands=("lwir11", "nir08"),
        )

    assert result.band_order == ("lwir11", "nir08")
    assert all("sig=xyz" in href for href in captured), "assets must carry the SAS token"

    with rasterio.MemoryFile(result.cog_bytes) as memfile, memfile.open() as ds:
        assert ds.count == 2
        assert ds.read(1).mean() == pytest.approx(299.393, abs=0.01)


@pytest.mark.asyncio
async def test_fetch_rejects_unknown_bands(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    with pytest.raises(ValueError, match="swir1"):
        await provider.fetch(
            scene_id="X",
            scene_datetime=datetime(2026, 3, 1, tzinfo=UTC),
            product_code="landsat_c2_l2_st",
            aoi_geojson_utm36n=_AOI_UTM,
            bands=("swir1",),
        )


@pytest.mark.asyncio
async def test_fetch_raises_when_the_scene_lacks_the_thermal_asset(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    """Belt and braces behind the platform filter in discover()."""
    async with respx.mock as router:
        router.get(f"{_SAS}/landsat-c2-l2").mock(return_value=httpx.Response(200, json=_sas_body()))
        router.get(f"{_STAC}/collections/landsat-c2-l2/items/LE07_X").mock(
            return_value=httpx.Response(200, json={"id": "LE07_X", "assets": {"lwir": {}}})
        )
        with pytest.raises(ValueError, match="lwir11"):
            await provider.fetch(
                scene_id="LE07_X",
                scene_datetime=datetime(2026, 3, 1, tzinfo=UTC),
                product_code="landsat_c2_l2_st",
                aoi_geojson_utm36n=_AOI_UTM,
                bands=("lwir11",),
            )


@pytest.mark.asyncio
async def test_cloud_masking_appends_qa_pixel_as_a_trailing_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`qa_pixel` is a quality band, not a science band.

    It stays out of `imagery_products.bands` — exactly like SCL for
    Sentinel-2 — and rides as one trailing band, which is what
    `_rasterio_io.load_raw_bands_and_aggregate` already accepts.
    """
    thermal = tmp_path / "ST_B10.TIF"
    qa = tmp_path / "QA_PIXEL.TIF"
    _write_scene(thermal, 44000)
    _write_scene(qa, 21824)

    monkeypatch.setattr(landsat_pc, "_gdal_path", lambda href: href.split("?")[0])
    monkeypatch.setattr(
        landsat_pc,
        "_sign_href",
        lambda href, token: (f"{thermal}?{token}" if "ST_B10" in href else f"{qa}?{token}"),
    )

    masking_provider = LandsatPlanetaryComputerProvider(
        stac_url=_STAC, sas_url=_SAS, cloud_mask=True
    )
    scene_id = "LC09_L2SP_175039_20260731_02_T1"
    async with respx.mock as router:
        router.get(f"{_SAS}/landsat-c2-l2").mock(return_value=httpx.Response(200, json=_sas_body()))
        router.get(f"{_STAC}/collections/landsat-c2-l2/items/{scene_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": scene_id,
                    "assets": {
                        "lwir11": {"href": f"{_BLOB}/{scene_id}_ST_B10.TIF"},
                        "qa_pixel": {"href": f"{_BLOB}/{scene_id}_QA_PIXEL.TIF"},
                    },
                },
            )
        )
        # The catalog's `bands` carries science bands only.
        result = await masking_provider.fetch(
            scene_id=scene_id,
            scene_datetime=datetime(2026, 7, 31, 8, 17, tzinfo=UTC),
            product_code="landsat_c2_l2_st",
            aoi_geojson_utm36n=_AOI_UTM,
            bands=("lwir11",),
        )

    assert result.band_order == ("lwir11", "qa_pixel")
    with rasterio.MemoryFile(result.cog_bytes) as memfile, memfile.open() as ds:
        assert ds.count == 2
        # The quality band survives unscaled so the codes stay readable.
        assert ds.read(2).mean() == pytest.approx(21824.0)


def test_code_matches_the_catalog_provider_code(
    provider: LandsatPlanetaryComputerProvider,
) -> None:
    assert provider.code == "landsat_pc"
