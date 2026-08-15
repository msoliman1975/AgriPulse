"""ImageryService Protocol + concrete impl.

Other modules consume `ImageryService` via DI and only this Protocol —
never the implementation. The repository, models, and provider
adapters are private.

Endpoint paths in `router.py` translate HTTP into method calls; Celery
tasks in `tasks.py` are enqueued by `trigger_refresh()` (the on-demand
path) and by Beat (the scheduled path). Both routes flow through this
service for auditability.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.imagery.errors import (
    FarmAoiNotFetchableError,
    SubscriptionNotFoundError,
)
from app.modules.imagery.events import (
    SubscriptionCreatedV1,
    SubscriptionRevokedV1,
)
from app.modules.imagery.farm_aoi import FarmAoiFit, measure_fit, product_resolution_m
from app.modules.imagery.repository import ImageryRepository
from app.modules.imagery.schemas import (
    ConfigResponse,
    FarmRasterRead,
    FarmSceneAssetRead,
    FarmSceneAssetsResponse,
    FarmSceneRead,
    FarmScenesResponse,
    FarmSubscriptionCreate,
    FarmSubscriptionRead,
    FarmSubscriptionUpdate,
    ImageryConfigEntry,
    IngestionJobRead,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


class ImageryService(Protocol):
    """Public contract for the imagery module."""

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> SubscriptionRead: ...

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[SubscriptionRead, ...]: ...

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> tuple[UUID, ...]: ...

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]: ...

    async def get_config(self) -> ConfigResponse: ...

    async def list_farm_scenes(self, *, farm_id: UUID, limit: int = 120) -> FarmScenesResponse: ...

    async def list_farm_scene_assets(
        self, *, farm_id: UUID, at: datetime | None = None
    ) -> FarmSceneAssetsResponse: ...

    async def list_farm_subscriptions(
        self, *, farm_id: UUID, include_inactive: bool = False
    ) -> tuple[FarmSubscriptionRead, ...]: ...

    async def upsert_farm_subscription(
        self, *, farm_id: UUID, payload: FarmSubscriptionCreate, actor_user_id: UUID | None
    ) -> FarmSubscriptionRead: ...

    async def update_farm_subscription(
        self,
        *,
        subscription_id: UUID,
        payload: FarmSubscriptionUpdate,
        actor_user_id: UUID | None,
    ) -> FarmSubscriptionRead | None: ...


class ImageryServiceImpl:
    """Concrete service. One per request — receives a tenant-scoped session."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._session = tenant_session
        self._repo = ImageryRepository(tenant_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

    # ---- Subscriptions ----------------------------------------------------

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> SubscriptionRead:
        subscription_id = uuid7()
        row = await self._repo.insert_subscription(
            subscription_id=subscription_id,
            block_id=block_id,
            product_id=payload.product_id,
            cadence_hours=payload.cadence_hours,
            cloud_cover_max_pct=payload.cloud_cover_max_pct,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="imagery.subscription_created",
            actor_user_id=actor_user_id,
            subject_kind="imagery_subscription",
            subject_id=subscription_id,
            details={
                "block_id": str(block_id),
                "product_id": str(payload.product_id),
                "cadence_hours": payload.cadence_hours,
                "cloud_cover_max_pct": payload.cloud_cover_max_pct,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            SubscriptionCreatedV1(
                subscription_id=subscription_id,
                block_id=block_id,
                product_id=payload.product_id,
                actor_user_id=actor_user_id,
            )
        )
        return SubscriptionRead.model_validate(row)

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[SubscriptionRead, ...]:
        rows = await self._repo.list_subscriptions(
            block_id=block_id, include_inactive=include_inactive
        )
        return tuple(SubscriptionRead.model_validate(r) for r in rows)

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        before = await self._repo.get_subscription(subscription_id)
        if not before["is_active"]:
            return  # already revoked — idempotent, no audit row
        after = await self._repo.revoke_subscription(
            subscription_id=subscription_id, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="imagery.subscription_revoked",
            actor_user_id=actor_user_id,
            subject_kind="imagery_subscription",
            subject_id=subscription_id,
            details={"block_id": str(after["block_id"])},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            SubscriptionRevokedV1(
                subscription_id=subscription_id,
                block_id=after["block_id"],
                actor_user_id=actor_user_id,
            )
        )

    # ---- Refresh ----------------------------------------------------------

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        """Enqueue `discover_scenes` for every active subscription on the block.

        Returns the list of subscription IDs we just enqueued. Empty
        tuple = there are no active subscriptions on this block.
        """
        # Local import: importing tasks.py at module level would pull
        # Celery into the FastAPI process tree at the wrong moment for
        # some startup orderings. Local import keeps service.py
        # Celery-free.
        from app.modules.imagery.tasks import discover_scenes

        subs = await self._repo.list_subscriptions(block_id=block_id, include_inactive=False)
        ids = tuple(sub["id"] for sub in subs)
        for subscription_id in ids:
            discover_scenes.delay(str(subscription_id), tenant_schema)
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type="imagery.refresh_triggered",
                actor_user_id=actor_user_id,
                subject_kind="imagery_subscription",
                subject_id=subscription_id,
                details={"block_id": str(block_id)},
                correlation_id=correlation_id,
            )
        return ids

    # ---- Scenes (read) ---------------------------------------------------

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]:
        cursor_dt = _decode_scene_cursor(cursor)
        rows, next_cursor_dt = await self._repo.list_ingestion_jobs_for_block(
            block_id=block_id,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            cursor=cursor_dt,
            limit=limit,
        )
        items = tuple(IngestionJobRead.model_validate(r) for r in rows)
        next_cursor = _encode_scene_cursor(next_cursor_dt) if next_cursor_dt else None
        return items, next_cursor

    async def list_farm_scenes(self, *, farm_id: UUID, limit: int = 120) -> FarmScenesResponse:
        rows = await self._repo.list_farm_scene_days(farm_id=farm_id, limit=limit)
        items = tuple(FarmSceneRead.model_validate(r) for r in rows)
        return FarmScenesResponse(
            farm_id=farm_id,
            items=items,
            median_gap_days=_median_gap_days([i.scene_date for i in items]),
        )

    async def list_farm_scene_assets(
        self, *, farm_id: UUID, at: datetime | None = None
    ) -> FarmSceneAssetsResponse:
        rows = await self._repo.list_farm_scene_assets(farm_id=farm_id, at=at)
        # The farm-wide raster wins when there is one: same ground, one file,
        # no seam. The per-block items still ride along so a client that
        # predates the field keeps working unchanged.
        farm_row = await self._repo.get_farm_scene_raster(farm_id=farm_id, at=at)
        return FarmSceneAssetsResponse(
            farm_id=farm_id,
            at=at,
            farm=FarmRasterRead.model_validate(farm_row) if farm_row else None,
            items=tuple(FarmSceneAssetRead.model_validate(r) for r in rows),
        )

    # ---- Farm-level subscriptions ----------------------------------------
    #
    # The farm is the unit imagery is actually fetched for. These replace the
    # per-block rows as the configuration surface; the block rows stay until
    # the cutover so a farm can be moved one at a time.

    async def list_farm_subscriptions(
        self, *, farm_id: UUID, include_inactive: bool = False
    ) -> tuple[FarmSubscriptionRead, ...]:
        rows = await self._repo.list_farm_subscriptions(
            farm_id=farm_id, include_inactive=include_inactive
        )
        if not rows:
            return ()
        # One boundary read and one product read for the whole list, rather
        # than a pair per row.
        farm = await self._repo.get_farm_boundary(farm_id)
        resolutions = await self._repo.product_resolutions()
        return tuple(
            FarmSubscriptionRead.model_validate(
                {**r, **self._fit_fields(self._measure(farm, resolutions.get(r["product_id"])))}
            )
            for r in rows
        )

    async def upsert_farm_subscription(
        self, *, farm_id: UUID, payload: FarmSubscriptionCreate, actor_user_id: UUID | None
    ) -> FarmSubscriptionRead:
        if payload.fetch_farm_aoi:
            await self._require_fetchable(farm_id=farm_id, product_id=payload.product_id)
        row = await self._repo.upsert_farm_subscription(
            subscription_id=uuid7(),
            farm_id=farm_id,
            product_id=payload.product_id,
            cadence_hours=payload.cadence_hours,
            cloud_cover_max_pct=payload.cloud_cover_max_pct,
            fetch_farm_aoi=payload.fetch_farm_aoi,
            actor_user_id=actor_user_id,
        )
        return await self._read_with_fit(row)

    async def update_farm_subscription(
        self,
        *,
        subscription_id: UUID,
        payload: FarmSubscriptionUpdate,
        actor_user_id: UUID | None,
    ) -> FarmSubscriptionRead | None:
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("fetch_farm_aoi"):
            # Read the row first: the caller gives a subscription id, and the
            # farm and product are what decide whether the fetch can happen.
            existing = await self._repo.get_farm_subscription(subscription_id)
            if existing is not None:
                await self._require_fetchable(
                    farm_id=existing["farm_id"], product_id=existing["product_id"]
                )
        row = await self._repo.update_farm_subscription(
            subscription_id=subscription_id,
            changes=changes,
            actor_user_id=actor_user_id,
        )
        return await self._read_with_fit(row) if row is not None else None

    # ---- farm-AOI fetchability -------------------------------------------
    #
    # Measured on every read instead of stored. A farm's boundary can be
    # redrawn at any time, so a persisted verdict would be wrong with nothing
    # to notice it — and this is cheap: a bbox over a geometry we already read.

    @staticmethod
    def _measure(farm: dict[str, Any] | None, resolution_raw: Any) -> FarmAoiFit:
        return measure_fit(
            farm["boundary_utm_geojson"] if farm else None,
            resolution_m=product_resolution_m({"resolution_m": resolution_raw}),
        )

    @staticmethod
    def _fit_fields(fit: FarmAoiFit) -> dict[str, Any]:
        return {
            "farm_aoi_fetchable": fit.fits,
            "farm_aoi_width_px": fit.width_px,
            "farm_aoi_height_px": fit.height_px,
            "farm_aoi_max_px": fit.max_px,
        }

    async def _fit_for(self, *, farm_id: UUID, product_id: UUID) -> FarmAoiFit:
        farm = await self._repo.get_farm_boundary(farm_id)
        resolutions = await self._repo.product_resolutions()
        return self._measure(farm, resolutions.get(product_id))

    async def _require_fetchable(self, *, farm_id: UUID, product_id: UUID) -> None:
        fit = await self._fit_for(farm_id=farm_id, product_id=product_id)
        if not fit.fits:
            raise FarmAoiNotFetchableError(
                width_px=fit.width_px, height_px=fit.height_px, max_px=fit.max_px
            )

    async def _read_with_fit(self, row: dict[str, Any]) -> FarmSubscriptionRead:
        fit = await self._fit_for(farm_id=row["farm_id"], product_id=row["product_id"])
        return FarmSubscriptionRead.model_validate({**row, **self._fit_fields(fit)})

    async def get_config(self) -> ConfigResponse:
        """GET /api/v1/config payload — tile-server URL + product hints."""
        from app.core.settings import get_settings

        settings = get_settings()
        products = await self._repo.list_products()
        return ConfigResponse(
            tile_server_base_url=settings.tile_server_base_url,
            # Bucket name surfaced so the SPA can build `s3://bucket/key`
            # tile URLs to pass to TiTiler. PR-D Q1.
            s3_bucket=settings.s3_bucket_uploads,
            cloud_cover_visualization_max_pct=(settings.imagery_cloud_cover_visualization_max_pct),
            cloud_cover_aggregation_max_pct=(settings.imagery_cloud_cover_aggregation_max_pct),
            products=tuple(
                ImageryConfigEntry(
                    product_id=p["product_id"],
                    product_code=p["product_code"],
                    product_name=p["product_name"],
                    bands=tuple(p["bands"]),
                    supported_indices=tuple(p["supported_indices"]),
                )
                for p in products
            ),
        )


def _median_gap_days(dates: Sequence[date]) -> float | None:
    """Median gap between consecutive acquisition days, newest first.

    Median rather than mean because the tail of any real farm's history has
    long cloud-driven gaps, and one 40-day hole would drag a mean out to a
    number that predicts nothing.

    Deliberately derived from observed history rather than from
    ``imagery_products.revisit_days_avg``: the nominal revisit is what the
    constellation offers, while this is what this farm's subscriptions have
    actually delivered — including a cadence set to poll less often than the
    satellite flies.
    """
    if len(dates) < 3:
        return None
    # Only the recent stretch: cadence changes, and old history should not
    # keep voting on what "next" means.
    recent = list(dates[:10])
    gaps = [
        (recent[i] - recent[i + 1]).days
        for i in range(len(recent) - 1)
        if (recent[i] - recent[i + 1]).days > 0
    ]
    if not gaps:
        return None
    gaps.sort()
    mid = len(gaps) // 2
    return float(gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2)


# --- Cursor helpers (datetime-based for scene listing) ---------------------


def _encode_scene_cursor(dt: datetime) -> str:
    """ISO-8601 encoded datetime; base64 to keep it opaque on the wire."""
    import base64

    return base64.urlsafe_b64encode(dt.isoformat().encode()).decode().rstrip("=")


def _decode_scene_cursor(value: str | None) -> datetime | None:
    if value is None:
        return None
    import base64

    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded).decode()
        return datetime.fromisoformat(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def get_imagery_service(
    *,
    tenant_session: AsyncSession,
    audit_service: AuditService | None = None,
    event_bus: EventBus | None = None,
) -> ImageryService:
    """Factory used by the router's FastAPI dependency."""
    return ImageryServiceImpl(
        tenant_session=tenant_session,
        audit_service=audit_service,
        event_bus=event_bus,
    )


# Suppress unused-import warning when these are referenced only inside
# Protocol annotations.
_ = (datetime, UTC, SubscriptionNotFoundError)
