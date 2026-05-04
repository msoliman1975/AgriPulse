"""Sentinel Hub adapter — implements `ImageryProvider`.

OAuth2 client-credentials with cached token, paginated catalog
discovery, and a multi-band Process API call that returns all seven
S2 bands (blue/green/red/red_edge_1/nir/swir1/swir2) in one COG-shaped
GeoTIFF in EPSG:32636.

Token cache is in-process per worker (Q4 in the PR-B plan): each pod
holds one access token, refreshed at 50 minutes (Sentinel Hub's tokens
last 60). Redis-backed sharing is a P2 upgrade.

Why a single multi-band fetch (Q1): seven bands * N scenes * tenants
multiplies upstream cost; one evalscript call returning a 7-band
TIFF keeps quota use linear in scene count.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.imagery.errors import SentinelHubNotConfiguredError
from app.modules.imagery.providers.protocol import DiscoveredScene, FetchResult

# How early before token expiry we refresh. Sentinel Hub tokens live
# 60 min; a 10-min cushion absorbs clock skew + network latency.
_TOKEN_REFRESH_LEAD_SECONDS = 600

# Max retries for transient 5xx errors. Tenacity-style without the dep.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0

# The seven bands the Sentinel-2 L2A product exposes through Sentinel Hub.
# Order matches `public.imagery_products.bands` for s2_l2a so the
# downstream rasterio code can read each band by index without a lookup.
_S2L2A_BAND_ORDER: tuple[str, ...] = (
    "blue",
    "green",
    "red",
    "red_edge_1",
    "nir",
    "swir1",
    "swir2",
)

# Sentinel Hub's name for each band, in the same order.
_SH_BAND_NAMES: dict[str, str] = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "red_edge_1": "B05",
    "nir": "B08",
    "swir1": "B11",
    "swir2": "B12",
}


@dataclass(slots=True)
class _CachedToken:
    access_token: str
    expires_at_epoch: float


class SentinelHubProvider:
    """`ImageryProvider` impl wired to Sentinel Hub's commercial endpoints.

    Constructed once per process (e.g., during FastAPI startup or
    Celery worker init); reuses one `httpx.AsyncClient`. Configuration
    flows from Settings; an empty client_id/secret pair raises
    SentinelHubNotConfiguredError, which the orchestrator catches and
    records as a failed job.
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        oauth_url: str | None = None,
        catalog_url: str | None = None,
        process_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._client_id = client_id if client_id is not None else settings.sentinel_hub_client_id
        self._client_secret = (
            client_secret if client_secret is not None else settings.sentinel_hub_client_secret
        )
        if not self._client_id or not self._client_secret:
            raise SentinelHubNotConfiguredError()

        self._oauth_url = oauth_url or settings.sentinel_hub_oauth_url
        self._catalog_url = catalog_url or settings.sentinel_hub_catalog_url
        self._process_url = process_url or settings.sentinel_hub_process_url

        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_http = http_client is None
        self._token: _CachedToken | None = None
        self._log = get_logger(__name__)

    @property
    def code(self) -> str:
        return "sentinel_hub"

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_http:
            await self._http.aclose()

    # -- OAuth ----------------------------------------------------------

    async def _bearer_token(self) -> str:
        """Return a non-expired access token, refreshing if needed."""
        now = time.time()
        if self._token is None or self._token.expires_at_epoch - now < _TOKEN_REFRESH_LEAD_SECONDS:
            await self._refresh_token()
        assert self._token is not None  # type narrowing
        return self._token.access_token

    async def _refresh_token(self) -> None:
        response = await self._http.post(
            self._oauth_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        body = response.json()
        access_token = str(body["access_token"])
        # SH returns expires_in seconds; default to 3600 if absent.
        expires_in = int(body.get("expires_in", 3600))
        self._token = _CachedToken(
            access_token=access_token,
            expires_at_epoch=time.time() + expires_in,
        )
        self._log.info("sentinel_hub_token_refreshed", expires_in=expires_in)

    # -- Discover -------------------------------------------------------

    async def discover(
        self,
        *,
        aoi_geojson: dict[str, Any],
        product_code: str,
        from_datetime: datetime,
        to_datetime: datetime,
        max_cloud_cover_pct: int | None = None,
    ) -> tuple[DiscoveredScene, ...]:
        """List scenes intersecting the AOI within the time window.

        Sentinel Hub's STAC catalog API paginates via a `next` token in
        the response context. We follow it until exhausted (or until
        we hit a 1000-scene safety cap; agriculture AOIs over 90 days
        rarely exceed ~30 scenes for S2).
        """
        if product_code != "s2_l2a":
            raise ValueError(f"Sentinel Hub adapter does not support product {product_code!r}")

        token = await self._bearer_token()
        results: list[DiscoveredScene] = []
        next_cursor: str | None = None
        page_count = 0
        while True:
            page_count += 1
            if page_count > 20:  # safety cap; ~1000 scenes
                self._log.warning("sentinel_hub_discover_pagination_cap_hit")
                break

            payload: dict[str, Any] = {
                "collections": ["sentinel-2-l2a"],
                "datetime": (
                    f"{from_datetime.astimezone(UTC).isoformat()}/"
                    f"{to_datetime.astimezone(UTC).isoformat()}"
                ),
                "intersects": aoi_geojson,
                "limit": 100,
            }
            if max_cloud_cover_pct is not None:
                # Sentinel Hub uses a `query` extension; cloud cover lives
                # under `eo:cloud_cover`. The catalog returns scenes with
                # cloud_cover ≤ the bound.
                payload["query"] = {"eo:cloud_cover": {"lte": max_cloud_cover_pct}}
            if next_cursor is not None:
                payload["next"] = next_cursor

            response = await self._post_with_retry(
                self._catalog_url,
                json_body=payload,
                token=token,
            )
            body = response.json()
            features = body.get("features", []) or []
            for feature in features:
                results.append(_feature_to_discovered(feature))

            context = body.get("context", {}) or {}
            next_cursor = context.get("next")
            if not next_cursor:
                break

        # SH catalog typically returns most-recent first; the protocol
        # promises ascending. Sort here so consumers don't have to.
        results.sort(key=lambda s: s.scene_datetime)
        return tuple(results)

    # -- Fetch ----------------------------------------------------------

    async def fetch(
        self,
        *,
        scene_id: str,
        product_code: str,
        aoi_geojson_utm36n: dict[str, Any],
        bands: tuple[str, ...],
    ) -> FetchResult:
        """Pull all requested bands for one scene as a multi-band TIFF.

        ``aoi_geojson_utm36n`` carries the block geometry already
        transformed into EPSG:32636 by the caller — Sentinel Hub
        accepts the AOI in any CRS as long as the request says so.
        """
        if product_code != "s2_l2a":
            raise ValueError(f"Sentinel Hub adapter does not support product {product_code!r}")
        unknown = [b for b in bands if b not in _SH_BAND_NAMES]
        if unknown:
            raise ValueError(f"Unsupported S2 L2A bands: {unknown!r}")

        token = await self._bearer_token()

        # Single-call multi-band evalscript. The output is a GeoTIFF
        # with one band per requested logical band, in the order the
        # caller supplied. Cloud Optimized GeoTIFF output is requested
        # via `responses[].format.type=image/tiff`; the COG profile is
        # applied server-side when enabled in our configuration.
        sh_band_list = [_SH_BAND_NAMES[b] for b in bands]
        evalscript = _build_multiband_evalscript(sh_band_list)

        payload = {
            "input": {
                "bounds": {
                    "geometry": aoi_geojson_utm36n,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32636"},
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {
                                # Sentinel Hub matches a scene within
                                # this range; using the exact scene id
                                # in `previewMode` would also work but
                                # the catalog already gave us the date.
                                "from": scene_id,
                                "to": scene_id,
                            },
                            "mosaickingOrder": "leastCC",
                        },
                    }
                ],
            },
            "output": {
                "responses": [
                    {
                        "identifier": "default",
                        "format": {"type": "image/tiff"},
                    }
                ],
            },
            "evalscript": evalscript,
        }

        response = await self._post_with_retry(
            self._process_url,
            json_body=payload,
            token=token,
            accept="image/tiff",
        )
        return FetchResult(
            cog_bytes=response.content,
            band_order=bands,
            content_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

    # -- internals ------------------------------------------------------

    async def _post_with_retry(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        token: str,
        accept: str = "application/json",
    ) -> httpx.Response:
        """POST with bounded retries on 5xx + network errors.

        4xx errors raise immediately — they signal a bad request, not
        transient infrastructure. The orchestrator records the failure
        and moves on.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._http.post(url, json=json_body, headers=headers)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES - 1:
                    raise
                self._log.warning(
                    "sentinel_hub_transport_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                continue
            if response.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"upstream {response.status_code}",
                    request=response.request,
                    response=response,
                )
                if attempt == _MAX_RETRIES - 1:
                    response.raise_for_status()
                self._log.warning(
                    "sentinel_hub_5xx_retry",
                    attempt=attempt + 1,
                    status=response.status_code,
                )
                continue
            response.raise_for_status()
            return response
        # Should be unreachable, but keep mypy happy.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("sentinel_hub retry loop exited without a result")


def _feature_to_discovered(feature: dict[str, Any]) -> DiscoveredScene:
    """Map a Sentinel Hub catalog feature to our DiscoveredScene."""
    properties = feature.get("properties", {}) or {}
    cloud = properties.get("eo:cloud_cover")
    cloud_decimal: Decimal | None = None
    if cloud is not None:
        cloud_decimal = Decimal(str(cloud)).quantize(Decimal("0.01"))

    raw_dt = properties.get("datetime") or properties.get("start_datetime")
    if raw_dt is None:
        raise ValueError(f"Sentinel Hub feature {feature.get('id')!r} missing datetime")
    scene_datetime = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))

    return DiscoveredScene(
        scene_id=str(feature["id"]),
        scene_datetime=scene_datetime,
        cloud_cover_pct=cloud_decimal,
        geometry_geojson=feature.get("geometry") or {},
    )


def _build_multiband_evalscript(sh_band_names: list[str]) -> str:
    """Build a Sentinel Hub evalscript that returns the requested bands.

    Output sample type is `FLOAT32` so downstream index math (PR-C)
    can compute `(NIR - Red) / (NIR + Red)` without precision loss.
    Pixel values are surface reflectance (already in 0..1 from L2A).
    """
    bands_array = ", ".join(f'"{b}"' for b in sh_band_names)
    output_array = ", ".join(f"sample.{b}" for b in sh_band_names)
    return f"""//VERSION=3
function setup() {{
  return {{
    input: [{{ bands: [{bands_array}] }}],
    output: {{
      bands: {len(sh_band_names)},
      sampleType: "FLOAT32"
    }}
  }};
}}
function evaluatePixel(sample) {{
  return [{output_array}];
}}
"""
