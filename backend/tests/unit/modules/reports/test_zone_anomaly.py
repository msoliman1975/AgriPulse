"""Unit tests for the zone-anomaly report service."""

from __future__ import annotations

from datetime import UTC, datetime
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
class TestZoneAnomalyReport:
    async def test_status_matrix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        b_anom, b_clear, b_insuff, b_nodata, b_nogrid = (uuid4() for _ in range(5))
        now = datetime(2026, 5, 20, tzinfo=UTC)

        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": b_anom, "name": "Anom"},
                {"id": b_clear, "name": "Clear"},
                {"id": b_insuff, "name": "Insuff"},
                {"id": b_nodata, "name": "NoData"},
                {"id": b_nogrid, "name": "NoGrid"},
            ]
        )

        async def fake_stats(*_a: object, **_k: object) -> dict:
            return {
                b_anom: {
                    "scene_time": now,
                    "bmean": Decimal("0.60"),
                    "bstd": Decimal("0.10"),
                    "cell_count": 40,
                    "z_thr": Decimal("1.50"),
                    "flagged": 3,
                    "flagged_area_m2": Decimal("12000"),
                    "worst_z": Decimal("-2.80"),
                },
                b_clear: {
                    "scene_time": now,
                    "bmean": Decimal("0.55"),
                    "bstd": Decimal("0.08"),
                    "cell_count": 50,
                    "z_thr": Decimal("1.50"),
                    "flagged": 0,
                    "flagged_area_m2": Decimal("0"),
                    "worst_z": Decimal("-1.10"),
                },
                b_insuff: {  # too few cells → insufficient regardless of flags
                    "scene_time": now,
                    "bmean": Decimal("0.50"),
                    "bstd": Decimal("0.10"),
                    "cell_count": 5,
                    "z_thr": Decimal("1.50"),
                    "flagged": 2,
                    "flagged_area_m2": Decimal("5000"),
                    "worst_z": Decimal("-3.00"),
                },
            }

        async def fake_grid(*_a: object, **_k: object) -> set:
            # b_nodata has a grid config but no scene; b_nogrid has none.
            return {b_anom, b_clear, b_insuff, b_nodata}

        monkeypatch.setattr(svc_module, "_select_zone_anomaly_stats", fake_stats)
        monkeypatch.setattr(svc_module, "_select_blocks_with_grid", fake_grid)

        out = await s.get_zone_anomaly_report(
            farm_id=farm_id, index_code="ndvi", since=None, until=None
        )

        status = {r.block_name: r.status for r in out.blocks}
        assert status == {
            "Anom": "anomalies",
            "Clear": "clear",
            "Insuff": "insufficient",
            "NoData": "no_data",
            "NoGrid": "no_grid",
        }
        anom = next(r for r in out.blocks if r.block_name == "Anom")
        assert anom.flagged_count == 3
        assert anom.flagged_area_ha == Decimal("1.200")  # 12000 m² → 1.2 ha
        assert anom.worst_z == Decimal("-2.80")
        # insufficient blocks report 0 flagged even though the raw query found some.
        insuff = next(r for r in out.blocks if r.block_name == "Insuff")
        assert insuff.flagged_count == 0

        assert out.blocks[0].block_name == "Anom"  # anomalies sort first
        assert out.summary.block_count == 5
        assert out.summary.blocks_with_grid == 4
        assert out.summary.blocks_with_anomalies == 1
        assert out.summary.total_flagged_cells == 3
        assert out.summary.total_flagged_area_ha == Decimal("1.200")

    async def test_low_std_is_insufficient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        b = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(return_value=[{"id": b, "name": "Uniform"}])  # type: ignore[attr-defined]

        async def fake_stats(*_a: object, **_k: object) -> dict:
            return {
                b: {
                    "scene_time": datetime(2026, 5, 1, tzinfo=UTC),
                    "bmean": Decimal("0.50"),
                    "bstd": Decimal("0.005"),  # below DEFAULT_MIN_STD 0.02
                    "cell_count": 100,
                    "z_thr": Decimal("1.50"),
                    "flagged": 0,
                    "flagged_area_m2": Decimal("0"),
                    "worst_z": Decimal("-0.50"),
                }
            }

        async def fake_grid(*_a: object, **_k: object) -> set:
            return {b}

        monkeypatch.setattr(svc_module, "_select_zone_anomaly_stats", fake_stats)
        monkeypatch.setattr(svc_module, "_select_blocks_with_grid", fake_grid)

        out = await s.get_zone_anomaly_report(
            farm_id=farm_id, index_code="ndvi", since=None, until=None
        )
        assert out.blocks[0].status == "insufficient"
