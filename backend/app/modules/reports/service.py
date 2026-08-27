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
from app.shared.crop_taxonomy import path_matches

from .custom_fields import (
    CustomFieldRef,
    list_custom_fields,
    load_custom_values,
    parse_field_refs,
)
from .schemas import (
    CropHealthBlockRow,
    CropHealthReportResponse,
    CropHealthStatus,
    CropHealthSummary,
    CustomFieldDef,
    CustomFieldsResponse,
    CustomFieldValue,
    OperationsLogReportResponse,
    OpsLogEntry,
    OpsLogSummary,
    ReportPeriod,
    SignalDetailFilters,
    SignalDetailRow,
    SignalDetailsReportResponse,
    SignalDetailSummary,
    WaterBalanceBlockRow,
    WaterBalanceReportResponse,
    WaterBalanceSummary,
    WaterBalanceWeather,
    WeatherCropContext,
    WeatherDailyPoint,
    WeatherRiskPressureReportResponse,
    WeatherRiskPressureRow,
    WeatherRiskPressureSummary,
    WeatherSummaryReportResponse,
    WeatherSummaryStats,
    ZoneAnomalyBlockRow,
    ZoneAnomalyReportResponse,
    ZoneAnomalyStatus,
    ZoneAnomalySummary,
)
from .signal_details import (
    SIGNAL_DETAIL_LIMIT,
    select_signal_details,
    signal_detail_stats,
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

# Indices where a *higher* reading is the bad one, so the status thresholds
# above apply to the flipped z. Everything else in the catalog reads
# higher-is-healthier.
#
#   msi  — SWIR1/NIR ratio, higher = drier leaf (see indices.computation.msi)
#   bsi  — bare-soil index, higher = less canopy over the soil
#   lst  — land-surface temperature in °C, higher = hotter
#   cwsi — crop water stress index, higher = more stress
#
# `smi` is *not* here: it is scaled 0 (dry edge) to 1 (wet edge), so higher is
# wetter, which is the normal polarity.
INVERTED_INDEX_CODES: frozenset[str] = frozenset({"msi", "bsi", "lst", "cwsi"})


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

    # ---- Custom (tenant-defined) report columns ------------------------

    async def get_custom_fields(self, *, farm_id: UUID) -> CustomFieldsResponse:
        """The column picker's menu for one farm.

        Goes through `_load_farm` like every report, so an unknown farm 404s
        here rather than returning an empty picker that reads as "this farm has
        no custom fields".
        """
        await self._load_farm(farm_id)
        return CustomFieldsResponse(
            farm_id=farm_id,
            fields=await list_custom_fields(self._session, farm_id=farm_id),
        )

    async def _load_custom(
        self, *, farm_id: UUID, refs: list[CustomFieldRef], period: ReportPeriod
    ) -> dict[UUID, dict[str, CustomFieldValue]]:
        """``{block_id: {ref_key: value}}`` for the picked columns, or ``{}``.

        Thin passthrough so every block-grained report asks for its custom
        columns the same way, and so the "no columns picked, no query" short
        circuit lives in one place.
        """
        return await load_custom_values(
            self._session,
            farm_id=farm_id,
            refs=refs,
            since=period.since,
            until=period.until,
        )

    async def _custom_field_defs(
        self, *, farm_id: UUID, refs: list[CustomFieldRef]
    ) -> list[CustomFieldDef]:
        """The picked columns' definitions, in the order the caller asked for.

        Resolved from the farm's catalog rather than echoed back from the
        param, so the response carries the label, unit and option list the FE
        needs to render a header and a cell. A ref naming a definition that no
        longer resolves on this farm is dropped here — the same
        outlives-its-definition tolerance `parse_field_refs` applies.
        """
        if not refs:
            return []
        available = {d.key: d for d in await list_custom_fields(self._session, farm_id=farm_id)}
        return [available[ref.key] for ref in refs if ref.key in available]

    # ---- PR-1: Seasonal Crop Health ------------------------------------

    async def get_crop_health_report(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        since: datetime | None,
        until: datetime | None,
        crop_path: str | None = None,
        fields: str | None = None,
    ) -> CropHealthReportResponse:
        """Per-block vegetation summary for one index over the window.

        One SQL pass collects window aggregates + the latest scene's
        spatial percentiles + baseline z per block; blocks with no scene
        in the window still appear (with null metrics) so the report
        lists the whole farm. Status is derived from the latest z so it
        is index-agnostic.

        When ``crop_path`` is given, only blocks whose current crop falls
        under that taxonomy path prefix are included (``mango`` = every
        Mango block, ``mango.alphonso.short`` = exactly Short Alphonso);
        blocks with no crop are dropped while a filter is active."""
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
        refs = parse_field_refs(fields)
        custom = await self._load_custom(farm_id=farm_id, refs=refs, period=period)

        if crop_path:
            blocks = [
                b for b in blocks if path_matches(crop_path, _crop_path_of(crops.get(b["id"])))
            ]

        rows: list[CropHealthBlockRow] = []
        counts = {"normal": 0, "watch": 0, "stressed": 0, "unknown": 0}
        value_sum = Decimal(0)
        value_n = 0
        with_data = 0

        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            block_name_ar = block.get("name_ar") or None
            s = stats.get(block_id)
            crop = crops.get(block_id)

            if s is None:
                status: CropHealthStatus = "unknown"
                counts["unknown"] += 1
                rows.append(
                    CropHealthBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        block_name_ar=block_name_ar,
                        crop_name_en=crop[0] if crop else None,
                        crop_name_ar=crop[1] if crop else None,
                        crop_path=(crop[2] or None) if crop else None,
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
                        custom=custom.get(block_id, {}),
                    )
                )
                continue

            with_data += 1
            z = s["last_z"]
            status = _status_from_z(z, index_code=index_code)
            counts[status] += 1
            last_value = s["last_mean"]
            if last_value is not None:
                value_sum += last_value
                value_n += 1

            rows.append(
                CropHealthBlockRow(
                    block_id=block_id,
                    block_name=block_name,
                    block_name_ar=block_name_ar,
                    crop_name_en=crop[0] if crop else None,
                    crop_name_ar=crop[1] if crop else None,
                    crop_path=(crop[2] or None) if crop else None,
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
                    custom=custom.get(block_id, {}),
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
            farm_name_ar=farm.get("name_ar"),
            index_code=index_code,
            period=period,
            crop_path=crop_path,
            blocks=rows,
            summary=summary,
            custom_fields=await self._custom_field_defs(farm_id=farm_id, refs=refs),
        )

    # ---- PR-2: Field Variability / Zone Anomaly ------------------------

    async def get_zone_anomaly_report(
        self,
        *,
        farm_id: UUID,
        index_code: str,
        since: datetime | None,
        until: datetime | None,
        fields: str | None = None,
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
        refs = parse_field_refs(fields)
        custom = await self._load_custom(farm_id=farm_id, refs=refs, period=period)

        rows: list[ZoneAnomalyBlockRow] = []
        total_flagged_cells = 0
        total_flagged_area = Decimal(0)
        blocks_with_anomalies = 0

        for block in blocks:
            block_id = block["id"]
            block_name = block.get("name") or block.get("code") or str(block_id)
            block_name_ar = block.get("name_ar") or None
            s = stats.get(block_id)

            if s is None:
                status: ZoneAnomalyStatus = "no_data" if block_id in gridded else "no_grid"
                rows.append(
                    ZoneAnomalyBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        block_name_ar=block_name_ar,
                        status=status,
                        scene_time=None,
                        cell_count=0,
                        flagged_count=0,
                        flagged_area_ha=None,
                        worst_z=None,
                        block_mean=None,
                        block_std=None,
                        threshold_k=None,
                        custom=custom.get(block_id, {}),
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
                    block_name_ar=block_name_ar,
                    status=status,
                    scene_time=s["scene_time"],
                    cell_count=cell_count,
                    flagged_count=flagged,
                    flagged_area_ha=area_ha,
                    worst_z=_q2(s["worst_z"]),
                    block_mean=_q3(s["bmean"]),
                    block_std=_q3(bstd),
                    threshold_k=s["z_thr"],
                    custom=custom.get(block_id, {}),
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
            farm_name_ar=farm.get("name_ar"),
            index_code=index_code,
            period=period,
            blocks=rows,
            summary=summary,
            custom_fields=await self._custom_field_defs(farm_id=farm_id, refs=refs),
        )

    # ---- PR-3: Irrigation & Water Balance ------------------------------

    async def get_water_balance_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
        fields: str | None = None,
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
        refs = parse_field_refs(fields)
        custom = await self._load_custom(farm_id=farm_id, refs=refs, period=period)

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
            block_name_ar = block.get("name_ar") or None
            s = sched.get(block_id)
            if s is None:
                rows.append(
                    WaterBalanceBlockRow(
                        block_id=block_id,
                        block_name=block_name,
                        block_name_ar=block_name_ar,
                        scheduled_count=0,
                        applied_count=0,
                        skipped_count=0,
                        pending_count=0,
                        recommended_mm_total=None,
                        applied_mm_total=None,
                        adherence_pct=None,
                        last_scheduled_for=None,
                        custom=custom.get(block_id, {}),
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
                    block_name_ar=block_name_ar,
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
                    custom=custom.get(block_id, {}),
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
            farm_name_ar=farm.get("name_ar"),
            period=period,
            weather=weather,
            blocks=rows,
            summary=summary,
            custom_fields=await self._custom_field_defs(farm_id=farm_id, refs=refs),
        )

    # ---- PR-R5: Disease & Pest Pressure -------------------------------

    async def get_weather_risk_pressure_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
        fields: str | None = None,
    ) -> WeatherRiskPressureReportResponse:
        """Per-(block, pathogen) disease/pest pressure over the window.

        One row per block-pathogen that has any scored day, carrying the
        peak/mean score, the day counts at each banding, and the most recent
        scored day so the FE shows current state next to the peak. Sorted
        worst-first (latest level, then peak). Blocks with no scored risk in
        the window simply do not appear."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)
        blocks = await self._list_active_blocks(farm_id)
        name_by_id = {
            b["id"]: (
                b.get("name") or b.get("code") or str(b["id"]),
                b.get("name_ar") or None,
            )
            for b in blocks
        }

        data = await _select_weather_risk_pressure(
            self._session,
            farm_id=farm_id,
            since=period.since.date(),
            until=period.until.date(),
        )
        refs = parse_field_refs(fields)
        custom = await self._load_custom(farm_id=farm_id, refs=refs, period=period)

        rows: list[WeatherRiskPressureRow] = []
        blocks_at_risk: set[UUID] = set()
        pathogens: set[str] = set()
        total_high_days = 0
        for d in data:
            block_id = d["block_id"]
            pathogens.add(d["risk_code"])
            total_high_days += d["days_high"]
            if d["latest_level"] in ("moderate", "high") or d["days_high"] > 0:
                blocks_at_risk.add(block_id)
            rows.append(
                WeatherRiskPressureRow(
                    block_id=block_id,
                    block_name=name_by_id.get(block_id, (str(block_id), None))[0],
                    block_name_ar=name_by_id.get(block_id, (str(block_id), None))[1],
                    risk_code=d["risk_code"],
                    days_observed=d["days_observed"],
                    peak_score=d["peak_score"],
                    mean_score=d["mean_score"],
                    days_high=d["days_high"],
                    days_moderate=d["days_moderate"],
                    latest_level=d["latest_level"],
                    latest_score=d["latest_score"],
                    latest_date=d["latest_date"],
                    # Every row of one block repeats that block's custom
                    # values — the grain here is (block, pathogen), and a
                    # crop attribute has no pathogen dimension to vary over.
                    custom=custom.get(block_id, {}),
                )
            )

        # Worst-first: current level, then peak score, then block name.
        _level_rank = {"high": 2, "moderate": 1, "low": 0}
        rows.sort(
            key=lambda r: (-_level_rank[r.latest_level], -r.peak_score, r.block_name),
        )

        summary = WeatherRiskPressureSummary(
            block_count=len({d["block_id"] for d in data}),
            pathogen_count=len(pathogens),
            blocks_at_risk=len(blocks_at_risk),
            total_high_days=total_high_days,
            row_count=len(rows),
        )
        return WeatherRiskPressureReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            farm_name_ar=farm.get("name_ar"),
            period=period,
            rows=rows,
            summary=summary,
            custom_fields=await self._custom_field_defs(farm_id=farm_id, refs=refs),
        )

    # ---- PR-4: Weather & Growing-Degree-Days Summary -------------------

    async def get_weather_summary_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
        crop_path: str | None = None,
    ) -> WeatherSummaryReportResponse:
        """Farm temperature / rainfall / ET₀ / GDD roll-up plus the daily
        series for charting and the current-crop agronomic context.

        The weather series is farm-level, so ``crop_path`` narrows only
        the crop context list (and its block counts) to crops under that
        taxonomy path prefix — the reader can then judge accumulated GDD
        against just the variety/strain they care about."""
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)

        rows = await _select_weather_daily(
            self._session, farm_id=farm_id, since=period.since.date(), until=period.until.date()
        )
        crops = await _select_weather_crop_context(
            self._session, farm_id=farm_id, crop_path=crop_path
        )

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
                temp_anomaly_z=r["temp_anomaly_z"],
                precip_anomaly_z=r["precip_anomaly_z"],
                et0_anomaly_z=r["et0_anomaly_z"],
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
            farm_name_ar=farm.get("name_ar"),
            period=period,
            crop_path=crop_path,
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
                    block_name_ar=a.get("block_name_ar"),
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
                    block_name_ar=al.get("block_name_ar"),
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
                    block_name_ar=rc.get("block_name_ar"),
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
            farm_name_ar=farm.get("name_ar"),
            period=period,
            entries=entries,
            summary=summary,
        )

    # ---- PR-R6: Signal Details -----------------------------------------

    async def get_signal_details_report(
        self,
        *,
        farm_id: UUID,
        since: datetime | None,
        until: datetime | None,
        signal_codes: list[str] | None = None,
        block_ids: list[UUID] | None = None,
        categorical_values: list[str] | None = None,
        min_value: Decimal | None = None,
        max_value: Decimal | None = None,
        recorded_by: UUID | None = None,
        location_mode: str | None = None,
        with_notes_only: bool = False,
        with_attachment_only: bool = False,
        limit: int = SIGNAL_DETAIL_LIMIT,
    ) -> SignalDetailsReportResponse:
        """Every signal observation on the farm that matches the filters.

        The one report whose rows are observations rather than blocks. Custom
        signals were previously only ever visible collapsed to one value per
        block, which cannot answer "what did the scouts actually record" — the
        four readings that produced today's average, who took them, and what
        they wrote in the notes.

        Rows are newest-first and capped at ``limit``. The per-signal stats are
        computed over the **returned** rows, and ``summary.truncated`` says
        when that is a partial view: an average taken over a cut-off page,
        presented as the period's average, is the kind of number somebody makes
        an irrigation decision on.

        ``block_ids`` is not re-checked against the farm; the SQL is already
        farm-scoped, so a block id from another farm simply matches nothing
        rather than leaking a row.
        """
        farm = await self._load_farm(farm_id)
        period = resolve_period(since, until)

        # Fetch one extra row to tell "exactly at the cap" from "cut off",
        # rather than reporting every full page as truncated.
        raw = await select_signal_details(
            self._session,
            farm_id=farm_id,
            since=period.since,
            until=period.until,
            signal_codes=signal_codes or [],
            block_ids=block_ids or [],
            categorical_values=categorical_values or [],
            min_value=min_value,
            max_value=max_value,
            recorded_by=recorded_by,
            location_mode=location_mode,
            with_notes_only=with_notes_only,
            with_attachment_only=with_attachment_only,
            limit=limit + 1,
        )
        truncated = len(raw) > limit
        raw = raw[:limit]

        rows = [
            SignalDetailRow(
                observation_id=r["id"],
                observed_at=r["observed_at"],
                recorded_at=r["recorded_at"],
                signal_code=r["signal_code"],
                signal_name=r["signal_name"],
                signal_name_ar=r["signal_name_ar"],
                value_kind=r["value_kind"],
                unit=r["unit"],
                unit_ar=r["unit_ar"],
                categorical_values=r["categorical_values"],
                categorical_values_ar=r["categorical_values_ar"],
                value_numeric=r["value_numeric"],
                value_categorical=r["value_categorical"],
                value_event=r["value_event"],
                value_boolean=r["value_boolean"],
                block_id=r["block_id"],
                block_name=r["block_name"],
                block_name_ar=r["block_name_ar"],
                crop_path=r["crop_path"] or None,
                notes=r["notes"],
                recorded_by=r["recorded_by"],
                recorded_by_name=r["recorded_by_name"],
                recorded_by_name_ar=r["recorded_by_name_ar"],
                location_mode=r["location_mode"],
                has_attachment=r["attachment_s3_key"] is not None,
                template_observation_id=r["template_observation_id"],
                import_batch_id=r["import_batch_id"],
            )
            for r in raw
        ]

        stats = signal_detail_stats(rows)
        summary = SignalDetailSummary(
            observation_count=len(rows),
            signal_count=len(stats),
            block_count=len({r.block_id for r in rows if r.block_id is not None}),
            recorder_count=len({r.recorded_by for r in rows}),
            truncated=truncated,
        )
        return SignalDetailsReportResponse(
            farm_id=farm_id,
            farm_name=farm["name"],
            farm_name_ar=farm.get("name_ar"),
            period=period,
            filters=SignalDetailFilters(
                signal_codes=list(signal_codes or []),
                block_ids=list(block_ids or []),
                categorical_values=list(categorical_values or []),
                min_value=min_value,
                max_value=max_value,
                recorded_by=recorded_by,
                location_mode=location_mode,
                with_notes_only=with_notes_only,
                with_attachment_only=with_attachment_only,
            ),
            rows=rows,
            stats=stats,
            summary=summary,
        )


def get_reports_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> ReportsService:
    return ReportsService(tenant_session=tenant_session, public_session=public_session)


# --- module-level helpers ---------------------------------------------------


def _crop_path_of(crop: tuple[str, str | None, str] | None) -> str | None:
    """Pull the crop_path out of a (name_en, name_ar, crop_path) tuple,
    or None when the block has no current crop — keeps the crop-health
    filter readable."""
    return crop[2] if crop else None


def _status_from_z(z: Decimal | None, *, index_code: str = "ndvi") -> CropHealthStatus:
    """Map a baseline z-score to a vegetation status.

    For the higher-is-healthier majority only the negative side (below normal)
    is a concern. For the four inverted indices the concern is *above* normal,
    so the z is flipped before the thresholds are applied — the reported
    `baseline_z` stays raw, because a sign-flipped number under a column
    headed "Baseline z" would disagree with the same block's trend chart.

    Getting this wrong is not cosmetic: without the flip, the hottest, driest
    block on the farm reads "Normal" and the coolest reads "Stressed".

    >>> _status_from_z(Decimal("-2.5"))
    'stressed'
    >>> _status_from_z(Decimal("-2.5"), index_code="lst")
    'normal'
    >>> _status_from_z(Decimal("2.5"), index_code="cwsi")
    'stressed'
    """
    if z is None:
        return "unknown"
    effective = -z if index_code in INVERTED_INDEX_CODES else z
    if effective <= _Z_STRESSED:
        return "stressed"
    if effective <= _Z_WATCH:
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


async def _select_weather_risk_pressure(
    session: AsyncSession,
    *,
    farm_id: UUID,
    since: date,
    until: date,
) -> list[dict[str, Any]]:
    """Per-(block, pathogen) pressure aggregates over the window, joined to
    the latest scored day. Returns one dict per block-pathogen with any
    scored day; blocks/pathogens absent from the window are simply omitted."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        WITH scoped AS (
            SELECT r.block_id, r.risk_code, r.date, r.score, r.level
            FROM weather_risk_daily r
            JOIN blocks b ON b.id = r.block_id AND b.deleted_at IS NULL
            WHERE b.farm_id = :farm_id
              AND r.date >= :since AND r.date <= :until
        ),
        agg AS (
            SELECT block_id, risk_code,
                   count(*) AS days_observed,
                   max(score) AS peak_score,
                   round(avg(score))::int AS mean_score,
                   count(*) FILTER (WHERE level = 'high') AS days_high,
                   count(*) FILTER (WHERE level = 'moderate') AS days_moderate
            FROM scoped GROUP BY block_id, risk_code
        ),
        latest AS (
            SELECT DISTINCT ON (block_id, risk_code)
                   block_id, risk_code,
                   level AS latest_level, score AS latest_score, date AS latest_date
            FROM scoped ORDER BY block_id, risk_code, date DESC
        )
        SELECT a.block_id, a.risk_code, a.days_observed, a.peak_score, a.mean_score,
               a.days_high, a.days_moderate,
               l.latest_level, l.latest_score, l.latest_date
        FROM agg a JOIN latest l USING (block_id, risk_code)
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(row) for row in result.mappings().all()]


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
) -> dict[UUID, tuple[str, str | None, str]]:
    """Current crop (name_en, name_ar, crop_path) per block for a farm.
    Only the is_current assignment is returned; blocks with none are
    absent. ``crop_path`` backs the crop-taxonomy report filter."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    sql = text(
        """
        SELECT bc.block_id, c.name_en, c.name_ar, bc.crop_path
        FROM block_crops bc
        JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
        JOIN public.crops c ON c.id = bc.crop_id
        WHERE b.farm_id = :farm_id
          AND bc.deleted_at IS NULL
          AND bc.is_current IS TRUE
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id})
    return {
        row["block_id"]: (row["name_en"], row["name_ar"], row["crop_path"] or "")
        for row in result.mappings().all()
    }


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
        -- Observations are tied to a config through `grid_cells`, not by
        -- (block_id, product_id): those two columns are stable across a
        -- rezone, so pairing on them would let a retired geometry's rows
        -- be scored against the current geometry's threshold. Valid time
        -- (tenant migration 0054) selects the geometry that actually
        -- produced each scene.
        WITH cfg AS (
            SELECT gc.id AS config_id, gc.block_id, gc.product_id,
                   gc.effective_from, gc.effective_to,
                   COALESCE(gc.anomaly_z_threshold, CAST(:default_k AS numeric)) AS z_thr
            FROM grid_configs gc
            JOIN blocks b ON b.id = gc.block_id AND b.deleted_at IS NULL
            WHERE b.farm_id = :farm_id
              AND gc.deleted_at IS NULL
              AND gc.superseded_at IS NULL
        ),
        obs AS (
            SELECT a.block_id, a.product_id, a.time, a.mean,
                   gcell.area_m2, cfg.z_thr
            FROM block_grid_aggregates a
            JOIN grid_cells gcell ON gcell.id = a.cell_id
            JOIN cfg
              ON cfg.config_id = gcell.grid_config_id
             AND tstzrange(cfg.effective_from, cfg.effective_to) @> a.time
            WHERE a.index_code = :index_code AND a.mean IS NOT NULL
        ),
        latest_scene AS (
            SELECT DISTINCT ON (block_id)
                   block_id, product_id, time AS scene_time, z_thr
            FROM obs
            WHERE time >= :since AND time <= :until
            ORDER BY block_id, time DESC
        ),
        cells AS (
            SELECT o.block_id, o.mean, o.area_m2, ls.scene_time, ls.z_thr
            FROM obs o
            JOIN latest_scene ls
              ON ls.block_id = o.block_id
             AND ls.product_id = o.product_id
             AND ls.scene_time = o.time
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


# z-score at/above which a day counts as a climatology anomaly (~2 sigma,
# i.e. outside the 95% seasonal band). Matches the Insights strip's
# "critical" anomaly chip (|z| >= 2) so report and map tell one story.
_ANOMALY_Z = Decimal("2")


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

    # Anomaly roll-up (PR-W6). `days_with_anomaly` is how many days had any
    # z-score at all (the climatology covered them); the per-index counts
    # are days that ran >=2 sigma hot / above-normal ET. All None when the
    # window predates baselines so the FE hides the row instead of 0s.
    temp_z = _vals("temp_anomaly_z")
    et0_z = _vals("et0_anomaly_z")
    has_any_z = bool(temp_z or et0_z or _vals("precip_anomaly_z"))
    days_with_anomaly = (
        sum(
            1
            for r in rows
            if r.get("temp_anomaly_z") is not None
            or r.get("et0_anomaly_z") is not None
            or r.get("precip_anomaly_z") is not None
        )
        if has_any_z
        else None
    )

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
        days_with_anomaly=days_with_anomaly,
        heat_anomaly_days=(sum(1 for z in temp_z if z >= _ANOMALY_Z) if temp_z else None),
        et0_anomaly_days=(sum(1 for z in et0_z if z >= _ANOMALY_Z) if et0_z else None),
    )


async def _select_weather_daily(
    session: AsyncSession, *, farm_id: UUID, since: date, until: date
) -> list[dict[str, Any]]:
    """Daily derived weather rows for a farm over the window, oldest
    first — both the chart series and the source for window stats."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    # LEFT JOIN the first-class weather-index z-scores (PR-W6) per day so
    # the report can surface anomalies against the seasonal climatology.
    # Joins stay NULL until the baseline sweep has ≥3 samples/DOY — the
    # report then just shows blank anomaly cells, never errors.
    sql = text(
        """
        SELECT wdd.date, wdd.temp_min_c, wdd.temp_max_c, wdd.temp_mean_c,
               wdd.precip_mm_daily, wdd.et0_mm_daily,
               wdd.gdd_base10, wdd.gdd_cumulative_base10_season,
               t.baseline_deviation AS temp_anomaly_z,
               r.baseline_deviation AS precip_anomaly_z,
               e.baseline_deviation AS et0_anomaly_z
        FROM weather_derived_daily wdd
        LEFT JOIN weather_index_daily t
          ON t.farm_id = wdd.farm_id AND t.date = wdd.date
          AND t.index_code = 'temperature'
        LEFT JOIN weather_index_daily r
          ON r.farm_id = wdd.farm_id AND r.date = wdd.date
          AND r.index_code = 'rainfall'
        LEFT JOIN weather_index_daily e
          ON e.farm_id = wdd.farm_id AND e.date = wdd.date
          AND e.index_code = 'evapotranspiration'
        WHERE wdd.farm_id = :farm_id AND wdd.date >= :since AND wdd.date <= :until
        ORDER BY wdd.date ASC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]


async def _select_weather_crop_context(
    session: AsyncSession, *, farm_id: UUID, crop_path: str | None = None
) -> list[dict[str, Any]]:
    """Current crops on the farm with their GDD base temp + default
    season length, for interpreting the accumulated GDD.

    ``crop_path`` (optional) restricts to block assignments under that
    hierarchical taxonomy prefix — exact path or any descendant — so the
    block counts reflect only the matching variety/strain."""
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
          AND (
              -- Cast the bind so asyncpg can infer the parameter type; an
              -- untyped NULL/`|| '.%'` bind raises AmbiguousParameterError.
              CAST(:crop_path AS text) IS NULL
              OR bc.crop_path = CAST(:crop_path AS text)
              OR bc.crop_path LIKE CAST(:crop_path AS text) || '.%'
          )
        GROUP BY c.id, c.name_en, c.name_ar, c.gdd_base_temp_c, c.default_growing_season_days
        ORDER BY block_count DESC, c.name_en ASC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "crop_path": crop_path})
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
               COALESCE(b.name, b.code) AS block_name,
               NULLIF(b.name_ar, '') AS block_name_ar
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
               COALESCE(b.name, b.code) AS block_name,
               NULLIF(b.name_ar, '') AS block_name_ar
        FROM alerts a
        JOIN blocks b ON b.id = a.block_id AND b.deleted_at IS NULL
        WHERE b.farm_id = :farm_id
          -- A grouped alert is one finding; its per-cell members would repeat
          -- the same sentence down the page.
          AND a.group_parent_id IS NULL
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
               COALESCE(b.name, b.code) AS block_name,
               NULLIF(b.name_ar, '') AS block_name_ar
        FROM recommendations r
        JOIN blocks b ON b.id = r.block_id AND b.deleted_at IS NULL
        WHERE r.farm_id = :farm_id
          AND r.group_parent_id IS NULL
          AND r.created_at >= :since AND r.created_at <= :until
        ORDER BY r.created_at DESC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    result = await session.execute(sql, {"farm_id": farm_id, "since": since, "until": until})
    return [dict(r) for r in result.mappings().all()]
