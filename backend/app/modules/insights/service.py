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
    AlertTrendPoint,
    BlockHealthRow,
    FarmAlertTrendResponse,
    FarmAnnotationsResponse,
    FarmHealthSummaryResponse,
    FarmIndexTimeseriesPoint,
    FarmIndexTimeseriesResponse,
    FarmSeasonContextResponse,
    SeasonContextCrop,
    TimeseriesAnnotation,
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

    # ---- B.3: annotations + season + alerts sparkline ------------------

    async def get_farm_annotations(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
    ) -> FarmAnnotationsResponse:
        """Vertical markers for the FarmTrendChart.

        V1 surfaces only `alert_opened` events — they're the
        decision-relevant moments and they map cleanly onto a
        vertical line. Activities + resolutions are deferred:
        activities would need a stable "type" vocabulary, and
        resolutions visually pair with their opening line (clutter).
        """
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        blocks = await self._farms.list_blocks(
            farm_id=farm_id,
            after=None,
            limit=200,
            irrigation_system=None,
            include_inactive=False,
        )
        block_id_set = {b["id"] for b in blocks}

        # Pull every open + closed alert for the farm; in-window
        # filter is in Python so a single query covers every block.
        # 200-row cap matches the alerts repo default — fine for a
        # 30-day window on a typical farm.
        annotations: list[TimeseriesAnnotation] = []
        for block_id in block_id_set:
            alerts = await self._alerts.list_alerts(block_id=block_id, limit=200)
            for a in alerts:
                created = a["created_at"]
                if since is not None and created < since:
                    continue
                if until is not None and created > until:
                    continue
                # Diagnosis text gives the operator one-line context;
                # severity drives the FE color.
                label = a.get("diagnosis_en") or a.get("rule_code") or "Alert opened"
                annotations.append(
                    TimeseriesAnnotation(
                        time=created,
                        kind="alert_opened",
                        label=label,
                        severity=a["severity"],
                        block_id=block_id,
                    )
                )

        annotations.sort(key=lambda x: x.time)
        return FarmAnnotationsResponse(farm_id=farm_id, annotations=annotations)

    async def get_farm_season_context(self, *, farm_id: UUID) -> FarmSeasonContextResponse:
        """Crop mix summary for the season-context bar. Joins
        block_crops + crops; counts blocks per crop. No planting-
        date / phenology math in V1 — that's a follow-up that
        needs reliable activity-type vocab."""
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        rows = await _select_farm_crops(self._session, farm_id=farm_id)
        crops = [
            SeasonContextCrop(
                crop_id=r["crop_id"],
                name_en=r["name_en"],
                name_ar=r.get("name_ar"),
                block_count=r["block_count"],
            )
            for r in rows
        ]
        blocks = await self._farms.list_blocks(
            farm_id=farm_id,
            after=None,
            limit=200,
            irrigation_system=None,
            include_inactive=False,
        )
        return FarmSeasonContextResponse(
            farm_id=farm_id, crops=crops, active_block_count=len(blocks)
        )

    async def get_farm_alert_trend(self, *, farm_id: UUID, days: int) -> FarmAlertTrendResponse:
        """Daily snapshot of open-alert count for the alerts KPI
        sparkline. Computed by walking every alert in the window
        and counting `open at end of day N` = `opened ≤ day_end
        AND (resolved_at IS NULL OR resolved_at > day_end)`."""
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        blocks = await self._farms.list_blocks(
            farm_id=farm_id,
            after=None,
            limit=200,
            irrigation_system=None,
            include_inactive=False,
        )

        # Pull a wide window of alerts (opened OR resolved within
        # the requested span). Status filter omitted so resolved
        # alerts still contribute to "was open on day N".
        all_alerts: list[dict[str, Any]] = []
        for block in blocks:
            rows = await self._alerts.list_alerts(block_id=block["id"], limit=500)
            all_alerts.extend(rows)

        now = datetime.now(UTC)
        # Day-aligned end-of-day buckets, oldest first.
        points: list[AlertTrendPoint] = []
        for offset in range(days - 1, -1, -1):
            day_end = (now - timedelta(days=offset)).replace(
                hour=23, minute=59, second=59, microsecond=0
            )
            open_at_end = sum(
                1
                for a in all_alerts
                if a["created_at"] <= day_end
                and (a["resolved_at"] is None or a["resolved_at"] > day_end)
            )
            points.append(AlertTrendPoint(date=day_end, open_count=open_at_end))

        return FarmAlertTrendResponse(farm_id=farm_id, days=days, points=points)


async def _select_farm_crops(session: AsyncSession, *, farm_id: UUID) -> list[dict[str, Any]]:
    """Read crop mix for a farm. Lives at module-level so it can be
    monkeypatched cheaply in tests; the SQL is small enough not to
    deserve its own repo class."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT c.id AS crop_id, c.name_en, c.name_ar,
                       COUNT(DISTINCT bc.block_id) AS block_count
                FROM block_crops bc
                JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
                JOIN public.crops c ON c.id = bc.crop_id
                WHERE b.farm_id = :farm_id
                  AND bc.deleted_at IS NULL
                GROUP BY c.id, c.name_en, c.name_ar
                ORDER BY block_count DESC, c.name_en ASC
                """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _trend_pct(*, current: Decimal | None, anchor: Decimal | None) -> Decimal | None:
    """(current - anchor) / |anchor| * 100. None when either endpoint
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
