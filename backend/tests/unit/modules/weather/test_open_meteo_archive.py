"""Unit tests for OpenMeteoProvider.fetch_archive.

The HTTP layer (`_get_with_retry`) is stubbed so the test exercises pure
parsing + request-shaping without a network call or respx mock: it asserts
the archive endpoint is hit with the archive variable set (no forecast-only
`precipitation_probability`) and that hourly rows map onto HourlyObservation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.weather.providers.open_meteo import OpenMeteoProvider
from app.modules.weather.providers.protocol import HourlyObservation

_ARCHIVE_BODY: dict[str, Any] = {
    "hourly": {
        "time": ["2025-07-01T00:00", "2025-07-01T01:00"],
        "temperature_2m": [28.4, 27.9],
        "relative_humidity_2m": [40, 42],
        "precipitation": [0.0, 0.0],
        "wind_speed_10m": [3.1, 2.8],
        "wind_direction_10m": [120, 130],
        "pressure_msl": [1012.0, 1011.5],
        "shortwave_radiation": [0.0, 0.0],
        "cloud_cover": [5, 10],
        "et0_fao_evapotranspiration": [0.01, 0.0],
    }
}


@pytest.mark.asyncio
async def test_fetch_archive_parses_hourly_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenMeteoProvider()
    captured: dict[str, Any] = {}

    async def fake_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["params"] = params
        return _ARCHIVE_BODY

    monkeypatch.setattr(provider, "_get_with_retry", fake_get)

    observations = await provider.fetch_archive(
        latitude=30.6,
        longitude=32.64,
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 1),
    )

    # Targets the archive endpoint with the inclusive date range.
    assert captured["url"] == provider._archive_url
    assert captured["params"]["start_date"] == "2025-07-01"
    assert captured["params"]["end_date"] == "2025-07-01"
    # Forecast-only variable must not be requested from the archive.
    assert "precipitation_probability" not in captured["params"]["hourly"]

    assert len(observations) == 2
    assert all(isinstance(o, HourlyObservation) for o in observations)
    first = observations[0]
    assert first.air_temp_c == Decimal("28.4")
    assert first.humidity_pct == Decimal("40")
    assert first.wind_direction_deg == Decimal("120")
    assert first.cloud_cover_pct == Decimal("5")


@pytest.mark.asyncio
async def test_fetch_archive_empty_body_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenMeteoProvider()

    async def fake_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return {"hourly": {"time": []}}

    monkeypatch.setattr(provider, "_get_with_retry", fake_get)

    observations = await provider.fetch_archive(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 2),
    )
    assert observations == ()
