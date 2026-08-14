"""Landsat Collection-2 Level-2 adapter — implements `ImageryProvider`.

Serves the thermal product (`landsat_c2_l2_st`) that LST / CWSI / SMI
depend on. Source is Microsoft Planetary Computer, which fronts the
USGS Collection-2 Level-2 archive as COGs in Azure blob storage.

Why Planetary Computer and not the obvious alternatives:

  * **CDSE `landsat-ot-l1`** is Level-1 TOA radiance. Turning that into
    surface temperature means writing the atmospheric-correction and
    emissivity-retrieval chain ourselves. Level-2 already has it.
  * **Sentinel-3 SLSTR** works with our CDSE credentials and is nearly
    free, but one pixel is 1 km and our largest farm is 786 m x 1085 m
    — a single pixel blends the whole farm with the surrounding desert.
  * **USGS LandsatLook** publishes a public STAC catalog whose asset
    hrefs are *gated*: a ranged GET 302s to `ers.cr.usgs.gov` and
    returns an HTML login page under a `200`.

PC needs no account: the STAC search is anonymous, and the SAS endpoint
issues a ~1 hour read token for the blob container to anyone who asks.
The same files are byte-identical in AWS `s3://usgs-landsat/`
(requester-pays), so losing PC is a credentials change here, not a
rewrite.

Two properties make this cheap for us specifically: the assets are
already `EPSG:32636` over Egypt — our storage CRS — so the common path
does no reprojection, and they live in Azure West Europe, a short hop
from the Hetzner node.

Only Landsat 8 and 9 are considered. Landsat 4/5/7 carry a `lwir`
asset, not `lwir11`, and L7's SLC-off striping would need gap-filling;
`discover()` filters them out so `fetch()` never meets an item whose
thermal band is missing.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.io import MemoryFile
from rasterio.profiles import default_gtiff_profile
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from shapely.geometry import shape

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.imagery.providers.protocol import DiscoveredScene, FetchResult, ProbeResult

# The product code this adapter serves, matching
# `public.imagery_products.code`.
_PRODUCT_CODE = "landsat_c2_l2_st"

# Planetary Computer's STAC collection id, and the blob container the
# SAS token is scoped to. Same string for both, which is a PC
# convention, not a coincidence we should rely on — hence two constants.
_COLLECTION_ID = "landsat-c2-l2"
_SAS_CONTAINER = "landsat-c2-l2"

# Only the TIRS-carrying platforms. See module docstring.
_SUPPORTED_PLATFORMS: tuple[str, ...] = ("landsat-8", "landsat-9")

# Our logical band name -> the STAC asset key on the item. Identity
# today, but stated explicitly so a bad `imagery_products.bands` entry
# fails with a clear message instead of a KeyError deep in the asset
# dict.
_BAND_ASSETS: dict[str, str] = {
    "lwir11": "lwir11",
    "red": "red",
    "nir08": "nir08",
    "qa_pixel": "qa_pixel",
}

# The quality band, appended as a trailing band when cloud masking is on
# so the compute step can drop cloud/shadow/cirrus pixels. Exactly the
# role SCL plays for Sentinel-2, and like SCL it is NOT a science band:
# it stays out of `imagery_products.bands`, and `_rasterio_io` already
# accepts one trailing quality band beyond the catalog's band list.
_QA_BAND = "qa_pixel"

# Collection-2 Level-2 scaling: physical = DN * scale + offset.
# ST_B10 -> kelvin; SR_B4/SR_B5 -> surface reflectance 0..1.
# `qa_pixel` is deliberately absent: it is a bit-packed categorical
# code that must survive the round-trip unscaled.
_BAND_SCALING: dict[str, tuple[float, float]] = {
    "lwir11": (0.00341802, 149.0),
    "red": (0.0000275, -0.2),
    "nir08": (0.0000275, -0.2),
}

# Collection-2 Level-2 uses 0 as the fill value across all these bands.
# It has to become NaN *before* scaling, or a fill pixel would read as
# a plausible 149 K.
_FILL_DN = 0

# The SAS token PC hands out lasts ~1 hour. Refresh with the same
# cushion the Sentinel Hub adapter uses for its OAuth token.
_TOKEN_REFRESH_LEAD_SECONDS = 600
_DEFAULT_TOKEN_TTL_SECONDS = 3600

_PROBE_TIMEOUT_SECONDS = 8.0
_MAX_RETRIES = 3

# Safety cap on STAC pagination. A year over one farm returns ~86
# scenes, so 20 pages of 100 is a very loose bound.
_MAX_PAGES = 20


@dataclass(slots=True)
class _CachedSasToken:
    token: str
    expires_at_epoch: float


@contextmanager
def _gdal_vsicurl_env() -> Iterator[None]:
    """GDAL settings for reading a signed HTTPS COG via `/vsicurl/`.

    `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` is the important one: without
    it GDAL lists the containing blob directory on every open, which over
    HTTP costs more than the pixel read itself.

    Deliberately *not* wrapped in `rasterio.Env(session=...)`. The
    AWSSession that `_rasterio_io._gdal_s3_env` installs for our own R2
    bucket would make GDAL try to sign these Azure requests. Env vars are
    saved and restored so this stays hermetic alongside that helper.
    """
    extras = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".TIF,.tif",
        "GDAL_HTTP_MULTIPLEX": "YES",
        "GDAL_HTTP_VERSION": "2",
        # PC occasionally 500s under load; GDAL's own retry is cheaper
        # than failing the whole job and re-reading every band.
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "1",
    }
    saved = {k: os.environ.get(k) for k in extras}
    os.environ.update(extras)
    try:
        with rasterio.Env():
            yield
    finally:
        for key, prior in saved.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


class LandsatPlanetaryComputerProvider:
    """`ImageryProvider` impl reading Landsat C2 L2 from Planetary Computer.

    Stateless apart from the cached SAS token, exactly like
    `SentinelHubProvider`'s OAuth cache: one token per worker process,
    refreshed 10 minutes before expiry.
    """

    def __init__(
        self,
        *,
        stac_url: str | None = None,
        sas_url: str | None = None,
        resolution_m: float | None = None,
        cloud_mask: bool | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._stac_url = (stac_url or settings.planetary_computer_stac_url).rstrip("/")
        self._sas_url = (sas_url or settings.planetary_computer_sas_url).rstrip("/")
        self._resolution_m = (
            float(resolution_m)
            if resolution_m is not None
            else float(settings.landsat_native_resolution_m)
        )
        self._cloud_mask = (
            bool(cloud_mask)
            if cloud_mask is not None
            else bool(settings.imagery_cloud_mask_enabled)
        )
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_http = http_client is None
        self._sas: _CachedSasToken | None = None
        self._log = get_logger(__name__)

    @property
    def code(self) -> str:
        return "landsat_pc"

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_http:
            await self._http.aclose()

    # -- Probe ----------------------------------------------------------

    async def probe(self) -> ProbeResult:
        """Ask for a SAS token — the cheapest call that proves the whole
        path works.

        It exercises DNS, TLS and PC's auth service in one round trip,
        and unlike a STAC search it reads no scene metadata. There are no
        credentials to validate (the endpoint is anonymous), so a 200
        here means "PC will serve us", which is the only question.
        """
        started = time.time()
        try:
            response = await self._http.get(
                f"{self._sas_url}/{_SAS_CONTAINER}",
                timeout=httpx.Timeout(_PROBE_TIMEOUT_SECONDS),
            )
        except httpx.TimeoutException as exc:
            return ProbeResult(
                status="timeout",
                latency_ms=int((time.time() - started) * 1000),
                error_message=str(exc),
            )
        except httpx.TransportError as exc:
            return ProbeResult(
                status="error",
                latency_ms=int((time.time() - started) * 1000),
                error_message=str(exc),
            )
        latency_ms = int((time.time() - started) * 1000)
        if response.status_code >= 400:
            return ProbeResult(
                status="error",
                latency_ms=latency_ms,
                error_message=f"HTTP {response.status_code}",
            )
        # Opportunistically prime the cache, mirroring the SH probe. A
        # changed body shape does not demote the probe — connectivity is
        # the signal we are after.
        with suppress(KeyError, ValueError, TypeError):
            self._sas = _parse_sas_response(response.json())
        return ProbeResult(status="ok", latency_ms=latency_ms)

    # -- SAS token ------------------------------------------------------

    async def _sas_token(self) -> str:
        """Return a non-expired SAS token, refreshing if needed."""
        now = time.time()
        if self._sas is None or self._sas.expires_at_epoch - now < _TOKEN_REFRESH_LEAD_SECONDS:
            await self._refresh_sas_token()
        assert self._sas is not None  # type narrowing
        return self._sas.token

    async def _refresh_sas_token(self) -> None:
        response = await self._request_with_retry("GET", f"{self._sas_url}/{_SAS_CONTAINER}")
        self._sas = _parse_sas_response(response.json())
        self._log.info(
            "planetary_computer_sas_refreshed",
            expires_in=int(self._sas.expires_at_epoch - time.time()),
        )

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
        """List Landsat 8/9 C2 L2 scenes intersecting the AOI.

        `aoi_geojson` is WGS84, per the STAC spec and matching what the
        orchestrator passes the Sentinel Hub adapter.

        A caveat worth carrying downstream: `eo:cloud_cover` describes a
        185 km x 180 km scene, not our 85 ha farm, so filtering on it is
        conservative — it discards scenes that are very likely clear over
        the AOI. Per-pixel truth comes from `qa_pixel` at compute time.
        """
        if product_code != _PRODUCT_CODE:
            raise ValueError(f"Landsat PC adapter does not support product {product_code!r}")

        payload: dict[str, Any] = {
            "collections": [_COLLECTION_ID],
            "intersects": aoi_geojson,
            "datetime": (
                f"{from_datetime.astimezone(UTC).isoformat()}/"
                f"{to_datetime.astimezone(UTC).isoformat()}"
            ),
            "limit": 100,
            "query": {"platform": {"in": list(_SUPPORTED_PLATFORMS)}},
        }
        if max_cloud_cover_pct is not None:
            payload["query"]["eo:cloud_cover"] = {"lte": max_cloud_cover_pct}

        results: list[DiscoveredScene] = []
        body: dict[str, Any] | None = payload
        for _page in range(_MAX_PAGES):
            if body is None:
                break
            response = await self._request_with_retry(
                "POST", f"{self._stac_url}/search", json_body=body
            )
            page_body = response.json()
            for feature in page_body.get("features", []) or []:
                results.append(_feature_to_discovered(feature))
            body = _next_search_body(page_body, body)
            if body is None:
                break
        else:
            self._log.warning("planetary_computer_discover_pagination_cap_hit", pages=_MAX_PAGES)

        results.sort(key=lambda s: s.scene_datetime)
        return tuple(results)

    # -- Fetch ----------------------------------------------------------

    async def fetch(
        self,
        *,
        scene_id: str,
        scene_datetime: datetime,
        product_code: str,
        aoi_geojson_utm36n: dict[str, Any],
        bands: tuple[str, ...],
    ) -> FetchResult:
        """Read the requested bands over the AOI as one multi-band COG.

        Every band rides in the same STAC item on the same 30 m grid, so
        one window serves them all and the stack is guaranteed aligned —
        which is what makes the LST/NDVI triangle behind SMI valid.

        Science bands are written scaled to physical units (kelvin for
        `lwir11`, surface reflectance for `red`/`nir08`) as float32,
        matching the Sentinel Hub adapter's contract.

        When cloud masking is on, `qa_pixel` is appended as a trailing
        band — the role SCL plays for Sentinel-2 — so the compute step
        can drop cloud/shadow pixels. It rides unscaled: it is a
        bit-packed categorical code, and float32 represents uint16
        exactly, so the codes survive intact. `band_order` reports it so
        the reader knows the COG layout.
        """
        if product_code != _PRODUCT_CODE:
            raise ValueError(f"Landsat PC adapter does not support product {product_code!r}")
        unknown = [b for b in bands if b not in _BAND_ASSETS]
        if unknown:
            raise ValueError(f"Unsupported Landsat C2 L2 bands: {unknown!r}")
        if not bands:
            raise ValueError("fetch() requires at least one band")

        out_bands = bands
        if self._cloud_mask and _QA_BAND not in bands:
            out_bands = (*bands, _QA_BAND)

        item = await self._get_item(scene_id)
        assets = item.get("assets", {}) or {}
        hrefs: list[str] = []
        for band in out_bands:
            asset = assets.get(_BAND_ASSETS[band])
            if not asset or not asset.get("href"):
                raise ValueError(f"Scene {scene_id!r} has no {_BAND_ASSETS[band]!r} asset")
            hrefs.append(str(asset["href"]))

        token = await self._sas_token()
        signed = [_sign_href(h, token) for h in hrefs]

        # rasterio is synchronous and this does real network IO, so it
        # runs off the event loop.
        cog_bytes = await asyncio.to_thread(
            _read_window_to_cog,
            signed_hrefs=signed,
            bands=out_bands,
            aoi_geojson_utm36n=aoi_geojson_utm36n,
        )
        return FetchResult(
            cog_bytes=cog_bytes,
            band_order=out_bands,
            content_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

    async def _get_item(self, scene_id: str) -> dict[str, Any]:
        """Read one STAC item so we can resolve its asset hrefs."""
        response = await self._request_with_retry(
            "GET", f"{self._stac_url}/collections/{_COLLECTION_ID}/items/{scene_id}"
        )
        item: dict[str, Any] = response.json()
        return item

    # -- internals ------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Request with bounded retries on 5xx + network errors.

        Same policy as the Sentinel Hub adapter: 4xx raises immediately
        because it signals a bad request rather than transient
        infrastructure.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._http.request(method, url, json=json_body)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES - 1:
                    raise
                self._log.warning(
                    "planetary_computer_transport_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                continue
            if response.status_code >= 500:
                if attempt == _MAX_RETRIES - 1:
                    response.raise_for_status()
                self._log.warning(
                    "planetary_computer_5xx_retry",
                    attempt=attempt + 1,
                    status=response.status_code,
                )
                continue
            response.raise_for_status()
            return response
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("planetary_computer retry loop exited without a result")


# -- module-level helpers -----------------------------------------------


def _parse_sas_response(body: dict[str, Any]) -> _CachedSasToken:
    """Map PC's `{token, msft:expiry}` payload to our cache entry.

    An unparseable expiry falls back to the documented 1 hour rather
    than failing: the token itself is what we need, and a conservative
    TTL only costs an extra refresh.
    """
    token = str(body["token"])
    expires_at = time.time() + _DEFAULT_TOKEN_TTL_SECONDS
    raw_expiry = body.get("msft:expiry")
    if raw_expiry:
        try:
            parsed = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
            expires_at = parsed.timestamp()
        except ValueError:
            pass
    return _CachedSasToken(token=token, expires_at_epoch=expires_at)


def _sign_href(href: str, token: str) -> str:
    """Append the SAS token as the query string GDAL will send."""
    separator = "&" if "?" in href else "?"
    return f"{href}{separator}{token}"


def _next_search_body(
    page_body: dict[str, Any], previous_body: dict[str, Any]
) -> dict[str, Any] | None:
    """Build the next POST body from a STAC `rel=next` link, if any.

    PC paginates POST searches by returning a link whose `body` carries
    a token to merge into the original search. `merge: false` (the
    default) means the link body is complete on its own.
    """
    for link in page_body.get("links", []) or []:
        if link.get("rel") != "next":
            continue
        link_body = link.get("body") or {}
        if link.get("merge"):
            return {**previous_body, **link_body}
        return {**previous_body, **link_body} if link_body else None
    return None


def _feature_to_discovered(feature: dict[str, Any]) -> DiscoveredScene:
    """Map a PC STAC feature to our DiscoveredScene."""
    properties = feature.get("properties", {}) or {}
    cloud = properties.get("eo:cloud_cover")
    cloud_decimal: Decimal | None = None
    if cloud is not None:
        cloud_decimal = Decimal(str(cloud)).quantize(Decimal("0.01"))

    raw_dt = properties.get("datetime") or properties.get("start_datetime")
    if raw_dt is None:
        raise ValueError(f"Landsat feature {feature.get('id')!r} missing datetime")
    scene_datetime = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))

    return DiscoveredScene(
        scene_id=str(feature["id"]),
        scene_datetime=scene_datetime,
        cloud_cover_pct=cloud_decimal,
        geometry_geojson=feature.get("geometry") or {},
    )


def _gdal_path(signed_href: str) -> str:
    """The GDAL VSI path for a signed asset URL.

    A seam: tests point this at local GeoTIFFs so the window/scaling
    logic can be exercised without network.
    """
    return f"/vsicurl/{signed_href}"


def _read_window_to_cog(
    *,
    signed_hrefs: list[str],
    bands: tuple[str, ...],
    aoi_geojson_utm36n: dict[str, Any],
) -> bytes:
    """Read the AOI window from each band and stack into one COG.

    Runs in a worker thread. All bands share the item's grid, so the
    window is computed once from the first band and reused — that also
    guarantees the stack is pixel-aligned.
    """
    aoi_bounds = shape(aoi_geojson_utm36n).bounds

    with _gdal_vsicurl_env():
        with rasterio.open(_gdal_path(signed_hrefs[0])) as first:
            source_crs = first.crs
            # Egypt sits in UTM 36N, which is already our storage CRS, so
            # this is the common path. The transform is still computed
            # rather than assumed: a farm near a zone boundary would land
            # in a neighbouring UTM zone and silently read the wrong
            # pixels otherwise.
            if source_crs is not None and source_crs.to_epsg() != 32636:
                read_bounds = transform_bounds(
                    "EPSG:32636", source_crs, *aoi_bounds, densify_pts=21
                )
            else:
                read_bounds = aoi_bounds
            window = _aoi_window(first, read_bounds)
            transform = first.window_transform(window)
            height, width = int(window.height), int(window.width)

        stack = np.empty((len(bands), height, width), dtype=np.float32)
        for idx, (band, href) in enumerate(zip(bands, signed_hrefs, strict=True)):
            with rasterio.open(_gdal_path(href)) as ds:
                raw = ds.read(1, window=window)
            stack[idx] = _scale_band(band, raw)

    profile: dict[str, Any] = {
        **default_gtiff_profile,
        "driver": "GTiff",
        "count": len(bands),
        "height": height,
        "width": width,
        "dtype": "float32",
        "crs": source_crs if source_crs is not None else "EPSG:32636",
        "transform": transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "predictor": 2,
        "nodata": float("nan"),
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(stack)
        return bytes(memfile.read())


def _aoi_window(dataset: rasterio.DatasetReader, bounds: tuple[float, ...]) -> Window:
    """The pixel window covering `bounds`, rounded outward and clipped.

    The floor/ceil pair is the point: it guarantees at least one whole
    pixel for any non-degenerate AOI. Our smallest block is 0.53 ha —
    a fraction of a single 30 m cell — and must still read the pixel it
    sits inside rather than collapsing to an empty window.

    Done arithmetically rather than via `Window.round_lengths(op=...)`,
    whose `op` argument is ignored on rasterio >= 1.4: it rounds to
    nearest, which silently turns a sub-pixel AOI into a 0x0 window.
    """
    left, bottom, right, top = bounds
    inverse = ~dataset.transform
    col_a, row_a = inverse * (left, top)
    col_b, row_b = inverse * (right, bottom)

    col_start = max(0, math.floor(min(col_a, col_b)))
    row_start = max(0, math.floor(min(row_a, row_b)))
    col_stop = min(dataset.width, math.ceil(max(col_a, col_b)))
    row_stop = min(dataset.height, math.ceil(max(row_a, row_b)))

    if col_stop <= col_start or row_stop <= row_start:
        raise ValueError("AOI does not intersect the Landsat scene footprint")
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def _scale_band(band: str, raw: NDArray[Any]) -> NDArray[np.float32]:
    """Apply Collection-2 Level-2 scaling, with fill pixels as NaN.

    Fill has to be masked before scaling: a 0 DN would otherwise read as
    a perfectly plausible 149 K.
    """
    values = raw.astype(np.float32, copy=True)
    scaling = _BAND_SCALING.get(band)
    if scaling is None:
        # `qa_pixel` — categorical, and its 0 value is itself meaningful
        # ("no bits set"), so it is not remapped to NaN here.
        return values
    fill = raw == _FILL_DN
    scale, offset = scaling
    values = values * np.float32(scale) + np.float32(offset)
    values[fill] = np.float32("nan")
    return values
