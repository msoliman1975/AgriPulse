"""Pure functions that derive daily agronomic signals from hourly weather.

The Celery task in ``tasks.py`` is the only caller — these helpers are
side-effect-free so they can be exercised in unit tests without a DB.

Signals computed here (all six match
``public.weather_derived_signals_catalog`` rows seeded in PR-A):

  * ``temp_min_c``, ``temp_max_c``, ``temp_mean_c``  — daily min/max/mean
  * ``precip_mm_daily``                              — daily precipitation total
  * ``et0_mm_daily``                                 — daily ET₀ total
  * ``gdd_base10``, ``gdd_base15``                   — Growing Degree Days
  * ``gdd_cumulative_base10_season``                 — running sum since season start
  * ``precip_mm_7d``, ``precip_mm_30d``              — rolling rainfall windows

ET₀ source: we sum the hourly ``et0_mm`` already populated by the
provider. Open-Meteo returns FAO-56 Penman-Monteith hourly values in
``et0_fao_evapotranspiration``; the Slice-4 lock-in keeps P-M as the
canonical formula but does not require us to recompute it when the
provider already supplies it. If a future provider lacks hourly ET₀,
add a Hargreaves-from-min/max-temp fallback here.

GDD bases: data_model § 8.4 stores fixed ``gdd_base10`` and
``gdd_base15`` columns. Per-crop base temperatures (corn 8°C, wheat
0°C, etc.) are out of scope for PR-C — consumers pick the closer of
the two pre-computed values, or revisit when the recommendations
module needs more.

Season cumulative: schema says "reset by event"; without the events
module wired up yet, we treat "season" as **calendar year** so the
column has a well-defined meaning. The reset-by-event path is a
follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class HourlyRow:
    """Slim view of one ``weather_observations`` row.

    Defined here rather than reusing the provider DTO so derivations
    don't depend on the provider package.
    """

    time: datetime
    air_temp_c: Decimal | None = None
    precipitation_mm: Decimal | None = None
    et0_mm: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DailyDerived:
    """Computed `weather_derived_daily` row, minus the cumulative + rolling
    fields which need cross-day context."""

    date: date_type
    temp_min_c: Decimal | None
    temp_max_c: Decimal | None
    temp_mean_c: Decimal | None
    precip_mm_daily: Decimal | None
    et0_mm_daily: Decimal | None
    gdd_base10: Decimal | None
    gdd_base15: Decimal | None


# --- Bucketing -------------------------------------------------------------


def bucket_hourly_by_local_date(
    rows: Iterable[HourlyRow], tz: ZoneInfo
) -> dict[date_type, list[HourlyRow]]:
    """Group hourly observations by their date in the given timezone.

    Times in the input are tz-aware UTC (TIMESTAMPTZ); the date we
    bucket on is the local-tz calendar date so that "today" matches
    what the user sees on the farm.
    """
    buckets: dict[date_type, list[HourlyRow]] = {}
    for row in rows:
        local = row.time.astimezone(tz)
        buckets.setdefault(local.date(), []).append(row)
    return buckets


# --- Per-day aggregation ---------------------------------------------------


def aggregate_one_day(rows: Sequence[HourlyRow], on_date: date_type) -> DailyDerived:
    """Aggregate one local-day's hourly rows into per-day signals.

    Empty input returns a row with all-None signals (so the caller can
    still upsert a placeholder for that day if desired). Numeric types
    stay ``Decimal`` end-to-end to preserve hypertable precision.
    """
    temps = [r.air_temp_c for r in rows if r.air_temp_c is not None]
    precs = [r.precipitation_mm for r in rows if r.precipitation_mm is not None]
    et0s = [r.et0_mm for r in rows if r.et0_mm is not None]

    temp_min = min(temps) if temps else None
    temp_max = max(temps) if temps else None
    temp_mean = (
        (sum(temps, start=Decimal(0)) / Decimal(len(temps))).quantize(Decimal("0.01"))
        if temps
        else None
    )
    precip_total = sum(precs, start=Decimal(0)) if precs else None
    et0_total = sum(et0s, start=Decimal(0)) if et0s else None

    if temp_mean is not None:
        gdd_base10 = max(Decimal(0), temp_mean - Decimal(10))
        gdd_base15 = max(Decimal(0), temp_mean - Decimal(15))
    else:
        gdd_base10 = None
        gdd_base15 = None

    return DailyDerived(
        date=on_date,
        temp_min_c=temp_min,
        temp_max_c=temp_max,
        temp_mean_c=temp_mean,
        precip_mm_daily=(
            precip_total.quantize(Decimal("0.01")) if precip_total is not None else None
        ),
        et0_mm_daily=et0_total.quantize(Decimal("0.01")) if et0_total is not None else None,
        gdd_base10=gdd_base10.quantize(Decimal("0.01")) if gdd_base10 is not None else None,
        gdd_base15=gdd_base15.quantize(Decimal("0.01")) if gdd_base15 is not None else None,
    )


# --- Rolling + cumulative --------------------------------------------------


def cumulative_gdd_base10_for_season(
    by_day: dict[date_type, DailyDerived], on_date: date_type
) -> Decimal | None:
    """Sum ``gdd_base10`` from Jan 1 of ``on_date.year`` through ``on_date``.

    "Season" = calendar year for now (see module docstring). Returns
    None if no contributing day in the season has a non-null value.
    """
    season_start = date_type(on_date.year, 1, 1)
    total = Decimal(0)
    seen = False
    cursor = season_start
    while cursor <= on_date:
        row = by_day.get(cursor)
        if row is not None and row.gdd_base10 is not None:
            total += row.gdd_base10
            seen = True
        cursor += timedelta(days=1)
    return total.quantize(Decimal("0.01")) if seen else None


def rolling_precip_total(
    by_day: dict[date_type, DailyDerived], on_date: date_type, window_days: int
) -> Decimal | None:
    """Sum ``precip_mm_daily`` for the inclusive window ending on ``on_date``.

    Returns None only if every day in the window has a null total —
    a single observed zero counts as data.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    total = Decimal(0)
    seen = False
    for offset in range(window_days):
        d = on_date - timedelta(days=offset)
        row = by_day.get(d)
        if row is not None and row.precip_mm_daily is not None:
            total += row.precip_mm_daily
            seen = True
    return total.quantize(Decimal("0.01")) if seen else None
