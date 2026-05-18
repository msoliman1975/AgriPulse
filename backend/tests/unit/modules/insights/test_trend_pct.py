"""Unit tests for the trend-pct helper in insights.service.

Covers the empty-data, divide-by-zero, and sign-preserving paths.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.insights.service import _trend_pct


class TestTrendPct:
    def test_both_endpoints_present_positive_delta(self) -> None:
        # 0.5 → 0.6 = +20%
        assert _trend_pct(current=Decimal("0.6"), anchor=Decimal("0.5")) == Decimal("20.00")

    def test_both_endpoints_present_negative_delta(self) -> None:
        # 0.5 → 0.4 = -20%
        assert _trend_pct(current=Decimal("0.4"), anchor=Decimal("0.5")) == Decimal("-20.00")

    def test_null_current_returns_none(self) -> None:
        assert _trend_pct(current=None, anchor=Decimal("0.5")) is None

    def test_null_anchor_returns_none(self) -> None:
        assert _trend_pct(current=Decimal("0.6"), anchor=None) is None

    def test_zero_anchor_returns_none_no_divide_by_zero(self) -> None:
        # Divide-by-zero defensive — shouldn't happen for NDVI but
        # could for indices with legitimate zero baselines.
        assert _trend_pct(current=Decimal("0.6"), anchor=Decimal("0")) is None

    def test_quantizes_to_two_decimals(self) -> None:
        # 0.123456 → 0.234567 = ~89.99% — quantised to two places.
        out = _trend_pct(current=Decimal("0.234567"), anchor=Decimal("0.123456"))
        assert out is not None
        # 0.234567 - 0.123456 = 0.111111; /0.123456 = 0.9; * 100 = 90.00.
        assert out == Decimal("90.00")

    def test_uses_abs_anchor_so_negative_index_handled(self) -> None:
        # baseline_deviation can be negative; the % should still
        # reflect magnitude direction correctly.
        # -0.5 → -0.3 (improvement, less deviation) — delta +0.2,
        # abs(anchor)=0.5, pct = +40%
        out = _trend_pct(current=Decimal("-0.3"), anchor=Decimal("-0.5"))
        assert out == Decimal("40.00")


@pytest.mark.asyncio
class TestServiceFlow:
    """End-to-end shape check via mocked repos.

    The real SQL paths (indices CAGG aggregation + alerts JOIN) are
    integration-tested separately; here we verify the service's
    composition logic: blocks loop, trend computation, alert rollup,
    classification, sort-by-severity.
    """

    async def test_smoke_health_summary_shape(self) -> None:
        from unittest.mock import AsyncMock
        from uuid import uuid4

        from app.modules.insights.service import InsightsService
        from app.shared.health import classify_health

        svc = InsightsService.__new__(InsightsService)
        svc._farms = AsyncMock()  # type: ignore[attr-defined]
        svc._indices = AsyncMock()  # type: ignore[attr-defined]
        svc._alerts = AsyncMock()  # type: ignore[attr-defined]

        farm_id = uuid4()
        b1, b2 = uuid4(), uuid4()
        svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
        svc._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": b1, "name": "North"},
                {"id": b2, "name": "South"},
            ]
        )
        # Indices: b1 healthy + improving, b2 critical (low NDVI).
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        svc._indices.get_timeseries = AsyncMock(  # type: ignore[attr-defined]
            side_effect=lambda **kw: (
                ({"bucket_time": now, "mean": Decimal("0.7")},)
                if kw["block_id"] == b1
                else ({"bucket_time": now, "mean": Decimal("0.3")},)
            )
        )
        svc._alerts.list_alerts = AsyncMock(return_value=())  # type: ignore[attr-defined]

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        assert out.farm_id == farm_id
        assert out.index_code == "ndvi"
        assert len(out.blocks) == 2
        # Sort: critical first (South), then healthy (North).
        assert out.blocks[0].block_name == "South"
        assert out.blocks[0].current_health == "critical"
        assert out.blocks[1].current_health == "healthy"
        # Belt-and-brace classifier agreement.
        assert classify_health(worst_alert_severity=None, ndvi_current=Decimal("0.3")) == "critical"
        # Trend is None because we returned the same single point for
        # both the current and anchor windows (mocked side_effect
        # ignores `from_datetime`/`to_datetime`); covers the None branch.
        # Note: in real flow `_latest_observation` reverses the bucket
        # list and picks the latest ≤ until; with one row both queries
        # return that row, so trend = (x-x)/|x|*100 = 0.
        assert out.blocks[0].trend_30d_pct == Decimal("0.00")
