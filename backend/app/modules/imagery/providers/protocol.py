"""ImageryProvider Protocol — the contract every provider adapter satisfies.

Per ARCHITECTURE.md § 9 the platform supports per-product adapters
(`SentinelHubProvider` in MVP; future `PlanetScopeProvider`,
`Sentinel2OpenDataProvider`). The Protocol is narrow on purpose: a
discovery method that returns scene candidates for an AOI / time window,
and a fetch method that pulls a specific scene's raw bands as bytes
the orchestrator can write to S3.

The orchestrator (Celery `acquire_scene` task in PR-B) owns the S3
upload, the database state transitions, and the retry / idempotency
logic — providers stay stateless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DiscoveredScene:
    """A candidate scene returned by `ImageryProvider.discover()`."""

    scene_id: str
    scene_datetime: datetime
    cloud_cover_pct: Decimal | None
    geometry_geojson: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Bytes + metadata returned by `ImageryProvider.fetch()`.

    `cog_bytes` is a multi-band Cloud Optimized GeoTIFF in UTM 36N
    (EPSG:32636). `band_order` documents the band ordering in the COG
    so the indices computation step (PR-C) can read each by index.
    """

    cog_bytes: bytes
    band_order: tuple[str, ...]
    content_type: str = "image/tiff; application=geotiff; profile=cloud-optimized"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a liveness probe — PR-IH5. Mirrors the weather variant.

    Status: 'ok' | 'error' | 'timeout'.
    """

    status: str
    latency_ms: int | None = None
    error_message: str | None = None


class ImageryProvider(Protocol):
    """The contract every provider adapter satisfies.

    All methods are async. Implementations are stateless aside from
    a cached OAuth token; concurrency is the orchestrator's concern.
    """

    @property
    def code(self) -> str:
        """The provider code matching `public.imagery_providers.code`."""
        ...

    async def probe(self) -> ProbeResult:
        """Cheap liveness check. See WeatherProvider.probe."""
        ...

    async def discover(
        self,
        *,
        aoi_geojson: dict[str, Any],
        product_code: str,
        from_datetime: datetime,
        to_datetime: datetime,
        max_cloud_cover_pct: int | None = None,
    ) -> tuple[DiscoveredScene, ...]:
        """List candidate scenes intersecting the AOI within the time window.

        Returns scenes ordered by `scene_datetime` ascending. May return
        an empty tuple. Implementations must raise on transport / auth
        errors — the orchestrator translates exceptions to
        `IngestionFailedV1` events.
        """
        ...

    async def fetch(
        self,
        *,
        scene_id: str,
        scene_datetime: datetime,
        product_code: str,
        aoi_geojson_utm36n: dict[str, Any],
        bands: tuple[str, ...],
    ) -> FetchResult:
        """Pull the requested bands for a specific scene as a multi-band COG.

        The AOI is supplied in UTM 36N (EPSG:32636) — that's the storage
        CRS per ARCHITECTURE.md § 9. Provider adapters that prefer a
        different CRS internally are responsible for re-projecting.

        ``scene_datetime`` lets adapters whose APIs filter by time
        window (e.g. Sentinel Hub Process) target a specific scene
        without parsing ``scene_id``.
        """
        ...
