"""Reports service — composes existing repos into read-only payloads.

No data of its own; orchestrates the feature repos plus module-level
`text()` SQL helpers for report-specific rollups (the `_select_*`
pattern from insights/service.py). Pure read path — no audit events.

Each report method is added below the shared helpers as its PR lands.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.errors import FarmNotFoundError
from app.modules.farms.repository import FarmsRepository
from app.modules.grid.anomaly import DEFAULT_K, DEFAULT_MIN_CELLS, DEFAULT_MIN_STD

from .schemas import (
    CropHealthBlockRow,
    CropHealthReportResponse,
    CropHealthStatus,
    CropHealthSummary,
    OperationsLogReportResponse,
    OpsLogEntry,
    OpsLogSummary,
    ReportPeriod,
    WaterBalanceBlockRow,
    WaterBalanceReportResponse,
    WaterBalanceSummary,
    WaterBalanceWeather,
    WeatherCropContext,
    WeatherDailyPoint,
    WeatherSummaryReportResponse,
    WeatherSummaryStats,
    ZoneAnomalyBlockRow,
    ZoneAnomalyReportResponse,
    ZoneAnomalyStatus,
    ZoneAnomalySummary,
)

# Default window when the caller omits since/until. 30 days matches the
# insights trend window so the two surfaces line up.
_DEFAULT_WINDOW = timedelta(days=30)

# Block fan-out cap, same as insights. A farm with >200 active blocks is
# well past V1 assumptions; revisit with keyset pagination if it lands.
_BLOCK_LIMIT = 200

# Baseline-deviation thresholds for the crop-health status. z is the
# latest scene's deviation from the block's historical baseline in
# std-devs; below normal is the concern, so only the negative side maps
# to watch/stressed.
_Z_WATCH = Decimal("-1")
_Z_STRESSED = Decimal("-2")


def resolve_period(since: datetime | None, until: datetime | None) -> ReportPeriod:
    """Fill a [since, until] window, defaulting to the last 30 days.

    `until` defaults to now; `since` to (until - 30d). Callers pass the
    raw query params straight through so the default lives in one place.
    """
    resolved_until = until or datetime.now(UTC)
    resolved_since = since or (resolved_until - _DEFAULT_WINDOW)
    return ReportPeriod(since=resolved_since, until=resolved_until)


class ReportsService:
    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._session = tenant_session
        self._public_session = public_session
        self._farms = FarmsRepository(tenant_session, public_session=public_session)

    async def _load_farm(self, farm_id: UUID) -> dict[str, Any]:
        """Resolve the farm or raise FarmNotFoundError. Every report
        starts here so a bad farm_id 404s before any heavy reads."""
        farm = await self._farms.get_farm_by_id(farm_id, with_boundary=False)
        if farm is None:
            raise FarmNotFoundError(farm_id)
        return farm

    async def _list_active_blocks(self, farm_id: UUID) -> list[dict[str, Any]]:
        """Active blocks for the farm, name-resolved. Shared by reports
        that fan out per block."""
        return await self._farms.list_blocks(
            farm_id=farm_id,
            after=None,
            limit=_BLOCK_LIMIT,
            irrigation_system=None,
            include_inactive=False,
        )

    # ---- PR-1: Seasonal Crop Health ------------------------------------

    async def get_crop_health_report(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        since: datetime | None,
        until: datetime | None,
    ) -> CropHealthReportResponse:
        """Per-block vegetation summary for one index over the window.

        One SQL pass collects window aggregates + the latest scene's
        spatial percentiles + baseline z per block; blocks with no scene
        in the window still appear (with null metrics) so the report
        lists the whole farm. Status is derived from the latest z so it
        is index-agnostic."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)
        blocks = await self._list_active_blocks(farm_id)

        stats = await _select_crop_health_stats(
            self._session,
            farm_id=farm_id,
            index_code=index_code,
            since=period.since,
            until=period.until,
        )
        crops = await _select_block_current_crops(self._session, farm_id=farm_id)

        rows: list[CropHealthBlockRow] = []
        counts = {"normal": 0, "watch": 0, "stressed": 0, "unknown": 0}
        value_sum = Decimal(0)
        value_n = 0
        with_data = 0

        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            s = stats.get(block_id)
            crop = crops.get(block_id)

            if s is None:
                status: CropHealthStatus = "unknown"
                counts["unknown"] += 1
                rows.append(
                    CropHealthBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        crop_name_en=crop[0] if crop else None,
                        crop_name_ar=crop[1] if crop else None,
                        status=status,
                        last_value=None,
                        last_observed_at=None,
                        baseline_z=None,
                        trend_pct=None,
                        min_value=None,
                        max_value=None,
                        p10=None,
                        p50=None,
                        p90=None,
                        avg_valid_pixel_pct=None,
                        avg_cloud_pct=None,
                        scene_count=0,
                    )
                )
                continue

            with_data += 1
            z = s["last_z"]
            status = _status_from_z(z)
            counts[status] += 1
            last_value = s["last_mean"]
            if last_value is not None:
                value_sum += last_value
                value_n += 1

            rows.append(
                CropHealthBlockRow(
                    block_id=block_id,
                    block_name=block_name,
                    crop_name_en=crop[0] if crop else None,
                    crop_name_ar=crop[1] if crop else None,
                    status=status,
                    last_value=last_value,
                    last_observed_at=s["last_time"],
                    baseline_z=z,
                    trend_pct=_trend_pct(first=s["first_mean"], last=last_value),
                    min_value=s["min_mean"],
                    max_value=s["max_mean"],
                    p10=s["last_p10"],
                    p50=s["last_p50"],
                    p90=s["last_p90"],
                    avg_valid_pixel_pct=_q2(s["avg_valid_pct"]),
                    avg_cloud_pct=_q2(s["avg_cloud_pct"]),
                    scene_count=s["scene_count"],
                )
            )

        # Stressed first, then watch, unknown, normal — same attention
        # ordering as the insights scorecard.
        order = {"stressed": 0, "watch": 1, "unknown": 2, "normal": 3}
        rows.sort(key=lambda r: (order[r.status], r.block_name))

        summary = CropHealthSummary(
            block_count=len(blocks),
            with_data_count=with_data,
            normal=counts["normal"],
            watch=counts["watch"],
            stressed=counts["stressed"],
            unknown=counts["unknown"],
            avg_last_value=_q3(value_sum / value_n) if value_n else None,
        )
        return CropHealthReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            index_code=index_code,
            period=period,
            blocks=rows,
            summary=summary,
        )

    # ---- PR-2: Field Variability / Zone Anomaly ------------------------

    async def get_zone_anomaly_report(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        since: datetime | None,
        until: datetime | None,
    ) -> ZoneAnomalyReportResponse:
        """Per-block within-field variability on the latest grid scene.

        Flags low-outlier cells (cell mean ≤ block_mean - k·block_std)
        using the block's configured threshold, the same rule as the
        live grid anomaly detector. Blocks without a grid config or a
        recent scene are listed with the reason so the report covers the
        whole farm."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)
        blocks = await self._list_active_blocks(farm_id)

        stats = await _select_zone_anomaly_stats(
            self._session,
            farm_id=farm_id,
            index_code=index_code,
            since=period.since,
            until=period.until,
        )
        gridded = await _select_blocks_with_grid(self._session, farm_id=farm_id)

        rows: list[ZoneAnomalyBlockRow] = []
        total_flagged_cells = 0
        total_flagged_area = Decimal(0)
        blocks_with_anomalies = 0

        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            s = stats.get(block_id)

            if s is None:
                status: ZoneAnomalyStatus = "no_data" if block_id in gridded else "no_grid"
                rows.append(
                    ZoneAnomalyBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        status=status,
                        scene_time=None,
                        cell_count=0,
                        flagged_count=0,
                        flagged_area_ha=None,
                        worst_z=None,
                        block_mean=None,
                        block_std=None,
                        threshold_k=None,
                    )
                )
                continue

            cell_count = s["cell_count"]
            bstd = s["bstd"]
            reliable = cell_count >= DEFAULT_MIN_CELLS and (
                bstd is not None and bstd >= Decimal(str(DEFAULT_MIN_STD))
            )
            flagged = s["flagged"] if reliable else 0
            area_ha = (
                (s["flagged_area_m2"] / Decimal(10000)).quantize(Decimal("0.001"))
                if reliable and s["flagged_area_m2"] is not None
                else (Decimal("0.000") if reliable else None)
            )

            if not reliable:
                status = "insufficient"
            elif flagged > 0:
                status = "anomalies"
                blocks_with_anomalies += 1
                total_flagged_cells += flagged
                if area_ha is not None:
                    total_flagged_area += area_ha
            else:
                status = "clear"

            rows.append(
                ZoneAnomalyBlockRow(
                    block_id=block_id,
                    block_name=block_name,
                    status=status,
                    scene_time=s["scene_time"],
                    cell_count=cell_count,
                    flagged_count=flagged,
                    flagged_area_ha=area_ha,
                    worst_z=_q2(s["worst_z"]),
                    block_mean=_q3(s["bmean"]),
                    block_std=_q3(bstd),
                    threshold_k=s["z_thr"],
                )
            )

        order = {"anomalies": 0, "insufficient": 1, "no_data": 2, "no_grid": 3, "clear": 4}
        rows.sort(key=lambda r: (order[r.status], -(r.flagged_count), r.block_name))

        summary = ZoneAnomalySummary(
            block_count=len(blocks),
            blocks_with_grid=sum(1 for b in blocks if b["id"] in gridded),
            blocks_with_anomalies=blocks_with_anomalies,
            total_flagged_cells=total_flagged_cells,
            total_flagged_area_ha=(
                total_flagged_area.quantize(Decimal("0.001")) if blocks_with_anomalies else None
            ),
        )
        return ZoneAnomalyReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            index_code=index_code,
            period=period,
            blocks=rows,
            summary=summary,
        )

    # ---- PR-3: Irrigation & Water Balance ------------------------------

    async def get_water_balance_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
    ) -> WaterBalanceReportResponse:
        """Farm water demand (ET₀) vs rainfall, plus per-block irrigation
        adherence (recommended vs applied mm) over the window."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)
        blocks = await self._list_active_blocks(farm_id)

        since_d = period.since.date()
        until_d = period.until.date()

        wx = await _select_water_balance_weather(
            self._session, farm_id=farm_id, since=since_d, until=until_d
        )
        sched = await _select_water_balance_blocks(
            self._session, farm_id=farm_id, since=since_d, until=until_d
        )

        days = wx["days"] or 0
        et0_total = wx["et0_total"]
        precip_total = wx["precip_total"]
        weather = WaterBalanceWeather(
            days_with_data=days,
            et0_mm_total=_q2(et0_total),
            precip_mm_total=_q2(precip_total),
            et0_mm_avg_daily=(_q2(et0_total / days) if days and et0_total is not None else None),
        )

        rows: list[WaterBalanceBlockRow] = []
        rec_total = Decimal(0)
        app_total = Decimal(0)
        applied_count = skipped_count = pending_count = 0
        with_schedules = 0

        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            s = sched.get(block_id)
            if s is None:
                rows.append(
                    WaterBalanceBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        scheduled_count=0,
                        applied_count=0,
                        skipped_count=0,
                        pending_count=0,
                        recommended_mm_total=None,
                        applied_mm_total=None,
                        adherence_pct=None,
                        last_scheduled_for=None,
                    )
                )
                continue

            with_schedules += 1
            rec = s["recommended_mm_total"] or Decimal(0)
            app = s["applied_mm_total"] or Decimal(0)
            rec_total += rec
            app_total += app
            applied_count += s["applied_count"]
            skipped_count += s["skipped_count"]
            pending_count += s["pending_count"]

            rows.append(
                WaterBalanceBlockRow(
                    block_id=block_id,
                    block_name=block_name,
                    scheduled_count=s["scheduled_count"],
                    applied_count=s["applied_count"],
                    skipped_count=s["skipped_count"],
                    pending_count=s["pending_count"],
                    recommended_mm_total=_q2(rec),
                    applied_mm_total=_q2(app),
                    adherence_pct=(
                        (app / rec * Decimal(100)).quantize(Decimal("0.1")) if rec > 0 else None
                    ),
                    last_scheduled_for=s["last_scheduled_for"],
                )
            )

        # Blocks with the most scheduling activity first; quiet blocks sink.
        rows.sort(key=lambda r: (-r.scheduled_count, r.block_name))

        summary = WaterBalanceSummary(
            block_count=len(blocks),
            blocks_with_schedules=with_schedules,
            recommended_mm_total=_q2(rec_total) if with_schedules else None,
            applied_mm_total=_q2(app_total) if with_schedules else None,
            applied_count=applied_count,
            skipped_count=skipped_count,
            pending_count=pending_count,
        )
        return WaterBalanceReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            period=period,
            weather=weather,
            blocks=rows,
            summary=summary,
        )

    # ---- PR-4: Weather & Growing-Degree-Days Summary -------------------

    async def get_weather_summary_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
    ) -> WeatherSummaryReportResponse:
        """Farm temperature / rainfall / ET₀ / GDD roll-up plus the daily
        series for charting and the current-crop agronomic context."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)

        rows = await _select_weather_daily(
            self._session, farm_id=farm_id, since=period.since.date(), until=period.until.date()
        )
        crops = await _select_weather_crop_context(self._session, farm_id=farm_id)

        daily = [
            WeatherDailyPoint(
                date=r["date"],
                temp_min_c=r["temp_min_c"],
                temp_max_c=r["temp_max_c"],
                temp_mean_c=r["temp_mean_c"],
                precip_mm=r["precip_mm_daily"],
                et0_mm=r["et0_mm_daily"],
                gdd_base10=r["gdd_base10"],
                gdd_cumulative_season=r["gdd_cumulative_base10_season"],
            )
            for r in rows
        ]

        stats = _weather_stats(rows)
        crop_ctx = [
            WeatherCropContext(
                crop_id=c["crop_id"],
                name_en=c["name_en"],
                name_ar=c["name_ar"],
                block_count=c["block_count"],
                gdd_base_temp_c=c["gdd_base_temp_c"],
                default_growing_season_days=c["default_growing_season_days"],
            )
            for c in crops
        ]
        return WeatherSummaryReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            period=period,
            stats=stats,
            daily=daily,
            crops=crop_ctx,
        )

    # ---- PR-5: Farm Operations & Agronomy Log --------------------------

    async def get_operations_log_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
    ) -> OperationsLogReportResponse:
        """Unified chronological log of activities, alerts, and
        recommendations on the farm over the window, plus action counts.
        Each source is window-scoped on its own date (activity scheduled
        date, alert/recommendation creation time)."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)

        activities = await _select_ops_activities(
            self._session, farm_id=farm_id, since=period.since.date(), until=period.until.date()
        )
        alerts = await _select_ops_alerts(
            self._session, farm_id=farm_id, since=period.since, until=period.until
        )
        recs = await _select_ops_recommendations(
            self._session, farm_id=farm_id, since=period.since, until=period.until
        )

        entries: list[OpsLogEntry] = []

        for a in activities:
            detail_bits = [b for b in (a.get("product_name"), a.get("dosage")) if b]
            entries.append(
                OpsLogEntry(
                    time=datetime.combine(a["scheduled_date"], dt_time.min, tzinfo=UTC),
                    kind="activity",
                    block_name=a.get("block_name"),
                    title=a["activity_type"],
                    status=a.get("status"),
                    detail=" · ".join(detail_bits) if detail_bits else None,
                )
            )

        # The alerts fetch also returns alerts only *resolved* in the
        # window (opened earlier) so the resolved-count is accurate; emit
        # log entries only for alerts actually *opened* in the window.
        opened_alerts = [al for al in alerts if period.since <= al["created_at"] <= period.until]
        for al in opened_alerts:
            entries.append(
                OpsLogEntry(
                    time=al["created_at"],
                    kind="alert",
                    block_name=al.get("block_name"),
                    title=al.get("diagnosis_en") or al["rule_code"],
                    status=al.get("status"),
                    severity=al.get("severity"),
                )
            )

        for rc in recs:
            entries.append(
                OpsLogEntry(
                    time=rc["created_at"],
                    kind="recommendation",
                    block_name=rc.get("block_name"),
                    title=_truncate(rc["text_en"], 140) or rc["action_type"],
                    status=rc.get("state"),
                    severity=rc.get("severity"),
                    detail=rc.get("dismissal_reason"),
                )
            )

        entries.sort(key=lambda e: e.time, reverse=True)

        summary = OpsLogSummary(
            activities_total=len(activities),
            activities_completed=sum(1 for a in activities if a.get("status") == "completed"),
            activities_skipped=sum(1 for a in activities if a.get("status") == "skipped"),
            alerts_opened=len(opened_alerts),
            alerts_resolved=sum(
                1
                for al in alerts
                if al.get("resolved_at") is not None
                and period.since <= al["resolved_at"] <= period.until
            ),
            recommendations_total=len(recs),
            recommendations_applied=sum(1 for rc in recs if rc.get("state") == "applied"),
            recommendations_dismissed=sum(1 for rc in recs if rc.get("state") == "dismissed"),
        )
        return OperationsLogReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            period=period,
            entries=entries,
            summary=summary,
        )


def get_reports_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> ReportsService:
    return ReportsService(tenant_session=tenant_session, public_session=public_session)


# --- module-level helpers ---------------------------------------------------


def _status_from_z(z: Decimal | None) -> CropHealthStatus:
    """Map a baseline z-score to a vegetation status. Only the negative
    side (below normal) is a concern."""
    if z is None:
        return "unknown"
    if z <= _Z_STRESSED:
        return "stressed"
    if z <= _Z_WATCH:
        return "watch"
    return "normal"


def _trend_pct(*, first: Decimal | None, last: Decimal | None) -> Decimal | None:
    """(last - first) / |first| * 100. None when either endpoint is
    missing or first is zero (would divide by zero)."""
    if first is None or last is None or first == 0:
        return None
    return ((last - first) / abs(first) * Decimal(100)).quantize(Decimal("0.01"))


def _q2(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.01")) if value is not None else None


def _q3(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.001")) if value is not None else None


async def _select_crop_health_stats(
    session: AsyncSession,
    *,
    farm_id: UUID,
    index_code: str,
    since: datetime,
    until: datetime,
) -> dict[UUID, dict[str, Any]]:
    """One pass over block_index_aggregates for a farm: per-block window
    aggregates joined to the latest and earliest in-window scene. Returns
    a {block_id: stats} map; blocks with no scene in the window are
    simply absent."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        WITH scoped AS (
            SELECT a.block_id, a.time, a.mean,
                   a.p10, a.p50, a.p90, a.baseline_deviation,
                   a.valid_pixel_count, a.total_pixel_count, a.cloud_cover_pct
            FROM block_index_aggregates a
            JOIN blocks b ON b.id = a.block_id AND b.deleted_at IS NULL
            WHERE b.farm_id = :farm_id
              AND a.index_code = :index_code
              AND a.time >= :since AND a.time <= :until
              AND a.mean IS NOT NULL
        ),
        win AS (
            SELECT block_id,
                   count(*) AS scene_count,
                   min(mean) AS min_mean,
                   max(mean) AS max_mean,
                   avg(CASE WHEN total_pixel_count > 0
                            THEN valid_pixel_count::numeric / total_pixel_count * 100
                       END) AS avg_valid_pct,
                   avg(cloud_cover_pct) AS avg_cloud_pct
            FROM scoped GROUP BY block_id
        ),
        latest AS (
            SELECT DISTINCT ON (block_id)
                   block_id, time AS last_time, mean AS last_mean,
                   p10 AS last_p10, p50 AS last_p50, p90 AS last_p90,
                   baseline_deviation AS last_z
            FROM scoped ORDER BY block_id, time DESC
        ),
        earliest AS (
            SELECT DISTINCT ON (block_id) block_id, mean AS first_mean
            FROM scoped ORDER BY block_id, time ASC
        )
        SELECT w.block_id, w.scene_count, w.min_mean, w.max_mean,
               w.avg_valid_pct, w.avg_cloud_pct,
               l.last_time, l.last_mean, l.last_p10, l.last_p50, l.last_p90, l.last_z,
               e.first_mean
        FROM win w
        JOIN latest l USING (block_id)
        JOIN earliest e USING (block_id)
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(
        sql,
        {"farm_id": farm_id, "index_code": index_code, "since": since, "until": until},
    )
    return {row["block_id"]: dict(row) for row in result.mappings().all()}


async def _select_block_current_crops(
    session: AsyncSession, *, farm_id: UUID
) -> dict[UUID, tuple[str, str | None]]:
    """Current crop name (en, ar) per block for a farm. Only the
    is_current assignment is returned; blocks with none are absent."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT bc.block_id, c.name_en, c.name_ar
        FROM block_crops bc
        JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
        JOIN public.crops c ON c.id = bc.crop_id
        WHERE b.farm_id = :farm_id
          AND bc.deleted_at IS NULL
          AND bc.is_current IS TRUE
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id})
    return {row["block_id"]: (row["name_en"], row["name_ar"]) for row in result.mappings().all()}


async def _select_blocks_with_grid(session: AsyncSession, *, farm_id: UUID) -> set[UUID]:
    """Block ids on the farm that have an active (non-retired) grid
    config. Used to tell 'no grid' apart from 'grid but no recent
    scene'."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT DISTINCT gc.block_id
        FROM grid_configs gc
        JOIN blocks b ON b.id = gc.block_id AND b.deleted_at IS NULL
        WHERE b.farm_id = :farm_id AND gc.retired_at IS NULL
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id})
    return {row["block_id"] for row in result.mappings().all()}


async def _select_zone_anomaly_stats(
    session: AsyncSession,
    *,
    farm_id: UUID,
    index_code: str,
    since: datetime,
    until: datetime,
) -> dict[UUID, dict[str, Any]]:
    """Per-block grid stats on the latest in-window scene: block mean/std
    across cells, the configured threshold, and the low-outlier count +
    area. One row per block that has a configured grid AND a scene."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        WITH cfg AS (
            SELECT gc.block_id, gc.product_id,
                   COALESCE(gc.anomaly_z_threshold, CAST(:default_k AS numeric)) AS z_thr
            FROM grid_configs gc
            JOIN blocks b ON b.id = gc.block_id AND b.deleted_at IS NULL
            WHERE b.farm_id = :farm_id AND gc.retired_at IS NULL
        ),
        latest_scene AS (
            SELECT DISTINCT ON (a.block_id)
                   a.block_id, a.product_id, a.time AS scene_time, cfg.z_thr
            FROM block_grid_aggregates a
            JOIN cfg ON cfg.block_id = a.block_id AND cfg.product_id = a.product_id
            WHERE a.index_code = :index_code
              AND a.time >= :since AND a.time <= :until
              AND a.mean IS NOT NULL
            ORDER BY a.block_id, a.time DESC
        ),
        cells AS (
            SELECT a.block_id, a.mean, gcell.area_m2, ls.scene_time, ls.z_thr
            FROM block_grid_aggregates a
            JOIN latest_scene ls
              ON ls.block_id = a.block_id
             AND ls.product_id = a.product_id
             AND ls.scene_time = a.time
            JOIN grid_cells gcell ON gcell.id = a.cell_id
            WHERE a.index_code = :index_code AND a.mean IS NOT NULL
        ),
        stats AS (
            SELECT block_id, scene_time, z_thr,
                   avg(mean) AS bmean, stddev_pop(mean) AS bstd, count(*) AS cell_count
            FROM cells GROUP BY block_id, scene_time, z_thr
        )
        SELECT s.block_id, s.scene_time, s.bmean, s.bstd, s.cell_count, s.z_thr,
               count(*) FILTER (
                   WHERE s.bstd > 0 AND (c.mean - s.bmean) / s.bstd <= -s.z_thr
               ) AS flagged,
               COALESCE(sum(c.area_m2) FILTER (
                   WHERE s.bstd > 0 AND (c.mean - s.bmean) / s.bstd <= -s.z_thr
               ), 0) AS flagged_area_m2,
               CASE WHEN s.bstd > 0 THEN min((c.mean - s.bmean) / s.bstd) END AS worst_z
        FROM cells c
        JOIN stats s ON s.block_id = c.block_id
        GROUP BY s.block_id, s.scene_time, s.bmean, s.bstd, s.cell_count, s.z_thr
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(
        sql,
        {
            "farm_id": farm_id,
            "index_code": index_code,
            "since": since,
            "until": until,
            "default_k": DEFAULT_K,
        },
    )
    return {row["block_id"]: dict(row) for row in result.mappings().all()}


async def _select_water_balance_weather(
    session: AsyncSession, *, farm_id: UUID, since: date, until: date
) -> dict[str, Any]:
    """Farm ET₀ + rainfall totals over the window from the daily derived
    table. Single-row result (days, et0_total, precip_total)."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT count(*) AS days,
               sum(et0_mm_daily) AS et0_total,
               sum(precip_mm_daily) AS precip_total
        FROM weather_derived_daily
        WHERE farm_id = :farm_id AND date >= :since AND date <= :until
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    row = (
        (await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until}))
        .mappings()
        .one()
    )
    return dict(row)


async def _select_water_balance_blocks(
    session: AsyncSession, *, farm_id: UUID, since: date, until: date
) -> dict[UUID, dict[str, Any]]:
    """Per-block irrigation activity over the window: schedule + applied
    counts, recommended vs applied volume, last scheduled date."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT s.block_id,
               count(*) AS scheduled_count,
               count(*) FILTER (WHERE s.status = 'applied') AS applied_count,
               count(*) FILTER (WHERE s.status = 'skipped') AS skipped_count,
               count(*) FILTER (WHERE s.status = 'pending') AS pending_count,
               sum(s.recommended_mm) AS recommended_mm_total,
               COALESCE(
                   sum(s.applied_volume_mm) FILTER (WHERE s.status = 'applied'), 0
               ) AS applied_mm_total,
               max(s.scheduled_for) AS last_scheduled_for
        FROM irrigation_schedules s
        JOIN blocks b ON b.id = s.block_id AND b.deleted_at IS NULL
        WHERE b.farm_id = :farm_id
          AND s.scheduled_for >= :since AND s.scheduled_for <= :until
        GROUP BY s.block_id
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return {row["block_id"]: dict(row) for row in result.mappings().all()}


def _dsum(values: list[Decimal]) -> Decimal:
    total = Decimal(0)
    for v in values:
        total += v
    return total


def _weather_stats(rows: list[dict[str, Any]]) -> WeatherSummaryStats:
    """Roll a daily weather series up to window stats. Pure (no I/O) so
    it's cheap to unit-test. Rows are date-ascending."""

    def _vals(key: str) -> list[Decimal]:
        return [r[key] for r in rows if r.get(key) is not None]

    temp_mins = _vals("temp_min_c")
    temp_maxs = _vals("temp_max_c")
    temp_means = _vals("temp_mean_c")
    precip = _vals("precip_mm_daily")
    et0 = _vals("et0_mm_daily")
    gdd = _vals("gdd_base10")

    # Latest non-null cumulative — the season-to-date GDD.
    gdd_cumulative: Decimal | None = None
    for r in reversed(rows):
        if r.get("gdd_cumulative_base10_season") is not None:
            gdd_cumulative = r["gdd_cumulative_base10_season"]
            break

    return WeatherSummaryStats(
        days_with_data=len(rows),
        temp_min_c=min(temp_mins) if temp_mins else None,
        temp_max_c=max(temp_maxs) if temp_maxs else None,
        temp_mean_c=(_q2(_dsum(temp_means) / len(temp_means)) if temp_means else None),
        precip_mm_total=_q2(_dsum(precip)) if precip else None,
        rain_days=sum(1 for p in precip if p > 0),
        et0_mm_total=_q2(_dsum(et0)) if et0 else None,
        et0_mm_avg_daily=(_q2(_dsum(et0) / len(et0)) if et0 else None),
        gdd_base10_total=_q2(_dsum(gdd)) if gdd else None,
        gdd_cumulative_season=_q2(gdd_cumulative),
    )


async def _select_weather_daily(
    session: AsyncSession, *, farm_id: UUID, since: date, until: date
) -> list[dict[str, Any]]:
    """Daily derived weather rows for a farm over the window, oldest
    first — both the chart series and the source for window stats."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT date, temp_min_c, temp_max_c, temp_mean_c,
               precip_mm_daily, et0_mm_daily,
               gdd_base10, gdd_cumulative_base10_season
        FROM weather_derived_daily
        WHERE farm_id = :farm_id AND date >= :since AND date <= :until
        ORDER BY date ASC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]


async def _select_weather_crop_context(
    session: AsyncSession, *, farm_id: UUID
) -> list[dict[str, Any]]:
    """Current crops on the farm with their GDD base temp + default
    season length, for interpreting the accumulated GDD."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT c.id AS crop_id, c.name_en, c.name_ar,
               c.gdd_base_temp_c, c.default_growing_season_days,
               count(DISTINCT bc.block_id) AS block_count
        FROM block_crops bc
        JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
        JOIN public.crops c ON c.id = bc.crop_id
        WHERE b.farm_id = :farm_id
          AND bc.deleted_at IS NULL
          AND bc.is_current IS TRUE
        GROUP BY c.id, c.name_en, c.name_ar, c.gdd_base_temp_c, c.default_growing_season_days
        ORDER BY block_count DESC, c.name_en ASC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id})
    return [dict(r) for r in result.mappings().all()]


def _truncate(text_value: str | None, limit: int) -> str | None:
    if text_value is None:
        return None
    text_value = text_value.strip()
    return text_value if len(text_value) <= limit else text_value[: limit - 1].rstrip() + "…"


async def _select_ops_activities(
    session: AsyncSession, *, farm_id: UUID, since: date, until: date
) -> list[dict[str, Any]]:
    """Plan activities scheduled within the window, with block name."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT a.scheduled_date, a.activity_type, a.status,
               a.product_name, a.dosage,
               COALESCE(b.name, b.code) AS block_name
        FROM plan_activities a
        JOIN blocks b ON b.id = a.block_id AND b.deleted_at IS NULL
        WHERE a.farm_id = :farm_id
          AND a.scheduled_date >= :since AND a.scheduled_date <= :until
        ORDER BY a.scheduled_date DESC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]


async def _select_ops_alerts(
    session: AsyncSession, *, farm_id: UUID, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """Alerts opened within the window (or resolved within it, so the
    resolved-count is accurate), with block name."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT a.created_at, a.resolved_at, a.rule_code, a.severity,
               a.status, a.diagnosis_en,
               COALESCE(b.name, b.code) AS block_name
        FROM alerts a
        JOIN blocks b ON b.id = a.block_id AND b.deleted_at IS NULL
        WHERE b.farm_id = :farm_id
          AND (
              (a.created_at >= :since AND a.created_at <= :until)
              OR (a.resolved_at >= :since AND a.resolved_at <= :until)
          )
        ORDER BY a.created_at DESC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]


async def _select_ops_recommendations(
    session: AsyncSession, *, farm_id: UUID, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """Recommendations created within the window, with block name."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT r.created_at, r.action_type, r.severity, r.state,
               r.text_en, r.dismissal_reason,
               COALESCE(b.name, b.code) AS block_name
        FROM recommendations r
        JOIN blocks b ON b.id = r.block_id AND b.deleted_at IS NULL
        WHERE r.farm_id = :farm_id
          AND r.created_at >= :since AND r.created_at <= :until
        ORDER BY r.created_at DESC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]
