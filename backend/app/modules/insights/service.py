"""Insights service — composes farms + indices + alerts repos.

No data of its own; orchestrates the three repos to feed the two
read endpoints in `router.py`. Pure read path (no audit events).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.repository import AlertsRepository
from app.modules.farms.errors import FarmNotFoundError
from app.modules.farms.repository import FarmsRepository
from app.modules.indices.repository import IndicesRepository
from app.shared.health import bucket_alert_severity, classify_health

from .schemas import (
    BlockHealthRow,
    FarmHealthSummaryResponse,
    FarmIndexTimeseriesPoint,
    FarmIndexTimeseriesResponse,
    TimeseriesGranularity,
)

# Health classification is NDVI-shaped (per app/shared/health.py
# thresholds), so the rollup endpoint pins to NDVI in V1. Surfaced via
# the response so a future overlay can swap without an API rev.
HEALTH_INDEX_CODE = "ndvi"

# Trend window. Picked at 30 days because most growers think of
# in-season comparisons that way; if the block has no observation at
# (now - 30d) ± a daily-bucket, trend resolves to None.
_TREND_WINDOW = timedelta(days=30)
_TREND_TOLERANCE = timedelta(days=2)


class InsightsService:
    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._session = tenant_session
        self._farms = FarmsRepository(tenant_session, public_session=public_session)
        self._indices = IndicesRepository(tenant_session)
        self._alerts = AlertsRepository(
            tenant_session=tenant_session, public_session=public_session
        )

    async def get_farm_index_timeseries(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        granularity: TimeseriesGranularity,
        since: datetime | None,
        until: datetime | None,
    ) -> FarmIndexTimeseriesResponse:
        """Read the bucketed mean per block, then flatten into one
        list of (time, block_id, block_name, value) points the FE
        feeds straight into a multi-series LineChart."""
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        blocks = await self._farms.list_blocks(
            farm_id=farm_id, after=None, limit=200, irrigation_system=None, include_inactive=False
        )

        points: list[FarmIndexTimeseriesPoint] = []
        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            rows = await self._indices.get_timeseries(
                block_id=block_id,
                index_code=index_code,
                granularity=granularity,
                from_datetime=since,
                to_datetime=until,
            )
            for r in rows:
                mean = r.get("mean")
                if mean is None:
                    # Null-mean bucket = no valid pixels; FE doesn't
                    # need to filter, we just drop server-side.
                    continue
                points.append(
                    FarmIndexTimeseriesPoint(
                        time=r["bucket_time"],
                        block_id=block_id,
                        block_name=block_name,
                        value=Decimal(str(mean)),
                    )
                )

        # Chronological order across blocks so the FE can render
        # without re-sorting per series.
        points.sort(key=lambda p: (p.time, str(p.block_id)))
        return FarmIndexTimeseriesResponse(
            farm_id=farm_id,
            index_code=index_code,
            granularity=granularity,
            points=points,
        )

    async def get_farm_health_summary(self, *, farm_id: UUID) -> FarmHealthSummaryResponse:
        """Per-block health rollup for the scorecard. Composes:

        1. blocks list (farms repo)
        2. NDVI current + 30d-ago point (indices repo, daily CAGG)
        3. open alert count + worst severity (alerts repo)
        4. classify_health(worst, current) → health bucket
        """
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        blocks = await self._farms.list_blocks(
            farm_id=farm_id, after=None, limit=200, irrigation_system=None, include_inactive=False
        )

        now = datetime.now(UTC)
        trend_anchor = now - _TREND_WINDOW

        rows: list[BlockHealthRow] = []
        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)

            current, current_at = await self._latest_observation(block_id=block_id, until=now)
            anchor, _ = await self._latest_observation(
                block_id=block_id,
                until=trend_anchor + _TREND_TOLERANCE,
                floor=trend_anchor - _TREND_TOLERANCE,
            )

            trend_pct = _trend_pct(current=current, anchor=anchor)
            worst, open_count = await self._block_alert_rollup(block_id=block_id)
            health = classify_health(worst_alert_severity=worst, ndvi_current=current)

            rows.append(
                BlockHealthRow(
                    block_id=block_id,
                    block_name=block_name,
                    current_health=health,
                    current_value=current,
                    trend_30d_pct=trend_pct,
                    alerts_open=open_count,
                    last_observation_at=current_at,
                )
            )

        # Sort: critical first, then watch, unknown, healthy. The
        # operator's eye should land on the rows that need attention.
        order = {"critical": 0, "watch": 1, "unknown": 2, "healthy": 3}
        rows.sort(key=lambda r: (order.get(r.current_health, 99), r.block_name))

        return FarmHealthSummaryResponse(farm_id=farm_id, index_code=HEALTH_INDEX_CODE, blocks=rows)

    async def _latest_observation(
        self,
        *,
        block_id: UUID,
        until: datetime,
        floor: datetime | None = None,
    ) -> tuple[Decimal | None, datetime | None]:
        """Most recent (mean, bucket_time) ≤ `until`, optionally
        floored at `floor` (used for the 30d anchor). Returns
        (None, None) when nothing matches.
        """
        rows = await self._indices.get_timeseries(
            block_id=block_id,
            index_code=HEALTH_INDEX_CODE,
            granularity="daily",
            from_datetime=floor,
            to_datetime=until,
        )
        for r in reversed(rows):
            mean = r.get("mean")
            if mean is not None:
                return Decimal(str(mean)), r["bucket_time"]
        return None, None

    async def _block_alert_rollup(self, *, block_id: UUID) -> tuple[Any, int]:
        """Open + acknowledged + snoozed alerts. (Resolved alerts
        don't count for health.) Returns (worst_bucket, count)."""
        alerts = await self._alerts.list_alerts(
            block_id=block_id,
            status_filter=("open", "acknowledged", "snoozed"),
            limit=200,
        )
        worst = None
        worst_rank = 99
        rank = {"critical": 0, "warning": 1, "info": 2}
        for a in alerts:
            r = rank.get(a["severity"], 99)
            if r < worst_rank:
                worst_rank = r
                worst = bucket_alert_severity(a["severity"])
        return worst, len(alerts)


def _trend_pct(*, current: Decimal | None, anchor: Decimal | None) -> Decimal | None:
    """(current - anchor) / |anchor| × 100. None when either endpoint
    is missing or anchor is zero (would divide by zero)."""
    if current is None or anchor is None or anchor == 0:
        return None
    delta = current - anchor
    pct = (delta / abs(anchor)) * Decimal(100)
    # Two decimals — the FE shows it as e.g. "+12.34%".
    return pct.quantize(Decimal("0.01"))


def get_insights_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> InsightsService:
    return InsightsService(tenant_session=tenant_session, public_session=public_session)
