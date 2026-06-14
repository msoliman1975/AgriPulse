"""Unit tests for the water-balance report service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
class TestWaterBalanceReport:
    async def test_aggregates_and_adherence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        b_active, b_quiet = uuid4(), uuid4()

        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": b_quiet, "name": "Quiet"},
                {"id": b_active, "name": "Active"},
            ]
        )

        async def fake_weather(*_a: object, **_k: object) -> dict:
            return {"days": 30, "et0_total": Decimal("150.00"), "precip_total": Decimal("12.00")}

        async def fake_blocks(*_a: object, **_k: object) -> dict:
            return {
                b_active: {
                    "scheduled_count": 10,
                    "applied_count": 8,
                    "skipped_count": 1,
                    "pending_count": 1,
                    "recommended_mm_total": Decimal("100.00"),
                    "applied_mm_total": Decimal("90.00"),
                    "last_scheduled_for": date(2026, 5, 27),
                }
            }

        monkeypatch.setattr(svc_module, "_select_water_balance_weather", fake_weather)
        monkeypatch.setattr(svc_module, "_select_water_balance_blocks", fake_blocks)

        out = await s.get_water_balance_report(farm_id=farm_id, since=None, until=None)

        assert out.weather.days_with_data == 30
        assert out.weather.et0_mm_total == Decimal("150.00")
        assert out.weather.et0_mm_avg_daily == Decimal("5.00")  # 150 / 30

        # Active block sorts first (more scheduling activity).
        assert out.blocks[0].block_name == "Active"
        active = out.blocks[0]
        assert active.adherence_pct == Decimal("90.0")  # 90 / 100
        assert active.applied_count == 8

        quiet = out.blocks[1]
        assert quiet.scheduled_count == 0
        assert quiet.recommended_mm_total is None
        assert quiet.adherence_pct is None

        assert out.summary.blocks_with_schedules == 1
        assert out.summary.recommended_mm_total == Decimal("100.00")
        assert out.summary.applied_mm_total == Decimal("90.00")
        assert out.summary.applied_count == 8
        assert out.summary.skipped_count == 1
        assert out.summary.pending_count == 1

    async def test_no_weather_no_schedules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(return_value=[{"id": uuid4(), "name": "B"}])  # type: ignore[attr-defined]

        async def fake_weather(*_a: object, **_k: object) -> dict:
            return {"days": 0, "et0_total": None, "precip_total": None}

        async def fake_blocks(*_a: object, **_k: object) -> dict:
            return {}

        monkeypatch.setattr(svc_module, "_select_water_balance_weather", fake_weather)
        monkeypatch.setattr(svc_module, "_select_water_balance_blocks", fake_blocks)

        out = await s.get_water_balance_report(farm_id=farm_id, since=None, until=None)
        assert out.weather.days_with_data == 0
        assert out.weather.et0_mm_avg_daily is None
        assert out.summary.blocks_with_schedules == 0
        assert out.summary.recommended_mm_total is None
