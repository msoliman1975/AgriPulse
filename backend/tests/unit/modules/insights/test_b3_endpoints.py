"""B.3 unit tests — annotations + alert-trend orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.insights.service import InsightsService


def _impl_with_mocked_repos() -> InsightsService:
    svc = InsightsService.__new__(InsightsService)
    svc._session = AsyncMock()  # type: ignore[attr-defined]
    svc._farms = AsyncMock()  # type: ignore[attr-defined]
    svc._indices = AsyncMock()  # type: ignore[attr-defined]
    svc._alerts = AsyncMock()  # type: ignore[attr-defined]
    return svc


@pytest.mark.asyncio
class TestAnnotations:
    async def test_filters_to_window(self) -> None:
        farm_id = uuid4()
        block_id = uuid4()
        now = datetime.now(UTC)
        old = now - timedelta(days=30)
        recent = now - timedelta(days=1)

        svc = _impl_with_mocked_repos()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[{"id": block_id}])  # type: ignore[attr-defined]
        svc._alerts.list_alerts = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "created_at": old,
                    "severity": "critical",
                    "diagnosis_en": "Old alert",
                    "rule_code": "ndvi_drop",
                },
                {
                    "created_at": recent,
                    "severity": "warning",
                    "diagnosis_en": "Recent alert",
                    "rule_code": "et_high",
                },
            ]
        )

        # Window starts 7 days back — `old` should be excluded.
        out = await svc.get_farm_annotations(
            farm_id=farm_id,
            since=now - timedelta(days=7),
            until=now,
        )
        labels = [a.label for a in out.annotations]
        assert labels == ["Recent alert"]
        assert out.annotations[0].severity == "warning"
        assert out.annotations[0].block_id == block_id

    async def test_unbounded_window_returns_all(self) -> None:
        farm_id = uuid4()
        block_id = uuid4()
        svc = _impl_with_mocked_repos()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[{"id": block_id}])  # type: ignore[attr-defined]
        svc._alerts.list_alerts = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "created_at": datetime.now(UTC) - timedelta(days=100),
                    "severity": "info",
                    "diagnosis_en": "Old",
                    "rule_code": "x",
                },
            ]
        )
        out = await svc.get_farm_annotations(farm_id=farm_id, since=None, until=None)
        assert len(out.annotations) == 1

    async def test_falls_back_to_rule_code_when_diagnosis_missing(self) -> None:
        farm_id = uuid4()
        block_id = uuid4()
        svc = _impl_with_mocked_repos()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[{"id": block_id}])  # type: ignore[attr-defined]
        svc._alerts.list_alerts = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "created_at": datetime.now(UTC),
                    "severity": "critical",
                    "diagnosis_en": None,
                    "rule_code": "ndvi_drop",
                },
            ]
        )
        out = await svc.get_farm_annotations(farm_id=farm_id, since=None, until=None)
        assert out.annotations[0].label == "ndvi_drop"


@pytest.mark.asyncio
class TestAlertTrend:
    async def test_open_count_walks_resolution_window(self) -> None:
        # 3-day window. Alert A opens day -3, resolves day -1 → open
        # on day -3, -2; closed by day -1, 0. Alert B opens day -2,
        # never resolves → open on -2, -1, 0.
        farm_id = uuid4()
        block_id = uuid4()
        now = datetime.now(UTC)

        svc = _impl_with_mocked_repos()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[{"id": block_id}])  # type: ignore[attr-defined]
        svc._alerts.list_alerts = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "created_at": now - timedelta(days=3),
                    "resolved_at": now - timedelta(days=1, hours=20),
                    "severity": "critical",
                },
                {
                    "created_at": now - timedelta(days=2),
                    "resolved_at": None,
                    "severity": "warning",
                },
            ]
        )

        out = await svc.get_farm_alert_trend(farm_id=farm_id, days=4)
        counts = [p.open_count for p in out.points]
        # Buckets are end-of-day; oldest first. Expect [1, 2, 1, 1].
        # Day -3 EOD: A open (B not yet) → 1
        # Day -2 EOD: A open, B open → 2
        # Day -1 EOD: A resolved earlier today, B open → 1
        # Day  0 EOD (today): A resolved, B open → 1
        assert counts == [1, 2, 1, 1]

    async def test_empty_farm_returns_zeros(self) -> None:
        farm_id = uuid4()
        svc = _impl_with_mocked_repos()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(return_value=[])  # type: ignore[attr-defined]
        out = await svc.get_farm_alert_trend(farm_id=farm_id, days=3)
        assert [p.open_count for p in out.points] == [0, 0, 0]
        assert out.days == 3
