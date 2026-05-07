"""Weather service — public Protocol + concrete impl + factory.

PR-A declared the Protocol so other modules could depend on the
contract before the impl existed. PR-B fills in the concrete class and
the factory; the Protocol stays as the public type other modules
should import.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.weather.errors import (
    BlockNotVisibleError,
    WeatherSubscriptionNotFoundError,
)
from app.modules.weather.repository import WeatherRepository
from app.modules.weather.schemas import (
    DailyForecastRead,
    DerivedDailyRead,
    ForecastResponse,
    HourlyObservationRead,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.modules.weather.timezone import tz_for_centroid, tz_name_for_centroid
from app.shared.db.ids import uuid7


class WeatherService(Protocol):
    """Public contract for the `weather` module."""

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
        block_id: UUID,
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

    # PR-C reads.
    async def get_forecast(
        self,
        *,
        block_id: UUID,
        horizon_days: int,
        provider_code: str = "open_meteo",
    ) -> ForecastResponse: ...

    async def get_observations(
        self,
        *,
        block_id: UUID,
        since: datetime,
        until: datetime,
        provider_code: str | None = None,
    ) -> tuple[HourlyObservationRead, ...]: ...

    async def get_derived_daily(
        self,
        *,
        block_id: UUID,
        since: date_type,
        until: date_type,
    ) -> tuple[DerivedDailyRead, ...]: ...


class WeatherServiceImpl:
    """Concrete implementation of `WeatherService`. Tenant-session scoped."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        audit_service: AuditService | None = None,
    ) -> None:
        self._session = tenant_session
        self._repo = WeatherRepository(tenant_session)
        self._audit = audit_service or get_audit_service()
        self._log = get_logger(__name__)

    # ---- Subscriptions ---------------------------------------------------

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
            provider_code=payload.provider_code,
            cadence_hours=payload.cadence_hours,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="weather.subscription_created",
            actor_user_id=actor_user_id,
            subject_kind="weather_subscription",
            subject_id=subscription_id,
            details={
                "block_id": str(block_id),
                "provider_code": payload.provider_code,
                "cadence_hours": payload.cadence_hours,
            },
            correlation_id=correlation_id,
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
        block_id: UUID,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        before = await self._repo.get_subscription(subscription_id)
        if before["block_id"] != block_id:
            # Caller passed a sub_id that doesn't belong to this block.
            # Surface as 404 so we don't leak cross-block existence.
            raise WeatherSubscriptionNotFoundError(str(subscription_id))
        if not before["is_active"]:
            return  # idempotent revoke
        after = await self._repo.revoke_subscription(
            subscription_id=subscription_id, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="weather.subscription_revoked",
            actor_user_id=actor_user_id,
            subject_kind="weather_subscription",
            subject_id=subscription_id,
            details={
                "block_id": str(after["block_id"]),
                "provider_code": after["provider_code"],
            },
            correlation_id=correlation_id,
        )

    # ---- Refresh ---------------------------------------------------------

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        """Enqueue `weather.fetch_weather` for the block's farm if there's
        an active subscription. Returns the farm_ids actually queued
        (typically a single UUID).
        """
        from app.modules.weather.tasks import fetch_weather

        block_meta = await self._repo.get_block_farm_centroid(block_id)
        if block_meta is None:
            return ()
        farm_id: UUID = block_meta["farm_id"]

        # Distinct provider codes with at least one active subscription
        # on this block.
        rows = await self._repo.list_subscriptions(block_id=block_id, include_inactive=False)
        provider_codes = {r["provider_code"] for r in rows}
        if not provider_codes:
            return ()

        for code in provider_codes:
            fetch_weather.delay(str(farm_id), tenant_schema, code)
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type="weather.refresh_triggered",
                actor_user_id=actor_user_id,
                subject_kind="farm",
                subject_id=farm_id,
                details={
                    "block_id": str(block_id),
                    "provider_code": code,
                },
                correlation_id=correlation_id,
            )
        return (farm_id,)

    # ---- Reads -----------------------------------------------------------

    async def get_forecast(
        self,
        *,
        block_id: UUID,
        horizon_days: int,
        provider_code: str = "open_meteo",
    ) -> ForecastResponse:
        """Daily-aggregated forecast in the farm's local timezone.

        Reads from `weather_forecasts` (latest issuance per hour),
        buckets hourly rows into local-tz days, and returns at most
        ``horizon_days`` of aggregations starting from "today" in the
        farm tz.
        """
        block_meta = await self._repo.get_block_farm_centroid(block_id)
        if block_meta is None:
            raise BlockNotVisibleError(str(block_id))
        farm_id: UUID = block_meta["farm_id"]
        tz = tz_for_centroid(block_meta["latitude"], block_meta["longitude"])
        tz_name = tz_name_for_centroid(block_meta["latitude"], block_meta["longitude"])

        # Window: today's local-midnight through (today + horizon_days)
        # local-midnight, both expressed in UTC for the hypertable scan.
        today_local = datetime.now(tz).date()
        end_local = today_local + timedelta(days=horizon_days)
        since_utc = datetime.combine(today_local, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        until_utc = datetime.combine(end_local, datetime.min.time(), tzinfo=tz).astimezone(UTC)

        rows = await self._repo.read_latest_forecast(
            farm_id=farm_id,
            provider_code=provider_code,
            since=since_utc,
            until=until_utc,
        )

        # Bucket by local date, then aggregate. The row dicts come from
        # asyncpg's mapping rows — typed loosely as object — so we
        # narrow each numeric column to Decimal explicitly before doing
        # comparisons / arithmetic.
        by_day: dict[date_type, list[dict[str, Any]]] = {}
        latest_issued: datetime | None = None
        for r in rows:
            local_dt = r["time"].astimezone(tz)
            by_day.setdefault(local_dt.date(), []).append(r)
            issued = r["forecast_issued_at"]
            if latest_issued is None or issued > latest_issued:
                latest_issued = issued

        days: list[DailyForecastRead] = []
        for offset in range(horizon_days):
            d = today_local + timedelta(days=offset)
            bucket = by_day.get(d, [])
            temps: list[Decimal] = [b["air_temp_c"] for b in bucket if b["air_temp_c"] is not None]
            precs: list[Decimal] = [
                b["precipitation_mm"] for b in bucket if b["precipitation_mm"] is not None
            ]
            probs: list[Decimal] = [
                b["precipitation_probability_pct"]
                for b in bucket
                if b["precipitation_probability_pct"] is not None
            ]
            precip_total = sum(precs, start=Decimal(0)) if precs else None
            days.append(
                DailyForecastRead(
                    date=d,
                    high_c=max(temps) if temps else None,
                    low_c=min(temps) if temps else None,
                    precip_mm_total=(
                        precip_total.quantize(Decimal("0.01")) if precip_total is not None else None
                    ),
                    precip_probability_max_pct=max(probs) if probs else None,
                )
            )

        return ForecastResponse(
            farm_id=farm_id,
            provider_code=provider_code,
            timezone=tz_name,
            forecast_issued_at=latest_issued,
            days=tuple(days),
        )

    async def get_observations(
        self,
        *,
        block_id: UUID,
        since: datetime,
        until: datetime,
        provider_code: str | None = None,
    ) -> tuple[HourlyObservationRead, ...]:
        block_meta = await self._repo.get_block_farm_centroid(block_id)
        if block_meta is None:
            raise BlockNotVisibleError(str(block_id))
        rows = await self._repo.read_observations(
            farm_id=block_meta["farm_id"],
            provider_code=provider_code,
            since=since,
            until=until,
        )
        return tuple(HourlyObservationRead.model_validate(r) for r in rows)

    async def get_derived_daily(
        self,
        *,
        block_id: UUID,
        since: date_type,
        until: date_type,
    ) -> tuple[DerivedDailyRead, ...]:
        block_meta = await self._repo.get_block_farm_centroid(block_id)
        if block_meta is None:
            raise BlockNotVisibleError(str(block_id))
        rows = await self._repo.read_derived_daily(
            farm_id=block_meta["farm_id"],
            since=since,
            until=until,
        )
        return tuple(DerivedDailyRead.model_validate(r) for r in rows)


def get_weather_service(*, tenant_session: AsyncSession) -> WeatherServiceImpl:
    """Factory used by routers and Celery tasks."""
    return WeatherServiceImpl(tenant_session=tenant_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: WeatherServiceImpl) -> WeatherService:
    return impl
