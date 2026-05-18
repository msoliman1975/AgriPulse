"""Insights HTTP surface — two read endpoints under /api/v1/farms.

Mount path lives under farms so the FE can build URLs from a single
farm_id without round-tripping; the module-internal organisation
(separate router from farms/router.py) keeps the insights composition
isolated for testing and future expansion (B.3 annotations, etc.).
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
    FarmAlertTrendResponse,
    FarmAnnotationsResponse,
    FarmHealthSummaryResponse,
    FarmIndexTimeseriesResponse,
    FarmSeasonContextResponse,
    TimeseriesGranularity,
)
from .service import InsightsService, get_insights_service

router = APIRouter(prefix="/api/v1", tags=["insights"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> InsightsService:
    return get_insights_service(tenant_session=tenant_session, public_session=public_session)


def _ensure_tenant(context: RequestContext) -> str:
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
    "/farms/{farm_id}/index-timeseries",
    response_model=FarmIndexTimeseriesResponse,
    summary="Per-block index timeseries for one farm (B.2).",
)
async def get_farm_index_timeseries(
    farm_id: UUID,
    index_code: str = Query(default="ndvi", min_length=1, max_length=64),
    granularity: TimeseriesGranularity = Query(default="daily"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    # `index.read` is the existing capability gating the per-block
    # timeseries endpoint. Same scope applies here — operator who can
    # see one block's indices can see them all on the same farm.
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: InsightsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_farm_index_timeseries(
        farm_id=farm_id,
        index_code=index_code,
        granularity=granularity,
        since=since,
        until=until,
    )
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/health-summary",
    response_model=FarmHealthSummaryResponse,
    summary="Per-block health scorecard for one farm (B.2).",
)
async def get_farm_health_summary(
    farm_id: UUID,
    # `farm.read` + index/alert reads are implicit (the same operator
    # who can open a farm can see its summary). farm.read is the
    # cheapest gate that covers the path-param farm_id.
    context: RequestContext = Depends(requires_capability("farm.read", farm_id_param="farm_id")),
    service: InsightsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_farm_health_summary(farm_id=farm_id)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/insights-annotations",
    response_model=FarmAnnotationsResponse,
    summary="Vertical markers for the farm trend chart (B.3).",
)
async def get_farm_annotations(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    context: RequestContext = Depends(requires_capability("alert.read", farm_id_param="farm_id")),
    service: InsightsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_farm_annotations(farm_id=farm_id, since=since, until=until)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/season-context",
    response_model=FarmSeasonContextResponse,
    summary="Crop mix + block counts for the season-context bar (B.3).",
)
async def get_farm_season_context(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("farm.read", farm_id_param="farm_id")),
    service: InsightsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_farm_season_context(farm_id=farm_id)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/alert-trend",
    response_model=FarmAlertTrendResponse,
    summary="Daily open-alert count for the alerts KPI sparkline (B.3).",
)
async def get_farm_alert_trend(
    farm_id: UUID,
    days: int = Query(default=7, ge=1, le=90),
    context: RequestContext = Depends(requires_capability("alert.read", farm_id_param="farm_id")),
    service: InsightsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_farm_alert_trend(farm_id=farm_id, days=days)
    return out.model_dump(mode="json")
