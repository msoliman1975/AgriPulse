"""Unit tests for the weather-summary report service + stats roll-up."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports import service as svc_module
from app.modules.reports.service import ReportsService, _weather_stats


def _row(d: int, *, tmin=None, tmax=None, tmean=None, precip=None, et0=None, gdd=None, cum=None):
    return {
        "date": date(2026, 5, d),
        "temp_min_c": tmin,
        "temp_max_c": tmax,
        "temp_mean_c": tmean,
        "precip_mm_daily": precip,
        "et0_mm_daily": et0,
        "gdd_base10": gdd,
        "gdd_cumulative_base10_season": cum,
    }


def D(v: str) -> Decimal:
    return Decimal(v)


def test_weather_stats_rollup() -> None:
    rows = [
        _row(1, tmin=D("8"), tmax=D("22"), tmean=D("15"), precip=D("0"), et0=D("4.0"), gdd=D("5"), cum=D("100")),
        _row(2, tmin=D("6"), tmax=D("25"), tmean=D("16"), precip=D("3.5"), et0=D("5.0"), gdd=D("6"), cum=D("106")),
        _row(3, tmin=D("9"), tmax=D("20"), tmean=D("14"), precip=D("0"), et0=D("3.0"), gdd=D("4"), cum=D("110")),
    ]
    s = _weather_stats(rows)
    assert s.days_with_data == 3
    assert s.temp_min_c == D("6")  # coldest min
    assert s.temp_max_c == D("25")  # warmest max
    assert s.temp_mean_c == D("15.00")  # (15+16+14)/3
    assert s.precip_mm_total == D("3.50")
    assert s.rain_days == 1  # only day 2 had rain
    assert s.et0_mm_total == D("12.00")
    assert s.et0_mm_avg_daily == D("4.00")
    assert s.gdd_base10_total == D("15.00")
    assert s.gdd_cumulative_season == D("110.00")  # latest cumulative


def test_weather_stats_empty_and_nulls() -> None:
    assert _weather_stats([]).days_with_data == 0
    assert _weather_stats([]).temp_min_c is None
    # Rows present but all metrics null → counts the day, no metric values.
    nulls = _weather_stats([_row(1)])
    assert nulls.days_with_data == 1
    assert nulls.et0_mm_total is None
    assert nulls.gdd_cumulative_season is None


@pytest.mark.asyncio
async def test_weather_report_assembles(monkeypatch: pytest.MonkeyPatch) -> None:
    farm_id = uuid4()
    crop_id = uuid4()
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]

    async def fake_daily(*_a: object, **_k: object) -> list:
        return [_row(1, tmean=D("15"), et0=D("4.0"), cum=D("100"))]

    async def fake_crops(*_a: object, **_k: object) -> list:
        return [
            {
                "crop_id": crop_id,
                "name_en": "Wheat",
                "name_ar": "قمح",
                "gdd_base_temp_c": D("4.5"),
                "default_growing_season_days": 150,
                "block_count": 3,
            }
        ]

    monkeypatch.setattr(svc_module, "_select_weather_daily", fake_daily)
    monkeypatch.setattr(svc_module, "_select_weather_crop_context", fake_crops)

    out = await s.get_weather_summary_report(farm_id=farm_id, since=None, until=None)
    assert out.farm_name == "F"
    assert len(out.daily) == 1
    assert out.stats.days_with_data == 1
    assert out.crops[0].name_en == "Wheat"
    assert out.crops[0].default_growing_season_days == 150
