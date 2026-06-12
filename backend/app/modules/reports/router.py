"""Reports HTTP surface — read-only farm reports under /api/v1/farms.

Mounted under farms (like insights) so the FE builds every report URL
from a single farm_id. Each report is one GET endpoint added below the
shared dependency helpers as its PR lands; PR-0 ships the module
skeleton (router + session/tenant wiring) the five reports plug into.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

from .schemas import (
    CropHealthReportResponse,
    OperationsLogReportResponse,
    WaterBalanceReportResponse,
    WeatherSummaryReportResponse,
    ZoneAnomalyReportResponse,
)
from .service import ReportsService, get_reports_service

router = APIRouter(prefix="/api/v1", tags=["reports"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> ReportsService:
    return get_reports_service(tenant_session=tenant_session, public_session=public_session)


def _ensure_tenant(context: RequestContext) -> str:
    """Reports are tenant-scoped; reject a platform-only JWT with 403
    rather than leaking an empty payload."""
    schema = context.tenant_schema
    if schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


@router.get(
    "/farms/{farm_id}/reports/crop-health",
    response_model=CropHealthReportResponse,
    summary="Seasonal crop-health report — per-block vegetation summary (PR-1).",
)
async def get_crop_health_report(
    farm_id: UUID,
    index_code: str = Query(default="ndvi", min_length=1, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    # Same gate as the insights index endpoints — an operator who can
    # read one block's indices can read the farm report.
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_crop_health_report(
        farm_id=farm_id, index_code=index_code, since=since, until=until
    )
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/zone-anomaly",
    response_model=ZoneAnomalyReportResponse,
    summary="Field-variability report — within-block grid anomalies (PR-2).",
)
async def get_zone_anomaly_report(
    farm_id: UUID,
    index_code: str = Query(default="ndvi", min_length=1, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_zone_anomaly_report(
        farm_id=farm_id, index_code=index_code, since=since, until=until
    )
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/water-balance",
    response_model=WaterBalanceReportResponse,
    summary="Irrigation & water-balance report — ET₀/rain vs applied (PR-3).",
)
async def get_water_balance_report(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    context: RequestContext = Depends(
        requires_capability("irrigation.schedule.read", farm_id_param="farm_id")
    ),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_water_balance_report(farm_id=farm_id, since=since, until=until)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/weather-summary",
    response_model=WeatherSummaryReportResponse,
    summary="Weather & GDD summary — temp/rain/ET₀/GDD over the window (PR-4).",
)
async def get_weather_summary_report(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    context: RequestContext = Depends(requires_capability("weather.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_weather_summary_report(farm_id=farm_id, since=since, until=until)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/operations-log",
    response_model=OperationsLogReportResponse,
    summary="Operations & agronomy log — activities, alerts, recs (PR-5).",
)
async def get_operations_log_report(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    context: RequestContext = Depends(requires_capability("plan.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_operations_log_report(farm_id=farm_id, since=since, until=until)
    return out.model_dump(mode="json")
