"""The weather lane: read-only SQL for a pipeline with no scenes and no pixels.

Weather is farm-scoped, so the block picker means nothing here and the API
says so rather than silently ignoring it. The spine is:

    subscription → fetch attempt → hourly observation
                 → derived daily → weather_index_daily → baseline → consumers

Two analogies make the imagery lane's vocabulary carry over:

* a **fetch attempt** is the scene — the unit of "did the provider give us
  anything";
* **hour coverage** is the valid-pixel percentage. It is the single most
  useful weather diagnostic and is invisible everywhere else in the product:
  a day derived from nine hourly rows produces a confident-looking ET₀ that
  is wrong, and nothing downstream knows.

Same interpolation rule as the imagery repository — `weather_observations` is
a hypertable, so time bounds are formatted into the SQL rather than bound.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.repository import _d, _ts

# Below this many hourly rows, a derived day is built on too little to trust.
# 18 of 24 is deliberately generous: the derivation has no coverage floor at
# all today, so the first useful thing Observer can do is name the days that
# would fail one.
COVERAGE_WARN_HOURS = 18


class ObserverWeatherRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def stage_counts(
        self,
        *,
        farm_id: UUID,
        window_from: datetime,
        window_to: datetime,
    ) -> dict[str, Any]:
        """Counts for the weather ribbon, in one pass.

        `hours_expected` is the window's length in hours rather than a count
        of anything stored — the point is to compare what arrived against what
        should have, and a denominator derived from the data itself could
        never show a gap.
        """
        sql = f"""
            SELECT
              (SELECT count(*) FROM weather_ingestion_attempts a
                WHERE a.farm_id = :fid
                  AND a.started_at >= {_ts(window_from)}
                  AND a.started_at < {_ts(window_to)}) AS attempts,
              (SELECT count(*) FROM weather_ingestion_attempts a
                WHERE a.farm_id = :fid
                  AND a.status = 'succeeded'
                  AND a.started_at >= {_ts(window_from)}
                  AND a.started_at < {_ts(window_to)}) AS attempts_ok,
              (SELECT count(*) FROM weather_observations o
                WHERE o.farm_id = :fid
                  AND o.time >= {_ts(window_from)}
                  AND o.time < {_ts(window_to)}) AS observations,
              (SELECT count(*) FROM weather_derived_daily d
                WHERE d.farm_id = :fid
                  AND d.date >= CAST({_ts(window_from)} AS date)
                  AND d.date < CAST({_ts(window_to)} AS date)) AS derived_days,
              (SELECT count(*) FROM weather_index_daily i
                WHERE i.farm_id = :fid
                  AND i.date >= CAST({_ts(window_from)} AS date)
                  AND i.date < CAST({_ts(window_to)} AS date)) AS index_rows,
              (SELECT count(DISTINCT i.index_code) FROM weather_index_daily i
                WHERE i.farm_id = :fid
                  AND i.date >= CAST({_ts(window_from)} AS date)
                  AND i.date < CAST({_ts(window_to)} AS date)) AS index_codes,
              (SELECT count(DISTINCT b.index_code) FROM weather_index_baselines b
                WHERE b.farm_id = :fid) AS baseline_codes,
              (SELECT count(*) FROM public.weather_indices_catalog c
                WHERE c.is_active = TRUE AND c.deleted_at IS NULL) AS catalog_codes
        """  # noqa: S608
        row = (await self._s.execute(text(sql), {"fid": str(farm_id)})).mappings().one()
        out = {k: int(v) for k, v in row.items()}
        out["hours_expected"] = int((window_to - window_from).total_seconds() // 3600)
        out["days_expected"] = max(out["hours_expected"] // 24, 0)
        return out

    async def hour_coverage(
        self,
        *,
        farm_id: UUID,
        window_from: datetime,
        window_to: datetime,
        limit_days: int = 120,
    ) -> list[dict[str, Any]]:
        """Hours present per day, with the derived row's presence alongside.

        Reported together on purpose: a day with 9 of 24 hours *and* a derived
        row is the dangerous case — the number exists, looks authoritative and
        was computed from a third of the day.
        """
        sql = f"""
            SELECT
              d.day::date AS day,
              d.hours,
              (SELECT count(*) > 0 FROM weather_derived_daily wd
                WHERE wd.farm_id = :fid AND wd.date = d.day::date) AS has_derived,
              (SELECT count(*) FROM weather_index_daily wi
                WHERE wi.farm_id = :fid AND wi.date = d.day::date) AS index_rows
              FROM (
                SELECT date_trunc('day', o.time) AS day,
                       count(DISTINCT date_trunc('hour', o.time)) AS hours
                  FROM weather_observations o
                 WHERE o.farm_id = :fid
                   AND o.time >= {_ts(window_from)}
                   AND o.time < {_ts(window_to)}
                 GROUP BY 1
              ) d
             ORDER BY d.day DESC
             LIMIT :limit
        """  # noqa: S608
        rows = (
            await self._s.execute(text(sql), {"fid": str(farm_id), "limit": limit_days})
        ).mappings()
        return [dict(r) for r in rows]

    async def recent_attempts(
        self,
        *,
        farm_id: UUID,
        window_from: datetime,
        window_to: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch attempts — the weather lane's answer to the scene table."""
        sql = f"""
            SELECT a.id, a.provider_code, a.status, a.rows_ingested,
                   a.error_code, a.error_message, a.started_at,
                   a.completed_at, a.duration_ms, a.block_id
              FROM weather_ingestion_attempts a
             WHERE a.farm_id = :fid
               AND a.started_at >= {_ts(window_from)}
               AND a.started_at < {_ts(window_to)}
             ORDER BY a.started_at DESC
             LIMIT :limit
        """
        rows = (await self._s.execute(text(sql), {"fid": str(farm_id), "limit": limit})).mappings()
        return [dict(r) for r in rows]

    async def index_days(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        window_from: datetime,
        window_to: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        sql = f"""
            SELECT i.date, i.index_code, i.value, i.value_min, i.value_max,
                   i.value_aux, i.baseline_deviation, i.computed_at,
                   (SELECT count(DISTINCT date_trunc('hour', o.time))
                      FROM weather_observations o
                     WHERE o.farm_id = i.farm_id
                       AND o.time >= {_ts(window_from)}
                       AND o.time < {_ts(window_to)}
                       AND o.time >= (i.date AT TIME ZONE 'UTC')
                       AND o.time < ((i.date + 1) AT TIME ZONE 'UTC')) AS source_hours
              FROM weather_index_daily i
             WHERE i.farm_id = :fid
               AND i.index_code = :code
               AND i.date >= CAST({_ts(window_from)} AS date)
               AND i.date < CAST({_ts(window_to)} AS date)
             ORDER BY i.date DESC
             LIMIT :limit
        """  # noqa: S608
        rows = (
            await self._s.execute(
                text(sql), {"fid": str(farm_id), "code": index_code, "limit": limit}
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def explain_index_day(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        day: date,
    ) -> dict[str, Any] | None:
        """Everything that produced one daily index value.

        The weather counterpart of the pixel inspector: the hourly rows that
        fed it, the derived-daily intermediate, the catalog definition, and
        the coverage that qualifies all of it.
        """
        index_row = (
            (
                await self._s.execute(
                    text(
                        """
                        SELECT i.date, i.index_code, i.value, i.value_min,
                               i.value_max, i.value_aux, i.baseline_deviation,
                               i.computed_at
                          FROM weather_index_daily i
                         WHERE i.farm_id = :fid AND i.index_code = :code
                           AND i.date = :day
                        """
                    ),
                    {"fid": str(farm_id), "code": index_code, "day": day},
                )
            )
            .mappings()
            .first()
        )
        if index_row is None:
            return None

        derived = (
            (
                await self._s.execute(
                    text(
                        """
                        SELECT gdd_base10, gdd_base15,
                               gdd_cumulative_base10_season,
                               et0_mm_daily, precip_mm_daily, precip_mm_7d,
                               precip_mm_30d, temp_min_c, temp_max_c,
                               temp_mean_c, computed_at
                          FROM weather_derived_daily
                         WHERE farm_id = :fid AND date = :day
                        """
                    ),
                    {"fid": str(farm_id), "day": day},
                )
            )
            .mappings()
            .first()
        )

        hourly = (
            await self._s.execute(
                text(
                    f"""
                    SELECT o.time, o.provider_code, o.air_temp_c, o.humidity_pct,
                           o.precipitation_mm, o.wind_speed_m_s,
                           o.solar_radiation_w_m2, o.et0_mm
                      FROM weather_observations o
                     WHERE o.farm_id = :fid
                       AND o.time >= ({_d(day)} AT TIME ZONE 'UTC')
                       AND o.time < (({_d(day)} + 1) AT TIME ZONE 'UTC')
                     ORDER BY o.time
                    """
                ),
                {"fid": str(farm_id)},
            )
        ).mappings()
        hourly_rows = [dict(r) for r in hourly]

        catalog = (
            (
                await self._s.execute(
                    text(
                        """
                        SELECT code, name_en, name_ar, unit, description_en,
                               source_kind, value_min, value_max
                          FROM public.weather_indices_catalog
                         WHERE code = :code
                        """
                    ),
                    {"code": index_code},
                )
            )
            .mappings()
            .first()
        )

        # Distinct hours, not row count: a provider that delivers two rows
        # for one hour must not read as better coverage than one that
        # delivers one.
        hours_present = len(
            {r["time"].replace(minute=0, second=0, microsecond=0) for r in hourly_rows}
        )
        return {
            "index": dict(index_row),
            "derived": dict(derived) if derived else None,
            "hourly": hourly_rows,
            "catalog": dict(catalog) if catalog else None,
            "hours_present": hours_present,
            "hours_expected": 24,
            # The qualifier that belongs next to every number above. A day
            # built from a third of its hours is not comparable to a full one,
            # and nothing downstream currently distinguishes them.
            "coverage_sufficient": hours_present >= COVERAGE_WARN_HOURS,
        }

    async def farm_has_weather(self, farm_id: UUID) -> bool:
        row = (
            await self._s.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM weather_subscriptions w
                          JOIN blocks b ON b.id = w.block_id
                         WHERE b.farm_id = :fid
                           AND w.deleted_at IS NULL
                    )
                    """
                ),
                {"fid": str(farm_id)},
            )
        ).first()
        return bool(row and row[0])
