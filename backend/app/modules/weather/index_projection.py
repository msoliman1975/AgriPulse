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
  * ``leaf_wetness``       — hours at/above 90% RH (NHRH90 model)
  * ``frost_risk``         — 0-100 closeness to frost, from the daily minimum
  * ``heat_stress``        — Thom THI from the daily maximum + mean humidity

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

# --- leaf wetness ----------------------------------------------------------
# The NHRH90 model: leaf wetness duration is the count of hours at or above
# 90% relative humidity. Sentelhas et al. (2008), Agric. For. Meteorol. 148(3)
# benchmarked it across multiple climates and found it matches the accuracy of
# energy-balance models in most cases — which is what makes it worth using
# when there is no wetness sensor in the field.
_LEAF_WETNESS_RH_PCT = Decimal(90)

# --- frost risk ------------------------------------------------------------
# Scored 0-100 off the daily minimum rather than reported as a probability:
# a real probability needs dew point and a local model, and we have neither.
# The band is the common operational warning threshold — advisories fire at a
# forecast minimum of ~3°C, and freezing damage is certain at or below 0°C.
# Linear between the two, which is a defensible reading of "how close is this
# night to frost" without implying precision the inputs cannot support.
_FROST_CERTAIN_C = Decimal(0)
_FROST_WATCH_C = Decimal(4)

# --- heat stress -----------------------------------------------------------
# Thom's (1959) Temperature-Humidity Index. Carried with a caveat the catalog
# description repeats: THI comes from livestock science, and its direct
# agricultural validity is weaker than the crop-specific critical-temperature-
# at-flowering model. It is used here because it is citable, computable from
# what we already store, and farm-level — the critical-threshold model needs
# per-crop phenology, which is block-level and therefore belongs with the
# block-keyed water-balance work rather than in a farm-wide index.
#
# Driven by the daily MAXIMUM rather than the mean: heat stress is a daytime
# extreme, and a day that peaks at 40°C is not made safe by a cool night.
_THI_C1 = Decimal("1.8")
_THI_C2 = Decimal(32)
_THI_C3 = Decimal("0.55")
_THI_C4 = Decimal("0.0055")
_THI_C5 = Decimal(26)


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
    # Hours in the day at or above `_LEAF_WETNESS_RH_PCT`. Defaulted so the
    # dataclass stays constructible from older call sites, and None-vs-0 is a
    # real distinction here: None means no humidity readings at all, 0 means a
    # measured dry day. A disease model must not treat those the same.
    leaf_wetness_hours: Decimal | None = None
    # How many hourly samples the day actually carried, so a partial day can
    # be recognised as partial rather than read as a short one.
    humidity_sample_hours: int = 0


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

    # Leaf wetness: one hour credited per hourly sample at or above the RH
    # threshold. `None` only when the day carried no humidity reading at all —
    # a day of measured dry air is 0 hours, which is a finding rather than a
    # gap, and a disease model must not treat the two the same.
    wet_hours = Decimal(sum(1 for h in hums if h >= _LEAF_WETNESS_RH_PCT)) if hums else None

    return RadiationWindDay(
        radiation_mean_w_m2=rad_mean.quantize(_Q) if rad_mean is not None else None,
        radiation_sum_mj_m2=rad_sum_mj.quantize(_Q) if rad_sum_mj is not None else None,
        wind_mean_m_s=wind_mean.quantize(_Q) if wind_mean is not None else None,
        wind_max_m_s=max(speeds).quantize(_Q) if speeds else None,
        wind_dir_mean_deg=_vector_mean_direction(dirs),
        humidity_mean_pct=(_mean(hums).quantize(_Q) if hums else None),  # type: ignore[union-attr]
        leaf_wetness_hours=wet_hours,
        humidity_sample_hours=len(hums),
    )


# --- Frost + heat scoring --------------------------------------------------


def frost_risk_score(temp_min_c: Decimal) -> Decimal:
    """0-100 closeness-to-frost from a day's minimum air temperature.

    100 at or below freezing, 0 at or above the watch threshold, linear in
    between. Deliberately NOT called a probability: a real frost probability
    needs dew point and a locally fitted model, and we have neither, so a
    number presented as a probability here would be false precision.

    The value is most useful on forecast days — it is the only signal in the
    system that fires before any damage has happened.
    """
    if temp_min_c <= _FROST_CERTAIN_C:
        return Decimal(100)
    if temp_min_c >= _FROST_WATCH_C:
        return Decimal(0)
    span = _FROST_WATCH_C - _FROST_CERTAIN_C
    return ((_FROST_WATCH_C - temp_min_c) / span * Decimal(100)).quantize(_Q)


def temperature_humidity_index(temp_c: Decimal, humidity_pct: Decimal) -> Decimal:
    """Thom (1959) THI: ``(1.8T + 32) - (0.55 - 0.0055·RH)(1.8T - 26)``.

    Returned on its native (Fahrenheit-derived) scale rather than rescaled,
    so published banding tables still apply to it unchanged.
    """
    f = _THI_C1 * temp_c + _THI_C2
    correction = (_THI_C3 - _THI_C4 * humidity_pct) * (_THI_C1 * temp_c - _THI_C5)
    return (f - correction).quantize(_Q)


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

    out.extend(project_hazard_indices(day, radwind))
    return out


def project_hazard_indices(
    day: DailyDerived | None,
    radwind: RadiationWindDay | None,
) -> list[ProjectedIndex]:
    """The three gap-audit indices: leaf wetness, frost risk, heat stress.

    Split out of :func:`project_indices` to keep that function's branch count
    honest, but they also belong together: unlike the eight above — which
    report a measured quantity — these three each answer "is this day
    dangerous, and how", and each is defined by a threshold rather than by a
    unit of measurement.
    """
    out: list[ProjectedIndex] = []

    # leaf_wetness — hours at/above 90% RH (NHRH90). The single strongest
    # predictor of fungal infection, because spores need free water to
    # germinate, and the input the three pathogen models were built without.
    if radwind is not None and radwind.leaf_wetness_hours is not None:
        out.append(
            ProjectedIndex(
                index_code="leaf_wetness",
                value=radwind.leaf_wetness_hours.quantize(_Q),
                value_aux={
                    "rh_threshold_pct": str(_LEAF_WETNESS_RH_PCT),
                    "sample_hours": str(radwind.humidity_sample_hours),
                },
            )
        )

    # frost_risk — 0-100 from the day's minimum temperature.
    if day is not None and day.temp_min_c is not None:
        out.append(
            ProjectedIndex(
                index_code="frost_risk",
                value=frost_risk_score(day.temp_min_c),
                value_aux={
                    "temp_min_c": str(day.temp_min_c),
                    "certain_at_c": str(_FROST_CERTAIN_C),
                    "watch_at_c": str(_FROST_WATCH_C),
                },
            )
        )

    # heat_stress — THI from the day's maximum temperature and mean humidity.
    # Needs both, so a day with temperature but no humidity emits no row
    # rather than a THI computed against an assumed humidity.
    temp_max = day.temp_max_c if day is not None else None
    humidity = radwind.humidity_mean_pct if radwind is not None else None
    if temp_max is not None and humidity is not None:
        out.append(
            ProjectedIndex(
                index_code="heat_stress",
                value=temperature_humidity_index(temp_max, humidity),
                value_aux={
                    "temp_max_c": str(temp_max),
                    "humidity_mean_pct": str(humidity),
                },
            )
        )

    return out
