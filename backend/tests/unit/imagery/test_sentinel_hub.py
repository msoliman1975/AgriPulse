"""Unit tests for SentinelHubProvider — respx-mocked HTTP layer.

We exercise:

  * OAuth2 client-credentials flow (initial token + cache reuse)
  * Catalog `/search` pagination
  * Process `/process` returning multi-band TIFF bytes
  * Empty creds → SentinelHubNotConfiguredError
  * 5xx retry then success
  * 4xx propagates immediately
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.settings import get_settings
from app.modules.imagery.errors import SentinelHubNotConfiguredError
from app.modules.imagery.providers.sentinel_hub import SentinelHubProvider

# Use the real Settings defaults (the URLs are public). Token / search /
# process URLs match what `SentinelHubProvider` reads from get_settings().
_OAUTH_URL = "https://services.sentinel-hub.com/oauth/token"
_CATALOG_URL = "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search"
_PROCESS_URL = "https://services.sentinel-hub.com/api/v1/process"


@pytest.fixture
def configured_provider(monkeypatch: pytest.MonkeyPatch) -> SentinelHubProvider:
    """A provider with explicit creds that bypass settings."""
    return SentinelHubProvider(
        client_id="test-client",
        client_secret="test-secret",
    )


def test_init_raises_when_creds_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_HUB_CLIENT_ID", "")
    monkeypatch.setenv("SENTINEL_HUB_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(SentinelHubNotConfiguredError):
            SentinelHubProvider()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_oauth_token_is_cached_across_calls(
    configured_provider: SentinelHubProvider,
) -> None:
    """First call fetches the token; subsequent calls reuse it."""
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        token_route = router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        router.post("/api/v1/catalog/1.0.0/search").mock(
            return_value=httpx.Response(200, json={"features": [], "context": {"next": None}})
        )
        await configured_provider.discover(
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            product_code="s2_l2a",
            from_datetime=datetime(2026, 1, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 1, 31, tzinfo=UTC),
        )
        # Second discover call — token must be reused.
        await configured_provider.discover(
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            product_code="s2_l2a",
            from_datetime=datetime(2026, 1, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 1, 31, tzinfo=UTC),
        )
    assert token_route.call_count == 1
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_discover_returns_sorted_scenes(
    configured_provider: SentinelHubProvider,
) -> None:
    feature_a = {
        "id": "S2A_OLDER",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": {
            "datetime": "2026-01-10T08:30:00Z",
            "eo:cloud_cover": 18.5,
        },
    }
    feature_b = {
        "id": "S2A_NEWER",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": {
            "datetime": "2026-01-25T08:30:00Z",
            "eo:cloud_cover": 5.0,
        },
    }
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        # Catalog returns most-recent first; provider must re-sort ascending.
        router.post("/api/v1/catalog/1.0.0/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "features": [feature_b, feature_a],
                    "context": {"next": None},
                },
            )
        )
        scenes = await configured_provider.discover(
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            product_code="s2_l2a",
            from_datetime=datetime(2026, 1, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 1, 31, tzinfo=UTC),
        )
    assert [s.scene_id for s in scenes] == ["S2A_OLDER", "S2A_NEWER"]
    assert scenes[0].cloud_cover_pct == Decimal("18.50")
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_discover_paginates_until_next_is_null(
    configured_provider: SentinelHubProvider,
) -> None:
    page_one = {
        "features": [
            {
                "id": "S2A_001",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"datetime": "2026-01-05T08:30:00Z", "eo:cloud_cover": 1},
            }
        ],
        "context": {"next": "page-2"},
    }
    page_two = {
        "features": [
            {
                "id": "S2A_002",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"datetime": "2026-01-12T08:30:00Z", "eo:cloud_cover": 2},
            }
        ],
        "context": {"next": None},
    }
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        # Two calls in sequence, each returning a different page.
        router.post("/api/v1/catalog/1.0.0/search").mock(
            side_effect=[
                httpx.Response(200, json=page_one),
                httpx.Response(200, json=page_two),
            ]
        )
        scenes = await configured_provider.discover(
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            product_code="s2_l2a",
            from_datetime=datetime(2026, 1, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 1, 31, tzinfo=UTC),
        )
    assert {s.scene_id for s in scenes} == {"S2A_001", "S2A_002"}
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_fetch_returns_multiband_cog_bytes(
    configured_provider: SentinelHubProvider,
) -> None:
    fake_tiff = b"II*\x00fake-cog-bytes"
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        router.post("/api/v1/process").mock(
            return_value=httpx.Response(
                200,
                content=fake_tiff,
                headers={"content-type": "image/tiff"},
            )
        )
        result = await configured_provider.fetch(
            scene_id="2026-01-15T08:30:00Z",
            scene_datetime=datetime(2026, 1, 15, 8, 30, 0, tzinfo=UTC),
            product_code="s2_l2a",
            aoi_geojson_utm36n={
                "type": "Polygon",
                "coordinates": [
                    [[200000, 3300000], [201000, 3300000], [201000, 3301000], [200000, 3300000]]
                ],
            },
            bands=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        )
    assert result.cog_bytes == fake_tiff
    assert result.band_order == (
        "blue",
        "green",
        "red",
        "red_edge_1",
        "nir",
        "swir1",
        "swir2",
    )
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_fetch_5xx_retries_then_succeeds(
    configured_provider: SentinelHubProvider,
) -> None:
    fake_tiff = b"II*\x00fake"
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        # 503 then 200 — provider should swallow the first and succeed.
        router.post("/api/v1/process").mock(
            side_effect=[
                httpx.Response(503, json={"error": "transient"}),
                httpx.Response(200, content=fake_tiff),
            ]
        )
        result = await configured_provider.fetch(
            scene_id="abc",
            scene_datetime=datetime(2026, 1, 15, 8, 30, 0, tzinfo=UTC),
            product_code="s2_l2a",
            aoi_geojson_utm36n={"type": "Polygon", "coordinates": [[[0, 0]]]},
            bands=("red", "nir"),
        )
    assert result.cog_bytes == fake_tiff
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_fetch_4xx_does_not_retry(
    configured_provider: SentinelHubProvider,
) -> None:
    async with respx.mock(base_url="https://services.sentinel-hub.com") as router:
        router.post("/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        )
        process_route = router.post("/api/v1/process").mock(
            return_value=httpx.Response(400, json={"error": "bad request"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await configured_provider.fetch(
                scene_id="abc",
                scene_datetime=datetime(2026, 1, 15, 8, 30, 0, tzinfo=UTC),
                product_code="s2_l2a",
                aoi_geojson_utm36n={"type": "Polygon", "coordinates": [[[0, 0]]]},
                bands=("red",),
            )
    assert process_route.call_count == 1
    await configured_provider.aclose()


@pytest.mark.asyncio
async def test_unsupported_product_raises(
    configured_provider: SentinelHubProvider,
) -> None:
    with pytest.raises(ValueError, match="planetscope_4band"):
        await configured_provider.discover(
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0]]]},
            product_code="planetscope_4band",
            from_datetime=datetime(2026, 1, 1, tzinfo=UTC),
            to_datetime=datetime(2026, 1, 2, tzinfo=UTC),
        )


# Reference URLs for code grep — quiet ruff "unused" warning.
_ = (_OAUTH_URL, _CATALOG_URL, _PROCESS_URL)
