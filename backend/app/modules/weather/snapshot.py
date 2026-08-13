"""Public weather snapshot loader.

Builds a ``WeatherSnapshot`` (from ``app.shared.conditions``) for one
farm at a moment in time. Consumers are the alerts and recommendations
services, which call this once per evaluation pass and embed the
result in the ``ConditionContext`` fed to the evaluator.

This file is part of the weather module's *public* surface — other
modules may import it. The internals (``models``, ``repository``,
``router``, ``schemas``) remain private per the import-linter
contract; this loader uses raw SQL so it doesn't need to import
``WeatherRepository``.

Aggregation choices for forecast windows mirror the agronomic intent
of the agronomy team's Tier-2 rules:

  * ``precipitation_mm_total`` — sum (e.g. "rain ≥ 5mm in next 24h")
  * ``precipitation_probability_pct_max`` — max
  * ``air_temp_c_max`` / ``air_temp_c_min`` — max / min
  * ``et0_mm_total`` — sum (used for irrigation predicates)

Missing data resolves to ``None`` everywhere; the conditions evaluator
treats ``None`` as "predicate does not match" rather than raising,
so partially-loaded blocks don't spuriously fire.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.conditions import WeatherIndexEntry, WeatherRiskEntry, WeatherSnapshot
from app.shared.conditions.context import WaterBalanceEntry

# Provider precedence: when a farm has multiple active providers, prefer
# the operationally-canonical one. Open-Meteo is the only Slice-4
# provider; the list lets future providers slot in by priority.
_PROVIDER_PREFERENCE: tuple[str, ...] = ("open_meteo",)


async def load_snapshot(
    session: AsyncSession,
    *,
    farm_id: UUID,
    now: datetime | None = None,
) -> WeatherSnapshot:
    """Load every scope of a ``WeatherSnapshot`` for ``farm_id``.

    ``session`` must already be bound to the tenant schema (the caller
    sets ``search_path`` per request / per task).

    Returns an empty snapshot (all scopes ``None``) when the farm has
    no provider data yet — the evaluator will branch to ``on_miss`` for
    any predicate that references it.
    """
    if now is None:
        now = datetime.now(UTC)
    provider_code = await _pick_provider(session, farm_id=farm_id)

    latest = await _load_latest_observation(session, farm_id=farm_id, provider_code=provider_code)
    forecast_24h = await _load_forecast_window(
        session, farm_id=farm_id, provider_code=provider_code, now=now, hours=24
    )
    forecast_72h = await _load_forecast_window(
        session, farm_id=farm_id, provider_code=provider_code, now=now, hours=72
    )
    today = now.date()
    derived_today = await _load_derived_for_date(session, farm_id=farm_id, on_date=today)
    derived_yesterday = await _load_derived_for_date(
        session, farm_id=farm_id, on_date=today - timedelta(days=1)
    )

    return WeatherSnapshot(
        latest_observation=latest,
        forecast_24h=forecast_24h,
        forecast_72h=forecast_72h,
        derived_today=derived_today,
        derived_yesterday=derived_yesterday,
    )


async def load_index_snapshot(
    session: AsyncSession,
    *,
    farm_id: UUID,
) -> dict[str, WeatherIndexEntry]:
    """Load the latest projected ``weather_index_daily`` row per index.

    Returns ``{index_code: WeatherIndexEntry}`` carrying the most-recent
    farm-level value + its z-score (``baseline_deviation``). Used by the
    conditions evaluator for the ``weather_index`` source (PR-W7).

    ``session`` must already be bound to the tenant schema. Returns an
    empty dict when the farm has no projected rows yet — every
    ``{source: weather_index}`` predicate then fails closed.

    Observed rows only. The projection now writes days ahead as well
    (``is_forecast``), and "latest" here means *current conditions* — a
    decision tree firing on ``weather_index`` must be judging what the
    farm is living through, not a prediction for four days out. The
    forward-looking view is ``forecast_24h``/``forecast_72h``, which the
    snapshot already carries separately and which trees opt into
    explicitly.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT DISTINCT ON (index_code)
                    index_code, date, value, baseline_deviation
                FROM weather_index_daily
                WHERE farm_id = :farm_id
                  AND NOT is_forecast
                ORDER BY index_code, date DESC
                """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        row["index_code"]: WeatherIndexEntry(
            date=row["date"],
            value=_to_decimal(row["value"]),
            baseline_deviation=_to_decimal(row["baseline_deviation"]),
        )
        for row in rows
    }


async def load_risk_snapshot(
    session: AsyncSession,
    *,
    block_id: UUID,
) -> dict[str, WeatherRiskEntry]:
    """Load the latest ``weather_risk_daily`` row per pathogen for one block.

    Returns ``{risk_code: WeatherRiskEntry}`` carrying the most-recent 0-100
    ``score`` + ``level`` banding. Used by the conditions evaluator for the
    ``weather_risk`` source (PR-R3) — block-keyed, since risk folds in the
    block's crop + growth stage.

    ``session`` must already be bound to the tenant schema. Returns an empty
    dict when the block has no scored rows yet — every
    ``{source: weather_risk}`` predicate then fails closed.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT DISTINCT ON (risk_code)
                    risk_code, date, score, level
                FROM weather_risk_daily
                WHERE block_id = :block_id
                ORDER BY risk_code, date DESC
                """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        row["risk_code"]: WeatherRiskEntry(
            date=row["date"],
            score=row["score"],
            level=row["level"],
        )
        for row in rows
    }


async def load_water_balance_snapshot(
    session: AsyncSession,
    *,
    block_id: UUID,
) -> WaterBalanceEntry | None:
    """Load the latest ``block_water_balance_daily`` row for one block.

    Backs the ``water_balance`` condition source: per-block crop water
    accounting, ``precipitation + irrigation - ETc``. Block-keyed like the risk
    snapshot above, and for the same reason — the crop coefficient and the
    applied irrigation both vary block to block even though the weather driver
    is the farm centroid.

    ``session`` must already be bound to the tenant schema. Returns ``None``
    when the sweep has written nothing for this block (no current crop, or no
    ET0 for the farm that day), so every ``{source: water_balance}`` predicate
    fails closed rather than reading absent bookkeeping as a zero balance.
    """
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT date, balance_mm, etc_mm, et0_mm, kc_used,
                       precip_mm, irrigation_mm, irrigation_logged
                FROM block_water_balance_daily
                WHERE block_id = :block_id
                ORDER BY date DESC
                LIMIT 1
                """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return WaterBalanceEntry(
        date=row["date"],
        balance_mm=row["balance_mm"],
        etc_mm=row["etc_mm"],
        et0_mm=row["et0_mm"],
        kc_used=row["kc_used"],
        precip_mm=row["precip_mm"],
        irrigation_mm=row["irrigation_mm"],
        irrigation_logged=row["irrigation_logged"],
    )


async def _pick_provider(session: AsyncSession, *, farm_id: UUID) -> str | None:
    """Pick the provider this farm has active data for.

    Looks at ``weather_subscriptions`` for any block on the farm; if
    multiple providers, applies ``_PROVIDER_PREFERENCE``. Returns
    ``None`` when no active subscription exists — the loader then
    short-circuits each scope to ``None``.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ws.provider_code
                FROM weather_subscriptions ws
                JOIN blocks b ON b.id = ws.block_id
                WHERE b.farm_id = :farm_id
                  AND ws.is_active = TRUE
                  AND ws.deleted_at IS NULL
                  AND b.deleted_at IS NULL
                """
            ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
            {"farm_id": farm_id},
        )
    ).all()
    available = {r.provider_code for r in rows}
    if not available:
        return None
    for preferred in _PROVIDER_PREFERENCE:
        if preferred in available:
            return preferred
    # Unknown provider — pick the alphabetically-first one for determinism.
    return sorted(available)[0]


async def _load_latest_observation(
    session: AsyncSession,
    *,
    farm_id: UUID,
    provider_code: str | None,
) -> dict[str, Decimal | None] | None:
    if provider_code is None:
        return None
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT time, air_temp_c, humidity_pct, precipitation_mm,
                       wind_speed_m_s, wind_direction_deg, pressure_hpa,
                       solar_radiation_w_m2, cloud_cover_pct, et0_mm
                FROM weather_observations
                WHERE farm_id = :farm_id
                  AND provider_code = :provider_code
                ORDER BY time DESC
                LIMIT 1
                """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id, "provider_code": provider_code},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    out: dict[str, Decimal | None] = {k: _to_decimal(v) for k, v in row.items() if k != "time"}
    return out


async def _load_forecast_window(
    session: AsyncSession,
    *,
    farm_id: UUID,
    provider_code: str | None,
    now: datetime,
    hours: int,
) -> dict[str, Decimal | None] | None:
    """Aggregate the next ``hours`` of forecast into a flat dict.

    Uses the latest issuance per (time) — same DISTINCT-ON pattern as
    ``WeatherRepository.read_latest_forecast`` — so we never mix
    issuances inside one window.
    """
    if provider_code is None:
        return None
    until = now + timedelta(hours=hours)
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                    SUM(precipitation_mm)              AS precipitation_mm_total,
                    MAX(precipitation_probability_pct) AS precipitation_probability_pct_max,
                    MAX(air_temp_c)                    AS air_temp_c_max,
                    MIN(air_temp_c)                    AS air_temp_c_min,
                    AVG(air_temp_c)                    AS air_temp_c_mean,
                    AVG(humidity_pct)                  AS humidity_pct_mean,
                    SUM(et0_mm)                        AS et0_mm_total,
                    MAX(wind_speed_m_s)                AS wind_speed_m_s_max,
                    COUNT(*)                           AS hours_observed
                FROM (
                    SELECT DISTINCT ON (time)
                        time, precipitation_mm, precipitation_probability_pct,
                        air_temp_c, humidity_pct, et0_mm, wind_speed_m_s
                    FROM weather_forecasts
                    WHERE farm_id = :farm_id
                      AND provider_code = :provider_code
                      AND time >= :since
                      AND time < :until
                    ORDER BY time ASC, forecast_issued_at DESC
                ) latest_per_hour
                """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {
                    "farm_id": farm_id,
                    "provider_code": provider_code,
                    "since": now,
                    "until": until,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None or (row.get("hours_observed") or 0) == 0:
        return None
    out: dict[str, Decimal | None] = {
        k: _to_decimal(v) for k, v in row.items() if k != "hours_observed"
    }
    # Surface coverage so a downstream consumer can tell partial windows
    # apart from full ones (e.g. "we only have 8h of forecast, not 24").
    out["hours_observed"] = Decimal(str(row["hours_observed"]))
    return out


async def _load_derived_for_date(
    session: AsyncSession,
    *,
    farm_id: UUID,
    on_date: date,
) -> dict[str, Decimal | None] | None:
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT gdd_base10, gdd_base15, gdd_cumulative_base10_season,
                       et0_mm_daily, precip_mm_daily,
                       precip_mm_7d, precip_mm_30d,
                       temp_min_c, temp_max_c, temp_mean_c
                FROM weather_derived_daily
                WHERE farm_id = :farm_id AND date = :on_date
                """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id, "on_date": on_date},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {k: _to_decimal(v) for k, v in row.items()}


async def load_gdd_since(
    session: AsyncSession,
    *,
    farm_id: UUID,
    since: date,
    until: date,
) -> Decimal | None:
    """Sum daily base-10 GDD for ``farm_id`` over ``[since, until]``.

    Used by the phenology auto-advance task to resolve
    ``gdd_from_planting`` stage windows. Deliberately sums the *daily*
    ``gdd_base10`` rather than reading ``gdd_cumulative_base10_season``:
    the season cumulative resets on the provider's own season anchor,
    which has no relationship to when a given block was planted, so a
    block planted mid-season would read far too high.

    Returns ``None`` when the farm has no derived rows in the window at
    all, which the caller treats as "unknown" and leaves the stage
    alone. A window that exists but is entirely NULL sums to 0, meaning
    "no heat accumulated yet" — a real answer, not a missing one.

    ``session`` must already be bound to the tenant schema.
    """
    row = (
        (
            await session.execute(
                text(
                    """
            SELECT COALESCE(SUM(gdd_base10), 0) AS gdd_total,
                   COUNT(*)                     AS day_count
            FROM weather_derived_daily
            WHERE farm_id = :farm_id
              AND date >= :since
              AND date <= :until
            """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                # Bind real `date` objects, never isoformat strings — asyncpg
                # rejects a str where the column is DATE.
                {"farm_id": farm_id, "since": since, "until": until},
            )
        )
        .mappings()
        .first()
    )
    if row is None or not row["day_count"]:
        return None
    return _to_decimal(row["gdd_total"])


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
