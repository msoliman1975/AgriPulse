"""Unit tests for the disease/pest pressure report service (PR-R5)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports import service as svc_module
from app.modules.reports.service import ReportsService


def _service() -> ReportsService:
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    return s


@pytest.mark.asyncio
class TestWeatherRiskPressureReport:
    async def test_rows_summary_and_worst_first_sort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        b_hi, b_lo = uuid4(), uuid4()

        s = _service()
        s._farms.get_farm_by_id = AsyncMock(  # type: ignore[attr-defined]
            return_value={"id": farm_id, "name": "Suez"}
        )
        s._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": b_hi, "name": "North"},
                {"id": b_lo, "name": "South"},
            ]
        )

        async def fake_select(*_a: object, **_k: object) -> list[dict]:
            return [
                # A low-pressure row (should sort last).
                {
                    "block_id": b_lo,
                    "risk_code": "fruit_fly",
                    "days_observed": 14,
                    "peak_score": 30,
                    "mean_score": 18,
                    "days_high": 0,
                    "days_moderate": 0,
                    "latest_level": "low",
                    "latest_score": 12,
                    "latest_date": date(2026, 6, 20),
                },
                # A high-pressure row (should sort first).
                {
                    "block_id": b_hi,
                    "risk_code": "powdery_mildew",
                    "days_observed": 14,
                    "peak_score": 100,
                    "mean_score": 80,
                    "days_high": 6,
                    "days_moderate": 4,
                    "latest_level": "high",
                    "latest_score": 95,
                    "latest_date": date(2026, 6, 20),
                },
            ]

        monkeypatch.setattr(svc_module, "_select_weather_risk_pressure", fake_select)

        out = await s.get_weather_risk_pressure_report(farm_id=farm_id, since=None, until=None)

        # Worst-first: the high powdery-mildew row leads.
        assert [r.risk_code for r in out.rows] == ["powdery_mildew", "fruit_fly"]
        assert out.rows[0].block_name == "North"
        assert out.rows[0].peak_score == 100
        assert out.rows[0].days_high == 6
        # Summary roll-up: two blocks observed, two pathogens, one at risk
        # (only the high block), six high-days total.
        assert out.summary.block_count == 2
        assert out.summary.pathogen_count == 2
        assert out.summary.blocks_at_risk == 1
        assert out.summary.total_high_days == 6
        assert out.summary.row_count == 2
        assert out.farm_name == "Suez"

    async def test_empty_window_yields_no_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(  # type: ignore[attr-defined]
            return_value={"id": farm_id, "name": "F"}
        )
        s._farms.list_blocks = AsyncMock(return_value=[{"id": uuid4(), "name": "B"}])  # type: ignore[attr-defined]

        async def fake_select(*_a: object, **_k: object) -> list[dict]:
            return []

        monkeypatch.setattr(svc_module, "_select_weather_risk_pressure", fake_select)

        out = await s.get_weather_risk_pressure_report(farm_id=farm_id, since=None, until=None)
        assert out.rows == []
        assert out.summary.block_count == 0
        assert out.summary.blocks_at_risk == 0
        assert out.summary.row_count == 0
