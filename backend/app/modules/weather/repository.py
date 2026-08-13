"""Async DB access for the weather module. Internal to the module.

Reads/writes for `weather_subscriptions`, `weather_observations`, and
`weather_forecasts`. Hypertable inserts use ``ON CONFLICT DO NOTHING``
on the unique key so re-fetching the same issuance is idempotent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, bindparam, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import CursorResult
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

    # ---- Attempt log (PR-IH1) -----------------------------------------

    async def open_attempt(
        self,
        *,
        attempt_id: UUID,
        subscription_id: UUID,
        # None for a farm-scoped attempt: one provider call covers the whole
        # farm, so there is no block it belongs to.
        block_id: UUID | None,
        farm_id: UUID,
        provider_code: str,
        started_at: datetime,
    ) -> None:
        """Insert a 'running' attempt row. Paired with `close_attempt`."""
        await self._session.execute(
            text(
                """
                INSERT INTO weather_ingestion_attempts
                (id, subscription_id, block_id, farm_id, provider_code,
                 started_at, status)
                VALUES (:id, :subscription_id, :block_id, :farm_id,
                        :provider_code, :started_at, 'running')
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("subscription_id", type_=PG_UUID(as_uuid=True)),
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": attempt_id,
                "subscription_id": subscription_id,
                "block_id": block_id,
                "farm_id": farm_id,
                "provider_code": provider_code,
                "started_at": started_at,
            },
        )

    async def close_attempt(
        self,
        *,
        attempt_id: UUID,
        completed_at: datetime,
        status: str,
        rows_ingested: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Transition a 'running' attempt to a terminal state."""
        # Truncate provider messages — they can be HTML error pages.
        if error_message is not None and len(error_message) > 1000:
            error_message = error_message[:997] + "..."
        await self._session.execute(
            text(
                """
                UPDATE weather_ingestion_attempts
                SET completed_at = :completed_at,
                    status = :status,
                    rows_ingested = :rows_ingested,
                    error_code = :error_code,
                    error_message = :error_message
                WHERE id = :id
                """
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {
                "id": attempt_id,
                "completed_at": completed_at,
                "status": status,
                "rows_ingested": rows_ingested,
                "error_code": error_code,
                "error_message": error_message,
            },
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
        """Return (farm_id, provider_code) pairs that are overdue a fetch.

        Beat-sweep entry point. Reads the FARM subscriptions, and falls back to
        the per-block rows for any (farm, provider) that has no farm row yet —
        migration 0077 creates one per active block combination, but a block
        subscribed after that migration ran would otherwise stop being fetched
        entirely. The fallback keeps every farm covered during the cutover and
        costs one extra scan of a small table.

        Dedup is done in SQL: many subscriptions on one farm collapse to a
        single fetch per cycle, which is all the provider call ever was.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT farm_id, provider_code FROM (
                        SELECT f.farm_id, f.provider_code, f.last_attempted_at,
                               f.cadence_hours
                        FROM weather_farm_subscriptions f
                        WHERE f.is_active = TRUE AND f.deleted_at IS NULL

                        UNION ALL

                        SELECT b.farm_id, s.provider_code,
                               max(s.last_attempted_at) AS last_attempted_at,
                               min(s.cadence_hours) AS cadence_hours
                        FROM weather_subscriptions s
                        JOIN blocks b ON b.id = s.block_id
                        WHERE s.is_active = TRUE
                          AND s.deleted_at IS NULL
                          AND b.deleted_at IS NULL
                          AND NOT EXISTS (
                              SELECT 1 FROM weather_farm_subscriptions f2
                              WHERE f2.farm_id = b.farm_id
                                AND f2.provider_code = s.provider_code
                                AND f2.is_active AND f2.deleted_at IS NULL
                          )
                        GROUP BY b.farm_id, s.provider_code
                    ) due
                    WHERE last_attempted_at IS NULL
                       OR last_attempted_at <
                          (:now - make_interval(
                               hours => COALESCE(cadence_hours, :default_cadence)
                          ))
                    """
                ).bindparams(now=now, default_cadence=default_cadence_hours)
            )
        ).all()
        return tuple((row.farm_id, row.provider_code) for row in rows)

    async def get_farm_subscription(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
    ) -> dict[str, Any] | None:
        """The farm-level subscription for this provider, if there is one."""
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT * FROM weather_farm_subscriptions
                        WHERE farm_id = :farm AND provider_code = :provider
                          AND is_active AND deleted_at IS NULL
                        """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id, "provider": provider_code},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def touch_farm_subscription_attempt(
        self,
        *,
        subscription_id: UUID,
        attempted_at: datetime,
        success: bool,
    ) -> None:
        """Heartbeat the farm subscription; advance the watermark on success."""
        sets = ["last_attempted_at = :at", "updated_at = now()"]
        if success:
            sets.append("last_successful_ingest_at = :at")
        await self._session.execute(
            text(
                f"UPDATE weather_farm_subscriptions SET {', '.join(sets)} "
                "WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": subscription_id, "at": attempted_at},
        )

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
        provider_code: str | None,
        since: datetime,
        until: datetime,
    ) -> tuple[dict[str, Any], ...]:
        """Latest-issuance forecast hours in [since, until). Time-ordered ascending.

        ``DISTINCT ON (time)`` collapses the keep-all-issuances history
        (per the Slice-4 lock) to one row per hour, picking whichever
        ``forecast_issued_at`` is most recent.

        ``provider_code`` pins one provider; None spans them all, which is
        what the index projection wants — it mirrors ``read_observations``,
        whose window is likewise provider-agnostic, so the observed and
        forecast halves of a series are drawn from the same set of
        providers. With one provider configured the two are identical; the
        DISTINCT ON still yields one row per hour either way (latest
        issuance wins regardless of which provider produced it).
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
                        SELECT DISTINCT ON (time)
                               time, forecast_issued_at, farm_id, provider_code,
                               air_temp_c, humidity_pct,
                               precipitation_mm, precipitation_probability_pct,
                               wind_speed_m_s, solar_radiation_w_m2, et0_mm
                        FROM weather_forecasts
                        WHERE {" AND ".join(clauses)}
                        ORDER BY time ASC, forecast_issued_at DESC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    params,
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

    # ---- weather-index projection (PR-W2) -----------------------------

    async def read_index_baseline(
        self, *, farm_id: UUID, index_code: str, day_of_year: int
    ) -> dict[str, Any] | None:
        """The (farm, index, DOY) climatology baseline row, or None.

        Read at projection time to populate
        ``weather_index_daily.baseline_deviation``. Returns None until the
        PR-W3 sweep has computed a baseline for this DOY.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT baseline_mean, baseline_std, sample_count
                        FROM weather_index_baselines
                        WHERE farm_id = :farm_id
                          AND index_code = :index_code
                          AND day_of_year = :doy
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "index_code": index_code, "doy": day_of_year},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def upsert_weather_index_daily(
        self,
        *,
        farm_id: UUID,
        date: date_type,
        index_code: str,
        value: Decimal | None,
        value_min: Decimal | None,
        value_max: Decimal | None,
        value_aux: dict[str, Any],
        baseline_deviation: Decimal | None,
        is_forecast: bool = False,
    ) -> None:
        """Insert-or-replace one (farm_id, date, index_code) projection row.

        ``ON CONFLICT DO UPDATE`` — re-deriving a partial / corrected day
        overwrites in place, matching ``upsert_derived_daily``.

        ``is_forecast`` is overwritten like every other column, which is
        what makes the forecast→observed handover free: yesterday's
        prediction for today is replaced by today's observed projection
        and the flag flips back to False on the same key.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO weather_index_daily (
                    farm_id, date, index_code,
                    value, value_min, value_max, value_aux,
                    baseline_deviation, is_forecast, computed_at
                ) VALUES (
                    :farm_id, :date, :index_code,
                    :value, :value_min, :value_max, CAST(:value_aux AS jsonb),
                    :baseline_deviation, :is_forecast, now()
                )
                ON CONFLICT (farm_id, date, index_code) DO UPDATE SET
                    value = EXCLUDED.value,
                    value_min = EXCLUDED.value_min,
                    value_max = EXCLUDED.value_max,
                    value_aux = EXCLUDED.value_aux,
                    baseline_deviation = EXCLUDED.baseline_deviation,
                    is_forecast = EXCLUDED.is_forecast,
                    computed_at = now()
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {
                "farm_id": farm_id,
                "date": date,
                "index_code": index_code,
                "value": value,
                "value_min": value_min,
                "value_max": value_max,
                "value_aux": json.dumps(value_aux),
                "baseline_deviation": baseline_deviation,
                "is_forecast": is_forecast,
            },
        )

    async def delete_forecast_index_rows_after(self, *, farm_id: UUID, after: date_type) -> int:
        """Drop every forecast projection row strictly after ``after``.

        Run immediately before writing a fresh forecast set. Without it a
        shrinking horizon leaves orphans: if the provider returns 5 days
        today and 2 tomorrow, days 3-5 keep yesterday's prediction forever
        and the chart shows a stale tail that never self-corrects.

        Observed rows are untouched — the ``is_forecast`` predicate is the
        whole safety of this delete.
        """
        result = await self._session.execute(
            text(
                """
                DELETE FROM weather_index_daily
                WHERE farm_id = :farm_id
                  AND is_forecast
                  AND date > :after
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {"farm_id": farm_id, "after": after},
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    # ---- weather-index climatology baselines (PR-W3) ------------------

    async def list_distinct_weather_index_pairs(self) -> tuple[tuple[UUID, str], ...]:
        """Every (farm_id, index_code) pair with at least one valued row.

        Drives the per-tenant baseline sweep — one recompute per pair.
        """
        rows = (
            await self._session.execute(
                text(
                    "SELECT DISTINCT farm_id, index_code FROM weather_index_daily "
                    "WHERE value IS NOT NULL"
                )
            )
        ).all()
        return tuple((r[0], r[1]) for r in rows)

    async def read_weather_index_history(
        self, *, farm_id: UUID, index_code: str
    ) -> tuple[dict[str, Any], ...]:
        """All valued OBSERVED (date, value) rows for one (farm, index).
        Date ascending.

        This is the climatology's sample set, so forecast rows are excluded
        without exception — letting predictions into the baseline would
        make each index partly its own normal, and the z-score that the
        anomaly chip and the compare view are built on would quietly
        shrink toward zero.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT date, value
                        FROM weather_index_daily
                        WHERE farm_id = :farm_id
                          AND index_code = :index_code
                          AND value IS NOT NULL
                          AND NOT is_forecast
                        ORDER BY date ASC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "index_code": index_code},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def upsert_weather_index_baseline(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        day_of_year: int,
        baseline_mean: Decimal,
        baseline_std: Decimal,
        sample_count: int,
        window_days: int,
        years_observed: int,
    ) -> None:
        """Insert-or-replace one (farm, index, day_of_year) baseline."""
        await self._session.execute(
            text(
                """
                INSERT INTO weather_index_baselines (
                    farm_id, index_code, day_of_year,
                    baseline_mean, baseline_std, sample_count,
                    window_days, years_observed, computed_at
                ) VALUES (
                    :farm_id, :index_code, :doy,
                    :mean, :std, :sample_count,
                    :window_days, :years_observed, now()
                )
                ON CONFLICT (farm_id, index_code, day_of_year) DO UPDATE SET
                    baseline_mean = EXCLUDED.baseline_mean,
                    baseline_std = EXCLUDED.baseline_std,
                    sample_count = EXCLUDED.sample_count,
                    window_days = EXCLUDED.window_days,
                    years_observed = EXCLUDED.years_observed,
                    computed_at = now()
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {
                "farm_id": farm_id,
                "index_code": index_code,
                "doy": day_of_year,
                "mean": baseline_mean,
                "std": baseline_std,
                "sample_count": sample_count,
                "window_days": window_days,
                "years_observed": years_observed,
            },
        )

    async def recompute_weather_index_deviations(self, *, farm_id: UUID, index_code: str) -> int:
        """Re-derive `baseline_deviation` on every row of one (farm, index).

        Sets the z-score `(value - baseline_mean) / baseline_std` against
        the matching day-of-year baseline, or NULL when no baseline exists
        for that DOY or its std is zero. A LEFT JOIN over the index rows
        (not the baselines) guarantees rows whose baseline disappeared are
        reset to NULL rather than left stale. Returns rows touched.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE weather_index_daily d
                SET baseline_deviation = sub.dev
                FROM (
                    SELECT r.farm_id, r.date, r.index_code,
                           CASE
                               WHEN b.baseline_std IS NOT NULL AND b.baseline_std > 0
                               THEN round(
                                   (r.value - b.baseline_mean) / b.baseline_std, 4
                               )
                               ELSE NULL
                           END AS dev
                    FROM weather_index_daily r
                    LEFT JOIN weather_index_baselines b
                        ON b.farm_id = r.farm_id
                        AND b.index_code = r.index_code
                        AND b.day_of_year = EXTRACT(DOY FROM r.date)::int
                    WHERE r.farm_id = :farm_id
                      AND r.index_code = :index_code
                      AND r.value IS NOT NULL
                ) sub
                WHERE d.farm_id = sub.farm_id
                  AND d.date = sub.date
                  AND d.index_code = sub.index_code
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {"farm_id": farm_id, "index_code": index_code},
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    # ---- weather-index read surface (PR-W4) ---------------------------

    async def read_weather_index_timeseries(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        since: date_type | None,
        until: date_type | None,
    ) -> tuple[dict[str, Any], ...]:
        """One (farm, index) series joined to its day-of-year climatology.

        ``[since, until)`` date filter when provided. Each row carries the
        stored z-score plus the matching baseline mean/std for the band.
        """
        clauses = ["d.farm_id = :farm_id", "d.index_code = :index_code"]
        params: dict[str, Any] = {"farm_id": farm_id, "index_code": index_code}
        if since is not None:
            clauses.append("d.date >= :since")
            params["since"] = since
        if until is not None:
            clauses.append("d.date < :until")
            params["until"] = until
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT d.date, d.value, d.value_min, d.value_max,
                               d.value_aux, d.is_forecast,
                               d.baseline_deviation AS zscore,
                               b.baseline_mean, b.baseline_std
                        FROM weather_index_daily d
                        LEFT JOIN weather_index_baselines b
                            ON b.farm_id = d.farm_id
                            AND b.index_code = d.index_code
                            AND b.day_of_year = EXTRACT(DOY FROM d.date)::int
                        WHERE {" AND ".join(clauses)}
                        ORDER BY d.date ASC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def read_weather_index_recent(
        self, *, farm_id: UUID, since: date_type
    ) -> tuple[dict[str, Any], ...]:
        """Valued rows for all indices on/after ``since`` — drives the
        farm summary (latest value + 7-day trend). Ordered for grouping.

        Forecast rows are excluded outright: the summary strip is the
        "what is it right now" reading, and since the projection started
        writing days ahead, ``series[-1]`` would otherwise be a prediction
        several days out labelled as the current value.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT date, index_code, value, baseline_deviation AS zscore
                        FROM weather_index_daily
                        WHERE farm_id = :farm_id
                          AND value IS NOT NULL
                          AND NOT is_forecast
                          AND date >= :since
                        ORDER BY index_code ASC, date ASC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "since": since},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    # ---- Weather risk (Phase 2) ---------------------------------------

    async def list_active_blocks_with_current_crop(self) -> tuple[dict[str, Any], ...]:
        """``(block_id, farm_id, crop_path, growth_stage, canopy_size_class)``
        for every current, live ``block_crops`` row with a crop assigned.

        Raw SQL over the tenant tables on purpose: the weather module may not
        import ``farms.repository``/``farms.models`` (import-linter), and this
        avoids it. Mirrors the eligibility filter of farms' phenology-advance
        query, minus the stage lock — a manually-set ``growth_stage`` is still
        a valid risk input, only auto-advance honours the lock.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT bc.block_id, b.farm_id, bc.crop_path,
                               bc.growth_stage, bc.canopy_size_class
                        FROM block_crops bc
                        JOIN blocks b ON b.id = bc.block_id
                        WHERE bc.is_current = TRUE
                          AND bc.deleted_at IS NULL
                          AND bc.crop_path <> ''
                          AND bc.status NOT IN ('completed', 'aborted')
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def upsert_weather_risk_daily(
        self,
        *,
        block_id: UUID,
        date: date_type,
        risk_code: str,
        score: int,
        level: str,
        inputs: dict[str, Any],
    ) -> None:
        """Insert-or-replace one ``(block_id, date, risk_code)`` risk row."""
        await self._session.execute(
            text(
                """
                INSERT INTO weather_risk_daily (
                    block_id, date, risk_code, score, level, inputs, computed_at
                ) VALUES (
                    :block_id, :date, :risk_code, :score, :level,
                    CAST(:inputs AS jsonb), now()
                )
                ON CONFLICT (block_id, date, risk_code) DO UPDATE SET
                    score = EXCLUDED.score,
                    level = EXCLUDED.level,
                    inputs = EXCLUDED.inputs,
                    computed_at = now()
                """
            ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
            {
                "block_id": block_id,
                "date": date,
                "risk_code": risk_code,
                "score": score,
                "level": level,
                "inputs": json.dumps(inputs),
            },
        )

    async def read_weather_risk_timeseries(
        self,
        *,
        farm_id: UUID,
        block_id: UUID,
        risk_code: str,
        since: date_type | None,
        until: date_type | None,
    ) -> tuple[dict[str, Any], ...]:
        """One ``(block, risk_code)`` score series, scoped to its farm.

        The ``blocks`` join enforces farm ownership so a caller authorised on
        ``farm_id`` cannot read a block in another farm (an empty series if the
        block is not in the farm). ``[since, until)`` when provided.
        """
        clauses = [
            "r.block_id = :block_id",
            "r.risk_code = :risk_code",
            "b.farm_id = :farm_id",
        ]
        params: dict[str, Any] = {
            "block_id": block_id,
            "risk_code": risk_code,
            "farm_id": farm_id,
        }
        if since is not None:
            clauses.append("r.date >= :since")
            params["since"] = since
        if until is not None:
            clauses.append("r.date < :until")
            params["until"] = until
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT r.date, r.risk_code, r.score, r.level, r.inputs
                        FROM weather_risk_daily r
                        JOIN blocks b ON b.id = r.block_id
                        WHERE {" AND ".join(clauses)}
                        ORDER BY r.date ASC
                        """
                    ).bindparams(
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def read_weather_risk_summary(self, *, farm_id: UUID) -> tuple[dict[str, Any], ...]:
        """Latest score per ``(block, risk_code)`` across a farm — map overlay.

        ``DISTINCT ON`` keeps the most recent row per block+pathogen.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT DISTINCT ON (r.block_id, r.risk_code)
                               r.block_id, r.risk_code, r.date, r.score, r.level
                        FROM weather_risk_daily r
                        JOIN blocks b ON b.id = r.block_id
                        WHERE b.farm_id = :farm_id
                        ORDER BY r.block_id, r.risk_code, r.date DESC
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)


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
