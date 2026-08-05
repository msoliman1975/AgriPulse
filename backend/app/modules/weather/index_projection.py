"""Pure functions that project hourly/daily weather into the 8 first-class
weather indices (catalog seeded in public migrations 0037 + 0049).

Side-effect-free so the derivation task and unit tests share the code.
The task in ``tasks.py`` is the only caller: it aggregates a window of
hourly observations + the per-day ``DailyDerived`` rows it already
computes, then calls :func:`project_indices` per target day and upserts
each result into ``weather_index_daily``.

Index → source mapping (codes match ``public.weather_indices_catalog``):

  * ``temperature``        — mean / min / max from ``DailyDerived``
  * ``radiation``          — daily mean W/m² (+ daily insolation MJ/m²)
  * ``wind``               — mean / max speed (+ vector-mean direction)
  * ``humidity``           — daily mean relative humidity %
  * ``rainfall``           — daily precip (+ rolling 7-/30-day totals)
  * ``evapotranspiration`` — daily ET₀ total
  * ``evaporation_coeff``  — soil dry-down: rolling Σ(ET₀ - precip), 30d
  * ``rain_et_balance``    — daily water balance precip - ET₀ (flux)

``evaporation_coeff`` is the *redefined* index (a cumulative deficit
STOCK), not the degenerate ``epan = et0/0.7`` proxy — see
docs/proposals/weather-indices-first-class.md §1. V1 uses a plain
window sum (no ordering / no field-capacity bucket); the proper
soil-water-balance model is Phase-2.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.modules.weather.derivations import DailyDerived, rolling_precip_total

# Headline-value quantum for the index rows (Numeric(10,3)).
_Q = Decimal("0.001")
# Seconds per hourly sample — turns instantaneous W/m² into J/m² per hour.
_SECONDS_PER_HOUR = Decimal(3600)
_J_PER_MJ = Decimal(1_000_000)
_DRY_DOWN_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class IndexHourlyRow:
    """Slim view of one ``weather_observations`` row for radiation + wind.

    Temperature / precip / ET₀ already flow through ``DailyDerived``;
    these are the fields the GDD/ET derivation path doesn't carry.
    """

    time: datetime
    solar_radiation_w_m2: Decimal | None = None
    wind_speed_m_s: Decimal | None = None
    wind_direction_deg: Decimal | None = None
    humidity_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RadiationWindDay:
    """Per-day radiation + wind aggregates (one farm-local date)."""

    radiation_mean_w_m2: Decimal | None
    radiation_sum_mj_m2: Decimal | None
    wind_mean_m_s: Decimal | None
    wind_max_m_s: Decimal | None
    wind_dir_mean_deg: Decimal | None
    humidity_mean_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ProjectedIndex:
    """One ``weather_index_daily`` row, pre-z-score.

    ``value_aux`` holds Decimals serialised as strings (Decimal→string
    JSON convention) so JSONB round-trips without precision loss.
    """

    index_code: str
    value: Decimal
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    value_aux: dict[str, str] = field(default_factory=dict)


# --- Bucketing -------------------------------------------------------------


def bucket_index_hourly_by_local_date(
    rows: Iterable[IndexHourlyRow], tz: ZoneInfo
) -> dict[date_type, list[IndexHourlyRow]]:
    """Group radiation/wind hourly rows by their local-tz calendar date."""
    buckets: dict[date_type, list[IndexHourlyRow]] = {}
    for row in rows:
        local = row.time.astimezone(tz)
        buckets.setdefault(local.date(), []).append(row)
    return buckets


# --- Radiation + wind day aggregation --------------------------------------


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _vector_mean_direction(dirs: Sequence[Decimal]) -> Decimal | None:
    """Circular (unit-vector) mean of compass bearings in degrees [0,360).

    Unweighted — a plain mean of unit direction vectors. Returns None for
    no input or a near-zero resultant (directions cancel out, so the mean
    bearing is undefined).
    """
    if not dirs:
        return None
    sin_sum = sum(math.sin(math.radians(float(d))) for d in dirs)
    cos_sum = sum(math.cos(math.radians(float(d))) for d in dirs)
    if abs(sin_sum) < 1e-9 and abs(cos_sum) < 1e-9:
        return None
    angle = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    return Decimal(str(angle)).quantize(Decimal("0.1"))


def aggregate_radiation_wind_day(rows: Sequence[IndexHourlyRow]) -> RadiationWindDay:
    """Aggregate one local-day's radiation + wind hourly rows.

    Empty / all-null input yields all-None fields, so the caller can
    still decide whether to emit a row.
    """
    rad = [r.solar_radiation_w_m2 for r in rows if r.solar_radiation_w_m2 is not None]
    speeds = [r.wind_speed_m_s for r in rows if r.wind_speed_m_s is not None]
    dirs = [r.wind_direction_deg for r in rows if r.wind_direction_deg is not None]
    hums = [r.humidity_pct for r in rows if r.humidity_pct is not None]

    rad_mean = _mean(rad)
    # Insolation: each hourly W/m² sample held for 3600s → J/m²; sum → MJ/m².
    rad_sum_mj = (sum(rad, start=Decimal(0)) * _SECONDS_PER_HOUR / _J_PER_MJ) if rad else None
    wind_mean = _mean(speeds)

    return RadiationWindDay(
        radiation_mean_w_m2=rad_mean.quantize(_Q) if rad_mean is not None else None,
        radiation_sum_mj_m2=rad_sum_mj.quantize(_Q) if rad_sum_mj is not None else None,
        wind_mean_m_s=wind_mean.quantize(_Q) if wind_mean is not None else None,
        wind_max_m_s=max(speeds).quantize(_Q) if speeds else None,
        wind_dir_mean_deg=_vector_mean_direction(dirs),
        humidity_mean_pct=(_mean(hums).quantize(_Q) if hums else None),  # type: ignore[union-attr]
    )


# --- Dry-down (soil water deficit STOCK) -----------------------------------


def dry_down_total(
    daily: dict[date_type, DailyDerived],
    on_date: date_type,
    *,
    window_days: int = _DRY_DOWN_WINDOW_DAYS,
) -> Decimal | None:
    """Rolling Σ(ET₀ - precip) for the inclusive window ending on ``on_date``.

    A day contributes only if it has an ET₀ value (demand is the driver);
    a missing precip counts as zero rainfall. Positive = net drying
    (soil deficit), negative = net surplus over the window. Returns None
    when no day in the window has ET₀ data.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    total = Decimal(0)
    seen = False
    for offset in range(window_days):
        row = daily.get(on_date - timedelta(days=offset))
        if row is None or row.et0_mm_daily is None:
            continue
        precip = row.precip_mm_daily if row.precip_mm_daily is not None else Decimal(0)
        total += row.et0_mm_daily - precip
        seen = True
    return total.quantize(_Q) if seen else None


# --- Projection ------------------------------------------------------------


def project_indices(
    on_date: date_type,
    daily: dict[date_type, DailyDerived],
    radwind: RadiationWindDay | None,
    *,
    dry_down_window_days: int = _DRY_DOWN_WINDOW_DAYS,
) -> list[ProjectedIndex]:
    """Project all available weather indices for ``on_date`` into rows.

    Only indices with a defined headline ``value`` are returned — a
    fully-undefined index (no source data) produces no row, so the
    timeseries simply has a gap rather than a null clutter row.
    """
    day = daily.get(on_date)
    out: list[ProjectedIndex] = []

    # temperature — mean headline, min/max spread.
    if day is not None and day.temp_mean_c is not None:
        out.append(
            ProjectedIndex(
                index_code="temperature",
                value=day.temp_mean_c.quantize(_Q),
                value_min=day.temp_min_c.quantize(_Q) if day.temp_min_c is not None else None,
                value_max=day.temp_max_c.quantize(_Q) if day.temp_max_c is not None else None,
            )
        )

    # radiation — daily mean W/m², daily insolation MJ/m² in aux.
    if radwind is not None and radwind.radiation_mean_w_m2 is not None:
        aux: dict[str, str] = {}
        if radwind.radiation_sum_mj_m2 is not None:
            aux["daily_insolation_mj_m2"] = str(radwind.radiation_sum_mj_m2)
        out.append(
            ProjectedIndex(
                index_code="radiation",
                value=radwind.radiation_mean_w_m2,
                value_aux=aux,
            )
        )

    # wind — mean speed headline, max gust, vector-mean direction in aux.
    if radwind is not None and radwind.wind_mean_m_s is not None:
        aux = {}
        if radwind.wind_dir_mean_deg is not None:
            aux["mean_direction_deg"] = str(radwind.wind_dir_mean_deg)
        out.append(
            ProjectedIndex(
                index_code="wind",
                value=radwind.wind_mean_m_s,
                value_max=radwind.wind_max_m_s,
                value_aux=aux,
            )
        )

    # humidity — daily mean relative humidity %. Already aggregated for the
    # risk models; emitting it here makes it a chartable first-class index.
    if radwind is not None and radwind.humidity_mean_pct is not None:
        out.append(
            ProjectedIndex(
                index_code="humidity",
                value=radwind.humidity_mean_pct,
            )
        )

    # rainfall — daily total headline, rolling 7-/30-day totals in aux.
    if day is not None and day.precip_mm_daily is not None:
        aux = {}
        p7 = rolling_precip_total(daily, on_date, window_days=7)
        p30 = rolling_precip_total(daily, on_date, window_days=30)
        if p7 is not None:
            aux["precip_mm_7d"] = str(p7)
        if p30 is not None:
            aux["precip_mm_30d"] = str(p30)
        out.append(
            ProjectedIndex(
                index_code="rainfall",
                value=day.precip_mm_daily.quantize(_Q),
                value_aux=aux,
            )
        )

    # evapotranspiration — daily ET₀ total.
    if day is not None and day.et0_mm_daily is not None:
        out.append(
            ProjectedIndex(
                index_code="evapotranspiration",
                value=day.et0_mm_daily.quantize(_Q),
            )
        )

    # evaporation_coeff — soil dry-down stock Σ(ET₀ - precip) over window.
    dry = dry_down_total(daily, on_date, window_days=dry_down_window_days)
    if dry is not None:
        out.append(
            ProjectedIndex(
                index_code="evaporation_coeff",
                value=dry,
                value_aux={"window_days": str(dry_down_window_days)},
            )
        )

    # rain_et_balance — daily flux precip - ET₀ (missing precip → 0 rain).
    if day is not None and day.et0_mm_daily is not None:
        precip = day.precip_mm_daily if day.precip_mm_daily is not None else Decimal(0)
        out.append(
            ProjectedIndex(
                index_code="rain_et_balance",
                value=(precip - day.et0_mm_daily).quantize(_Q),
            )
        )

    return out
