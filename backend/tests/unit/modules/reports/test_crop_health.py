"""Unit tests for the crop-health report service + helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports import service as svc_module
from app.modules.reports.service import (
    ReportsService,
    _status_from_z,
    _trend_pct,
)


def test_status_from_z_thresholds() -> None:
    assert _status_from_z(None) == "unknown"
    assert _status_from_z(Decimal("0.5")) == "normal"
    assert _status_from_z(Decimal("-1")) == "watch"
    assert _status_from_z(Decimal("-1.5")) == "watch"
    assert _status_from_z(Decimal("-2")) == "stressed"
    assert _status_from_z(Decimal("-3.2")) == "stressed"


def test_trend_pct() -> None:
    assert _trend_pct(first=Decimal("0.5"), last=Decimal("0.6")) == Decimal("20.00")
    assert _trend_pct(first=Decimal("0.6"), last=Decimal("0.3")) == Decimal("-50.00")
    assert _trend_pct(first=None, last=Decimal("0.6")) is None
    assert _trend_pct(first=Decimal("0"), last=Decimal("0.6")) is None


def _service() -> ReportsService:
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    return s


@pytest.mark.asyncio
class TestCropHealthReport:
    async def test_classifies_sorts_and_summarises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        b_stressed, b_normal, b_nodata = uuid4(), uuid4(), uuid4()
        now = datetime(2026, 5, 30, tzinfo=UTC)

        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "North Farm"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": b_normal, "name": "B-Normal"},
                {"id": b_stressed, "name": "A-Stressed"},
                {"id": b_nodata, "name": "C-NoData"},
            ]
        )

        async def fake_stats(*_args: object, **_kwargs: object) -> dict:
            return {
                b_normal: {
                    "scene_count": 4,
                    "min_mean": Decimal("0.50"),
                    "max_mean": Decimal("0.70"),
                    "avg_valid_pct": Decimal("95.5"),
                    "avg_cloud_pct": Decimal("4.0"),
                    "last_time": now,
                    "last_mean": Decimal("0.680"),
                    "last_p10": Decimal("0.60"),
                    "last_p50": Decimal("0.68"),
                    "last_p90": Decimal("0.75"),
                    "last_z": Decimal("0.2"),
                    "first_mean": Decimal("0.60"),
                },
                b_stressed: {
                    "scene_count": 3,
                    "min_mean": Decimal("0.20"),
                    "max_mean": Decimal("0.40"),
                    "avg_valid_pct": Decimal("80.0"),
                    "avg_cloud_pct": Decimal("12.0"),
                    "last_time": now,
                    "last_mean": Decimal("0.250"),
                    "last_p10": Decimal("0.18"),
                    "last_p50": Decimal("0.25"),
                    "last_p90": Decimal("0.33"),
                    "last_z": Decimal("-2.5"),
                    "first_mean": Decimal("0.40"),
                },
            }

        async def fake_crops(*_args: object, **_kwargs: object) -> dict:
            return {b_normal: ("Wheat", "قمح")}

        monkeypatch.setattr(svc_module, "_select_crop_health_stats", fake_stats)
        monkeypatch.setattr(svc_module, "_select_block_current_crops", fake_crops)

        out = await s.get_crop_health_report(
            farm_id=farm_id, index_code="ndvi", since=None, until=None
        )

        assert out.farm_name == "North Farm"
        # Attention ordering (same as insights): stressed, watch, unknown,
        # then normal — so the no-data block sorts above the healthy one.
        assert [r.block_name for r in out.blocks] == ["A-Stressed", "C-NoData", "B-Normal"]
        statuses = {r.block_name: r.status for r in out.blocks}
        assert statuses == {
            "A-Stressed": "stressed",
            "B-Normal": "normal",
            "C-NoData": "unknown",
        }
        # Crop name attached to the block that has one.
        normal_row = next(r for r in out.blocks if r.block_name == "B-Normal")
        assert normal_row.crop_name_en == "Wheat"
        assert normal_row.trend_pct == Decimal("13.33")  # (0.68-0.60)/0.60

        # No-data block carries nulls + zero scene count.
        nodata = next(r for r in out.blocks if r.block_name == "C-NoData")
        assert nodata.last_value is None
        assert nodata.scene_count == 0

        assert out.summary.block_count == 3
        assert out.summary.with_data_count == 2
        assert out.summary.stressed == 1
        assert out.summary.normal == 1
        assert out.summary.unknown == 1
        # avg of 0.680 + 0.250 = 0.465
        assert out.summary.avg_last_value == Decimal("0.465")

    async def test_empty_farm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Empty"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        async def empty(*_args: object, **_kwargs: object) -> dict:
            return {}

        monkeypatch.setattr(svc_module, "_select_crop_health_stats", empty)
        monkeypatch.setattr(svc_module, "_select_block_current_crops", empty)

        out = await s.get_crop_health_report(
            farm_id=farm_id, index_code="ndvi", since=None, until=None
        )
        assert out.blocks == []
        assert out.summary.block_count == 0
        assert out.summary.avg_last_value is None
