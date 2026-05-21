"""Synchronous Sentinel Hub client — OAuth + discover + multi-band fetch."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

_OAUTH_URL = "https://services.sentinel-hub.com/oauth/token"
_CATALOG_URL = "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search"
_PROCESS_URL = "https://services.sentinel-hub.com/api/v1/process"

_TOKEN_REFRESH_LEAD_SECONDS = 600
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0

S2_L2A_BAND_ORDER: tuple[str, ...] = (
    "blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2",
)
_SH_BAND_NAMES: dict[str, str] = {
    "blue": "B02", "green": "B03", "red": "B04",
    "red_edge_1": "B05", "nir": "B08", "swir1": "B11", "swir2": "B12",
}


@dataclass(frozen=True, slots=True)
class DiscoveredScene:
    scene_id: str
    scene_datetime: datetime
    cloud_cover_pct: Decimal | None
    geometry_geojson: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FetchResult:
    cog_bytes: bytes
    band_order: tuple[str, ...]
    content_type: str


class SentinelHubError(RuntimeError):
    pass


class SentinelHubClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        oauth_url: str = _OAUTH_URL,
        catalog_url: str = _CATALOG_URL,
        process_url: str = _PROCESS_URL,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._catalog_url = catalog_url
        self._process_url = process_url
        self._http = httpx.Client(timeout=httpx.Timeout(timeout_seconds))
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def __enter__(self) -> "SentinelHubClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _bearer_token(self) -> str:
        now = time.time()
        if self._token is None or self._token_expires_at - now < _TOKEN_REFRESH_LEAD_SECONDS:
            self._refresh_token()
        assert self._token is not None
        return self._token

    def _refresh_token(self) -> None:
        response = self._http.post(
            self._oauth_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise SentinelHubError(
                f"OAuth token refresh failed: HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        self._token = str(body["access_token"])
        self._token_expires_at = time.time() + int(body.get("expires_in", 3600))

    def discover(
        self,
        *,
        aoi_geojson_wgs84: dict[str, Any],
        from_datetime: datetime,
        to_datetime: datetime,
        max_cloud_cover_pct: int | None = None,
    ) -> tuple[DiscoveredScene, ...]:
        token = self._bearer_token()
        results: list[DiscoveredScene] = []
        next_cursor: str | None = None
        page = 0
        while True:
            page += 1
            if page > 20:
                break

            payload: dict[str, Any] = {
                "collections": ["sentinel-2-l2a"],
                "datetime": (
                    f"{from_datetime.astimezone(UTC).isoformat()}/"
                    f"{to_datetime.astimezone(UTC).isoformat()}"
                ),
                "intersects": aoi_geojson_wgs84,
                "limit": 100,
            }
            if max_cloud_cover_pct is not None:
                payload["filter-lang"] = "cql2-text"
                payload["filter"] = f"eo:cloud_cover<={max_cloud_cover_pct}"
            if next_cursor is not None:
                payload["next"] = next_cursor

            response = self._post_with_retry(
                self._catalog_url,
                json_body=payload,
                token=token,
                accept="application/geo+json",
            )
            body = response.json()
            for feature in body.get("features", []) or []:
                results.append(_feature_to_discovered(feature))

            ctx = body.get("context", {}) or {}
            next_cursor = ctx.get("next")
            if not next_cursor:
                break

        results.sort(key=lambda s: s.scene_datetime)
        return tuple(results)

    def fetch_multiband(
        self,
        *,
        scene_id: str,
        scene_datetime: datetime,
        aoi_geojson_utm: dict[str, Any],
        utm_epsg: int,
    ) -> FetchResult:
        token = self._bearer_token()
        sh_bands = [_SH_BAND_NAMES[b] for b in S2_L2A_BAND_ORDER]
        evalscript = _build_multiband_evalscript(sh_bands)

        scene_dt_utc = scene_datetime.astimezone(UTC)
        window_from = (scene_dt_utc - timedelta(hours=12)).isoformat()
        window_to = (scene_dt_utc + timedelta(hours=12)).isoformat()

        payload = {
            "input": {
                "bounds": {
                    "geometry": aoi_geojson_utm,
                    "properties": {
                        "crs": f"http://www.opengis.net/def/crs/EPSG/0/{utm_epsg}"
                    },
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {"from": window_from, "to": window_to},
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
        response = self._post_with_retry(
            self._process_url,
            json_body=payload,
            token=token,
            accept="image/tiff",
        )
        return FetchResult(
            cog_bytes=response.content,
            band_order=S2_L2A_BAND_ORDER,
            content_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

    def _post_with_retry(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        token: str,
        accept: str,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "Content-Type": "application/json",
        }
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._http.post(url, json=json_body, headers=headers)
            except httpx.TransportError as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise SentinelHubError(f"network error: {exc}") from exc
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if response.status_code >= 500:
                if attempt == _MAX_RETRIES - 1:
                    raise SentinelHubError(
                        f"upstream {response.status_code}: {response.text[:500]}"
                    )
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise SentinelHubError(
                    f"HTTP {response.status_code}: {response.text[:500]}"
                )
            return response
        raise SentinelHubError("retry loop exited without a result")


def _feature_to_discovered(feature: dict[str, Any]) -> DiscoveredScene:
    properties = feature.get("properties", {}) or {}
    cloud = properties.get("eo:cloud_cover")
    cloud_decimal: Decimal | None = None
    if cloud is not None:
        cloud_decimal = Decimal(str(cloud)).quantize(Decimal("0.01"))

    raw_dt = properties.get("datetime") or properties.get("start_datetime")
    if raw_dt is None:
        raise SentinelHubError(f"feature {feature.get('id')!r} missing datetime")
    scene_datetime = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))

    return DiscoveredScene(
        scene_id=str(feature["id"]),
        scene_datetime=scene_datetime,
        cloud_cover_pct=cloud_decimal,
        geometry_geojson=feature.get("geometry") or {},
    )


def _build_multiband_evalscript(sh_band_names: list[str]) -> str:
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
