"""Pure bridge: weather day-aggregates -> a trailing RiskWeatherDay window.

Turns the per-local-date ``DailyDerived`` (temp/precip) + ``RadiationWindDay``
(humidity) maps the weather aggregation already produces (see
``index_projection.aggregate_radiation_wind_day`` + ``derivations``) into the
trailing window the risk models in ``weather.risk`` consume. Side-effect-free
and unit-tested, mirroring ``index_projection.py`` — the risk task is the only
caller and stays thin.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as date_type
from datetime import timedelta

from app.modules.weather.derivations import DailyDerived
from app.modules.weather.index_projection import RadiationWindDay
from app.modules.weather.risk.types import RiskWeatherDay


def build_risk_window(
    daily: Mapping[date_type, DailyDerived],
    radwind: Mapping[date_type, RadiationWindDay],
    *,
    as_of: date_type,
    window_days: int,
) -> list[RiskWeatherDay]:
    """Assemble the inclusive ``[as_of - window_days + 1, as_of]`` risk window.

    A date with neither a daily nor a radiation/wind aggregate is omitted (a
    gap day the models simply don't see); a date present in only one map keeps
    the available signals and leaves the rest ``None`` (the models degrade per
    field). Result is ascending by date.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    out: list[RiskWeatherDay] = []
    for offset in range(window_days):
        d = as_of - timedelta(days=offset)
        day = daily.get(d)
        rw = radwind.get(d)
        if day is None and rw is None:
            continue
        out.append(
            RiskWeatherDay(
                date=d,
                temp_min_c=day.temp_min_c if day is not None else None,
                temp_max_c=day.temp_max_c if day is not None else None,
                temp_mean_c=day.temp_mean_c if day is not None else None,
                humidity_mean_pct=rw.humidity_mean_pct if rw is not None else None,
                precip_mm=day.precip_mm_daily if day is not None else None,
            )
        )
    out.sort(key=lambda r: r.date)
    return out


__all__ = ["build_risk_window"]
