"""Async DB access for the weather module. Internal to the module.

Reads/writes for `weather_subscriptions`, `weather_observations`, and
`weather_forecasts`. Hypertable inserts use ``ON CONFLICT DO NOTHING``
on the unique key so re-fetching the same issuance is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, bindparam, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.weather.errors import (
    WeatherProviderNotFoundError,
    WeatherSubscriptionAlreadyExistsError,
    WeatherSubscriptionNotFoundError,
)
from app.modules.weather.models import WeatherSubscription
from app.modules.weather.providers.protocol import HourlyForecast, HourlyObservation


class WeatherRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Subscriptions -------------------------------------------------

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        clauses = [WeatherSubscription.block_id == block_id]
        if not include_inactive:
            clauses.append(WeatherSubscription.is_active.is_(True))
        clauses.append(WeatherSubscription.deleted_at.is_(None))
        rows = (
            (
                await self._session.execute(
                    select(WeatherSubscription)
                    .where(and_(*clauses))
                    .order_by(WeatherSubscription.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return tuple(_subscription_to_dict(r) for r in rows)

    async def get_subscription(self, subscription_id: UUID) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(WeatherSubscription).where(
                    and_(
                        WeatherSubscription.id == subscription_id,
                        WeatherSubscription.deleted_at.is_(None),
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise WeatherSubscriptionNotFoundError(str(subscription_id))
        return _subscription_to_dict(row)

    async def insert_subscription(
        self,
        *,
        subscription_id: UUID,
        block_id: UUID,
        provider_code: str,
        cadence_hours: int | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Validate provider_code points at an active row in the public
        # catalog. We do this in app code rather than via FK so the
        # cross-schema link stays a logical reference (data_model § 8).
        provider_ok = await self._session.execute(
            text(
                "SELECT 1 FROM public.weather_providers "
                "WHERE code = :code AND is_active = TRUE AND deleted_at IS NULL"
            ),
            {"code": provider_code},
        )
        if provider_ok.scalar_one_or_none() is None:
            raise WeatherProviderNotFoundError(provider_code)

        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO weather_subscriptions
                    (id, block_id, provider_code, cadence_hours,
                     is_active, created_by, updated_by)
                    VALUES (:id, :block_id, :provider_code, :cadence_hours,
                            TRUE, :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": subscription_id,
                    "block_id": block_id,
                    "provider_code": provider_code,
                    "cadence_hours": cadence_hours,
                    "actor": actor_user_id,
                },
            )
        except Exception as exc:  # asyncpg UniqueViolation surfaces as IntegrityError
            msg = str(exc)
            if (
                "uq_weather_subscriptions_block_provider_active" in msg
                or "duplicate key" in msg.lower()
            ):
                raise WeatherSubscriptionAlreadyExistsError() from exc
            raise

        return await self.get_subscription(subscription_id)

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        await self._session.execute(
            update(WeatherSubscription)
            .where(WeatherSubscription.id == subscription_id)
            .values(is_active=False, updated_by=actor_user_id)
        )
        return await self.get_subscription(subscription_id)

    async def touch_subscription_attempt(
        self,
        *,
        subscription_id: UUID,
        attempted_at: datetime,
        success: bool,
    ) -> None:
        values: dict[str, Any] = {"last_attempted_at": attempted_at}
        if success:
            values["last_successful_ingest_at"] = attempted_at
        await self._session.execute(
            update(WeatherSubscription)
            .where(WeatherSubscription.id == subscription_id)
            .values(**values)
        )

    # ---- Subscription discovery (Beat sweep helper) -------------------

    async def list_active_subscriptions_for_farm(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
    ) -> tuple[dict[str, Any], ...]:
        """Every active subscription on the given (farm_id, provider_code).

        We need the farm_id even though the subscription only stores
        block_id, so the caller has done the join. Used by the
        ingestion task to update `last_*_at` on every subscription
        whose farm just got refreshed.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT s.id, s.block_id, s.cadence_hours
                    FROM weather_subscriptions s
                    JOIN blocks b ON b.id = s.block_id
                    WHERE b.farm_id = :farm_id
                      AND s.provider_code = :provider_code
                      AND s.is_active = TRUE
                      AND s.deleted_at IS NULL
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id, "provider_code": provider_code},
            )
        ).all()
        return tuple(
            {"id": r.id, "block_id": r.block_id, "cadence_hours": r.cadence_hours} for r in rows
        )

    async def list_due_farm_provider_pairs(
        self,
        *,
        default_cadence_hours: int,
        now: datetime,
    ) -> tuple[tuple[UUID, str], ...]:
        """Return distinct (farm_id, provider_code) tuples whose oldest
        active subscription is overdue.

        Beat-sweep entry point. Dedup is done in SQL: many subscriptions
        on the same farm collapse to one fetch per cycle.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT DISTINCT b.farm_id, s.provider_code
                    FROM weather_subscriptions s
                    JOIN blocks b ON b.id = s.block_id
                    WHERE s.is_active = TRUE
                      AND s.deleted_at IS NULL
                      AND (
                            s.last_attempted_at IS NULL
                            OR s.last_attempted_at <
                               (:now - make_interval(
                                    hours => COALESCE(
                                        s.cadence_hours,
                                        :default_cadence
                                    )
                               ))
                          )
                    """
                ).bindparams(now=now, default_cadence=default_cadence_hours)
            )
        ).all()
        return tuple((row.farm_id, row.provider_code) for row in rows)

    # ---- Hypertable writers --------------------------------------------

    async def upsert_observations(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
        observations: Sequence[HourlyObservation],
    ) -> int:
        """Bulk insert into `weather_observations`. Returns rows actually inserted."""
        if not observations:
            return 0
        # asyncpg + SQLAlchemy core: one statement per row keeps the
        # error path simple. Volume is ~24-72 rows per fetch — not
        # worth executemany or COPY.
        inserted = 0
        for o in observations:
            res = await self._session.execute(
                text(
                    """
                    INSERT INTO weather_observations (
                        time, farm_id, provider_code,
                        air_temp_c, humidity_pct, precipitation_mm,
                        wind_speed_m_s, wind_direction_deg, pressure_hpa,
                        solar_radiation_w_m2, cloud_cover_pct, et0_mm
                    ) VALUES (
                        :time, :farm_id, :provider_code,
                        :air_temp_c, :humidity_pct, :precipitation_mm,
                        :wind_speed_m_s, :wind_direction_deg, :pressure_hpa,
                        :solar_radiation_w_m2, :cloud_cover_pct, :et0_mm
                    )
                    ON CONFLICT (time, farm_id, provider_code) DO NOTHING
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {
                    "time": o.time,
                    "farm_id": farm_id,
                    "provider_code": provider_code,
                    "air_temp_c": _d(o.air_temp_c),
                    "humidity_pct": _d(o.humidity_pct),
                    "precipitation_mm": _d(o.precipitation_mm),
                    "wind_speed_m_s": _d(o.wind_speed_m_s),
                    "wind_direction_deg": _d(o.wind_direction_deg),
                    "pressure_hpa": _d(o.pressure_hpa),
                    "solar_radiation_w_m2": _d(o.solar_radiation_w_m2),
                    "cloud_cover_pct": _d(o.cloud_cover_pct),
                    "et0_mm": _d(o.et0_mm),
                },
            )
            inserted += getattr(res, "rowcount", 0) or 0
        return int(inserted)

    async def upsert_forecasts(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
        forecast_issued_at: datetime,
        forecasts: Sequence[HourlyForecast],
    ) -> int:
        if not forecasts:
            return 0
        inserted = 0
        for f in forecasts:
            res = await self._session.execute(
                text(
                    """
                    INSERT INTO weather_forecasts (
                        time, forecast_issued_at, farm_id, provider_code,
                        air_temp_c, humidity_pct,
                        precipitation_mm, precipitation_probability_pct,
                        wind_speed_m_s, solar_radiation_w_m2, et0_mm
                    ) VALUES (
                        :time, :forecast_issued_at, :farm_id, :provider_code,
                        :air_temp_c, :humidity_pct,
                        :precipitation_mm, :precip_prob,
                        :wind_speed_m_s, :solar_radiation_w_m2, :et0_mm
                    )
                    ON CONFLICT (time, farm_id, provider_code, forecast_issued_at)
                    DO NOTHING
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {
                    "time": f.time,
                    "forecast_issued_at": forecast_issued_at,
                    "farm_id": farm_id,
                    "provider_code": provider_code,
                    "air_temp_c": _d(f.air_temp_c),
                    "humidity_pct": _d(f.humidity_pct),
                    "precipitation_mm": _d(f.precipitation_mm),
                    "precip_prob": _d(f.precipitation_probability_pct),
                    "wind_speed_m_s": _d(f.wind_speed_m_s),
                    "solar_radiation_w_m2": _d(f.solar_radiation_w_m2),
                    "et0_mm": _d(f.et0_mm),
                },
            )
            inserted += getattr(res, "rowcount", 0) or 0
        return int(inserted)

    # ---- Cross-module reader -------------------------------------------

    async def get_block_farm_centroid(self, block_id: UUID) -> dict[str, Any] | None:
        """Look up a block's farm_id + farm centroid (lat, lon)."""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT
                        b.farm_id,
                        ST_Y(ST_Centroid(f.boundary)::geometry) AS latitude,
                        ST_X(ST_Centroid(f.boundary)::geometry) AS longitude
                    FROM blocks b
                    JOIN farms f ON f.id = b.farm_id
                    WHERE b.id = :block_id AND b.deleted_at IS NULL
                    """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return {
            "farm_id": row.farm_id,
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
        }

    async def get_farm_centroid(self, farm_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT
                        ST_Y(ST_Centroid(boundary)::geometry) AS latitude,
                        ST_X(ST_Centroid(boundary)::geometry) AS longitude
                    FROM farms
                    WHERE id = :farm_id AND deleted_at IS NULL
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return {"latitude": float(row.latitude), "longitude": float(row.longitude)}

    # ---- Read paths (PR-C) ---------------------------------------------

    async def read_observations(
        self,
        *,
        farm_id: UUID,
        provider_code: str | None,
        since: datetime,
        until: datetime,
    ) -> tuple[dict[str, Any], ...]:
        """Hourly observations in [since, until). Time-ordered ascending.

        ``provider_code`` filters when set; None returns every provider's
        rows. The hypertable is keyed on ``(time, farm_id, provider_code)``,
        so the (farm_id, time-range) range scan is index-supported.
        """
        clauses = ["farm_id = :farm_id", "time >= :since", "time < :until"]
        params: dict[str, Any] = {"farm_id": farm_id, "since": since, "until": until}
        if provider_code is not None:
            clauses.append("provider_code = :provider_code")
            params["provider_code"] = provider_code
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT time, farm_id, provider_code,
                               air_temp_c, humidity_pct, precipitation_mm,
                               wind_speed_m_s, wind_direction_deg, pressure_hpa,
                               solar_radiation_w_m2, cloud_cover_pct, et0_mm
                        FROM weather_observations
                        WHERE {" AND ".join(clauses)}
                        ORDER BY time ASC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def read_latest_forecast(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
        since: datetime,
        until: datetime,
    ) -> tuple[dict[str, Any], ...]:
        """Latest-issuance forecast hours in [since, until). Time-ordered ascending.

        ``DISTINCT ON (time)`` collapses the keep-all-issuances history
        (per the Slice-4 lock) to one row per hour, picking whichever
        ``forecast_issued_at`` is most recent. Provider is required —
        cross-provider reconciliation is out of scope.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT DISTINCT ON (time)
                               time, forecast_issued_at, farm_id, provider_code,
                               air_temp_c, humidity_pct,
                               precipitation_mm, precipitation_probability_pct,
                               wind_speed_m_s, solar_radiation_w_m2, et0_mm
                        FROM weather_forecasts
                        WHERE farm_id = :farm_id
                          AND provider_code = :provider_code
                          AND time >= :since
                          AND time < :until
                        ORDER BY time ASC, forecast_issued_at DESC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {
                        "farm_id": farm_id,
                        "provider_code": provider_code,
                        "since": since,
                        "until": until,
                    },
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def read_derived_daily(
        self,
        *,
        farm_id: UUID,
        since: date_type,
        until: date_type,
    ) -> tuple[dict[str, Any], ...]:
        """Per-day derived rows in [since, until). Date-ordered ascending."""
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT farm_id, date,
                               gdd_base10, gdd_base15, gdd_cumulative_base10_season,
                               et0_mm_daily, precip_mm_daily,
                               precip_mm_7d, precip_mm_30d,
                               temp_min_c, temp_max_c, temp_mean_c,
                               computed_at
                        FROM weather_derived_daily
                        WHERE farm_id = :farm_id
                          AND date >= :since
                          AND date < :until
                        ORDER BY date ASC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "since": since, "until": until},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def upsert_derived_daily(
        self,
        *,
        farm_id: UUID,
        date: date_type,
        temp_min_c: Decimal | None,
        temp_max_c: Decimal | None,
        temp_mean_c: Decimal | None,
        precip_mm_daily: Decimal | None,
        et0_mm_daily: Decimal | None,
        gdd_base10: Decimal | None,
        gdd_base15: Decimal | None,
        gdd_cumulative_base10_season: Decimal | None,
        precip_mm_7d: Decimal | None,
        precip_mm_30d: Decimal | None,
    ) -> None:
        """Insert-or-replace one (farm_id, date) row.

        ``ON CONFLICT (farm_id, date) DO UPDATE`` — every fetch of a
        partial day re-aggregates and overwrites; the previous-day row
        also gets refreshed in case late observations corrected it.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO weather_derived_daily (
                    farm_id, date,
                    temp_min_c, temp_max_c, temp_mean_c,
                    precip_mm_daily, et0_mm_daily,
                    gdd_base10, gdd_base15, gdd_cumulative_base10_season,
                    precip_mm_7d, precip_mm_30d,
                    computed_at
                ) VALUES (
                    :farm_id, :date,
                    :temp_min, :temp_max, :temp_mean,
                    :precip, :et0,
                    :gdd10, :gdd15, :gdd_cum,
                    :p7, :p30,
                    now()
                )
                ON CONFLICT (farm_id, date) DO UPDATE SET
                    temp_min_c = EXCLUDED.temp_min_c,
                    temp_max_c = EXCLUDED.temp_max_c,
                    temp_mean_c = EXCLUDED.temp_mean_c,
                    precip_mm_daily = EXCLUDED.precip_mm_daily,
                    et0_mm_daily = EXCLUDED.et0_mm_daily,
                    gdd_base10 = EXCLUDED.gdd_base10,
                    gdd_base15 = EXCLUDED.gdd_base15,
                    gdd_cumulative_base10_season = EXCLUDED.gdd_cumulative_base10_season,
                    precip_mm_7d = EXCLUDED.precip_mm_7d,
                    precip_mm_30d = EXCLUDED.precip_mm_30d,
                    computed_at = now()
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {
                "farm_id": farm_id,
                "date": date,
                "temp_min": temp_min_c,
                "temp_max": temp_max_c,
                "temp_mean": temp_mean_c,
                "precip": precip_mm_daily,
                "et0": et0_mm_daily,
                "gdd10": gdd_base10,
                "gdd15": gdd_base15,
                "gdd_cum": gdd_cumulative_base10_season,
                "p7": precip_mm_7d,
                "p30": precip_mm_30d,
            },
        )


def _d(v: Decimal | None) -> Decimal | None:
    """No-op coercion; here so the asyncpg → Decimal binding is explicit."""
    return v


def _subscription_to_dict(row: WeatherSubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "block_id": row.block_id,
        "provider_code": row.provider_code,
        "cadence_hours": row.cadence_hours,
        "is_active": row.is_active,
        "last_successful_ingest_at": row.last_successful_ingest_at,
        "last_attempted_at": row.last_attempted_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
