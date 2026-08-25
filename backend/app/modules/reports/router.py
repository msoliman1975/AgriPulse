"""Reports HTTP surface — read-only farm reports under /api/v1/farms.

Mounted under farms (like insights) so the FE builds every report URL
from a single farm_id. Each report is one GET endpoint added below the
shared dependency helpers as its PR lands; PR-0 ships the module
skeleton (router + session/tenant wiring) the five reports plug into.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

from .custom_fields import MAX_CUSTOM_FIELDS
from .schemas import (
    CropHealthReportResponse,
    CustomFieldsResponse,
    OperationsLogReportResponse,
    SignalDetailsReportResponse,
    WaterBalanceReportResponse,
    WeatherRiskPressureReportResponse,
    WeatherSummaryReportResponse,
    ZoneAnomalyReportResponse,
)
from .service import ReportsService, get_reports_service
from .signal_details import LOCATION_MODES, SIGNAL_DETAIL_LIMIT

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


# Tenant-defined report columns. One query param rather than a repeated one so
# the order the user arranged the columns in survives the round trip, and so a
# report URL stays short enough to paste.
_FIELDS_QUERY = Query(
    default=None,
    max_length=1024,
    description=(
        "Comma-separated custom columns as `source:code` — e.g. "
        "`crop_attribute:brix,signal:trap_count`. Sources: `crop_attribute`, "
        f"`signal`. At most {MAX_CUSTOM_FIELDS} are honoured; unknown entries "
        "are ignored rather than rejected, so a saved report URL survives a "
        "retired definition. List what a farm offers at "
        "`GET /farms/{farm_id}/reports/custom-fields`."
    ),
)


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
    crop_path: str | None = Query(
        default=None,
        max_length=256,
        description="Crop-taxonomy path prefix filter, e.g. 'mango' / "
        "'mango.alphonso' / 'mango.alphonso.short'.",
    ),
    fields: str | None = _FIELDS_QUERY,
    # Same gate as the insights index endpoints — an operator who can
    # read one block's indices can read the farm report.
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_crop_health_report(
        farm_id=farm_id,
        index_code=index_code,
        since=since,
        until=until,
        crop_path=crop_path,
        fields=fields,
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
    fields: str | None = _FIELDS_QUERY,
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_zone_anomaly_report(
        farm_id=farm_id, index_code=index_code, since=since, until=until, fields=fields
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
    fields: str | None = _FIELDS_QUERY,
    context: RequestContext = Depends(
        requires_capability("irrigation.schedule.read", farm_id_param="farm_id")
    ),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_water_balance_report(
        farm_id=farm_id, since=since, until=until, fields=fields
    )
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/weather-risk-pressure",
    response_model=WeatherRiskPressureReportResponse,
    summary="Disease & pest pressure — per-block pathogen risk over the window (PR-R5).",
)
async def get_weather_risk_pressure_report(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    fields: str | None = _FIELDS_QUERY,
    context: RequestContext = Depends(
        requires_capability("weather_risk.read", farm_id_param="farm_id")
    ),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_weather_risk_pressure_report(
        farm_id=farm_id, since=since, until=until, fields=fields
    )
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
    crop_path: str | None = Query(
        default=None,
        max_length=256,
        description="Crop-taxonomy path prefix filter for the crop context, "
        "e.g. 'mango' / 'mango.alphonso' / 'mango.alphonso.short'.",
    ),
    context: RequestContext = Depends(requires_capability("weather.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_weather_summary_report(
        farm_id=farm_id, since=since, until=until, crop_path=crop_path
    )
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


@router.get(
    "/farms/{farm_id}/reports/custom-fields",
    response_model=CustomFieldsResponse,
    summary="Custom report columns available on a farm (crop attributes + signals).",
)
async def get_report_custom_fields(
    farm_id: UUID,
    # `index.read` rather than a capability of its own. This lists the *names*
    # of a farm's tenant-defined fields, which is strictly less than what every
    # report already returns, and anyone who can open a report needs it to
    # build the column picker.
    context: RequestContext = Depends(requires_capability("index.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_custom_fields(farm_id=farm_id)
    return out.model_dump(mode="json")


@router.get(
    "/farms/{farm_id}/reports/signal-details",
    response_model=SignalDetailsReportResponse,
    summary="Signal details — every custom-signal observation, filtered (PR-R6).",
)
async def get_signal_details_report(
    farm_id: UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    # Repeated params rather than one comma-separated string: these are
    # multi-select filters, not an ordered column list, and a signal code may
    # legitimately contain characters a split would mangle.
    signal_code: list[str] = Query(default_factory=list, max_length=32),
    block_id: list[UUID] = Query(default_factory=list, max_length=64),
    value: list[str] = Query(
        default_factory=list,
        max_length=32,
        description="Categorical / event values to keep. Matches either column.",
    ),
    min_value: Decimal | None = Query(default=None, description="Numeric signals only."),
    max_value: Decimal | None = Query(default=None, description="Numeric signals only."),
    recorded_by: UUID | None = Query(default=None, description="Filter to one recorder."),
    location_mode: str | None = Query(
        default=None,
        description="One of entity | point_in_entity | free_point.",
    ),
    with_notes_only: bool = Query(default=False),
    with_attachment_only: bool = Query(default=False),
    limit: int = Query(default=SIGNAL_DETAIL_LIMIT, ge=1, le=SIGNAL_DETAIL_LIMIT),
    context: RequestContext = Depends(requires_capability("signal.read", farm_id_param="farm_id")),
    service: ReportsService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    if location_mode is not None and location_mode not in LOCATION_MODES:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unknown location mode",
            detail=f"location_mode must be one of {', '.join(LOCATION_MODES)}.",
            type_="https://agripulse.cloud/problems/invalid-filter",
        )
    out = await service.get_signal_details_report(
        farm_id=farm_id,
        since=since,
        until=until,
        signal_codes=signal_code,
        block_ids=block_id,
        categorical_values=value,
        min_value=min_value,
        max_value=max_value,
        recorded_by=recorded_by,
        location_mode=location_mode,
        with_notes_only=with_notes_only,
        with_attachment_only=with_attachment_only,
        limit=limit,
    )
    return out.model_dump(mode="json")
