"""FastAPI routes for the weather module.

Mounted under /api/v1 by the app factory. Endpoints:

  POST   /blocks/{block_id}/weather/subscriptions
  GET    /blocks/{block_id}/weather/subscriptions
  DELETE /blocks/{block_id}/weather/subscriptions/{subscription_id}
  POST   /blocks/{block_id}/weather/refresh

The observations / forecasts / derived-daily read endpoints land in
PR-C alongside the derivations.

RBAC mirrors imagery: block-only routes resolve the farm via the
repository, then call `has_capability(..., farm_id=...)` manually.
A capability denial surfaces as 404 to avoid leaking block existence
across farm scopes.

Note: deliberately NO `from __future__ import annotations` (same
reason as imagery/router.py â€” FastAPI's TypeAdapter cannot resolve
string annotations on Request injection).
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.weather.errors import BlockNotVisibleError
from app.modules.weather.models import WeatherIndexCatalog, WeatherProvider
from app.modules.weather.repository import WeatherRepository
from app.modules.weather.schemas import (
    DerivedDailyRead,
    ForecastResponse,
    HourlyObservationRead,
    RefreshResponse,
    SubscriptionCreate,
    SubscriptionRead,
    WeatherIndexCatalogEntry,
    WeatherIndexSummaryResponse,
    WeatherIndexTimeseriesResponse,
    WeatherProviderRead,
    WeatherRiskSummaryResponse,
    WeatherRiskTimeseriesResponse,
)
from app.modules.weather.service import WeatherServiceImpl, get_weather_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability, requires_capability

# Canonical order for the summary response (matches the catalog sort_order).
# Anything missing here is dropped from the strip no matter how well the
# rest of the pipeline computes it — which is exactly what happened to
# `humidity` between public migration 0049 seeding it as the eighth index
# and this tuple being left at seven.
_WEATHER_INDEX_ORDER: tuple[str, ...] = (
    "temperature",
    "radiation",
    "wind",
    "rainfall",
    "evapotranspiration",
    "evaporation_coeff",
    "rain_et_balance",
    "humidity",  # sort_order 8 — appended by 0049, so it sorts last here too
    # sort_order 9-11, appended by 0057 (indices-guide gap audit).
    "leaf_wetness",
    "frost_risk",
    "heat_stress",
)
# Trailing window the farm summary scans for "latest + 7-day trend".
_SUMMARY_WINDOW_DAYS = 45

router = APIRouter(prefix="/api/v1", tags=["weather"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherServiceImpl:
    return get_weather_service(tenant_session=tenant_session)


def _correlation_id(request: Request) -> UUID | None:
    cid = getattr(request.state, "correlation_id", None)
    if isinstance(cid, str):
        try:
            return UUID(cid)
        except ValueError:
            return None
    if isinstance(cid, UUID):
        return cid
    return None


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


async def _resolve_farm_id(*, block_id: UUID, tenant_session: AsyncSession) -> UUID:
    """Look up the farm_id that owns this block; 404 if missing."""
    repo = WeatherRepository(tenant_session)
    block = await repo.get_block_farm_centroid(block_id)
    if block is None:
        raise BlockNotVisibleError(str(block_id))
    return block["farm_id"]


async def _guard_subscriptions_lock(*, tenant_session: AsyncSession, farm_id: UUID) -> None:
    """Reject writes when the farm's subscriptions category is locked.

    Gated by the farm-config feature flag. PR-3 of farm-block-config-model.
    """
    from app.core.settings import get_settings

    if not get_settings().farm_config_template_enabled:
        return
    from app.modules.farms import config_template

    await config_template.assert_category_unlocked(
        tenant_session, farm_id=farm_id, category="subscriptions"
    )


# --- Catalog ---------------------------------------------------------------


@router.get(
    "/weather/providers",
    response_model=list[WeatherProviderRead],
    summary="List active weather providers from public.weather_providers.",
)
async def list_weather_providers(
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> list[WeatherProviderRead]:
    """Catalog endpoint for the SPA's provider picker.

    Mirrors `/api/v1/config` (imagery): tenant scope is enough; the
    rows are platform-wide curated catalog data, not per-farm. Active
    rows only, ordered by name for stable picker order.
    """
    _ensure_tenant(context)
    rows = (
        (
            await tenant_session.execute(
                select(WeatherProvider)
                .where(WeatherProvider.is_active.is_(True))
                .order_by(WeatherProvider.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [WeatherProviderRead.model_validate(r) for r in rows]


@router.get(
    "/weather/indices/catalog",
    response_model=list[WeatherIndexCatalogEntry],
    summary="List the first-class weather indices from public.weather_indices_catalog.",
)
async def list_weather_index_catalog(
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> list[WeatherIndexCatalogEntry]:
    """Catalog endpoint for the SPA's weather-index picker + tooltips.

    Like the provider catalog, a tenant scope is enough — the rows are
    platform-wide curated data, not per-farm. Active rows only, ordered
    by `sort_order` for a stable picker.
    """
    _ensure_tenant(context)
    rows = (
        (
            await tenant_session.execute(
                select(WeatherIndexCatalog)
                .where(WeatherIndexCatalog.is_active.is_(True))
                .order_by(WeatherIndexCatalog.sort_order.asc())
            )
        )
        .scalars()
        .all()
    )
    return [WeatherIndexCatalogEntry.model_validate(r) for r in rows]


# --- Weather-index read surface (PR-W4) ------------------------------------


@router.get(
    "/farms/{farm_id}/weather-indices/{index_code}/timeseries",
    response_model=WeatherIndexTimeseriesResponse,
    summary="Daily weather-index series for a farm, with climatology band.",
)
async def get_weather_index_timeseries(
    farm_id: UUID,
    index_code: str,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    context: RequestContext = Depends(requires_capability("weather.read", farm_id_param="farm_id")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherIndexTimeseriesResponse:
    """One weather index's daily series for a farm over ``[from, to)``.

    Farm-scoped (weather is farm-centroid data); gated on ``weather.read``
    like the other weather reads. Each point carries the z-score plus the
    matching day-of-year baseline mean/std for the climatology band. An
    unknown ``index_code`` or a gap range simply yields no points.
    """
    _ensure_tenant(context)
    repo = WeatherRepository(tenant_session)
    rows = await repo.read_weather_index_timeseries(
        farm_id=farm_id, index_code=index_code, since=from_date, until=to_date
    )
    return WeatherIndexTimeseriesResponse.model_validate(
        {"farm_id": farm_id, "index_code": index_code, "points": list(rows)}
    )


@router.get(
    "/farms/{farm_id}/weather-indices/summary",
    response_model=WeatherIndexSummaryResponse,
    summary="Latest value + anomaly + 7-day trend for every weather index.",
)
async def get_weather_index_summary(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("weather.read", farm_id_param="farm_id")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherIndexSummaryResponse:
    """One row per weather index that has recent data for the farm — the
    map/dashboard "current state" strip. Indices stale beyond the trailing
    window are omitted (weather updates every few hours).

    Observed rows only — the repository filters forecast out, so "latest"
    stays the most recent day the farm actually lived through rather than
    the far end of the forecast horizon. The forward view is the
    timeseries endpoint, whose points are flagged.
    """
    _ensure_tenant(context)
    repo = WeatherRepository(tenant_session)
    since = datetime.now(UTC).date() - timedelta(days=_SUMMARY_WINDOW_DAYS)
    rows = await repo.read_weather_index_recent(farm_id=farm_id, since=since)

    by_code: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_code.setdefault(r["index_code"], []).append(r)

    entries: list[dict[str, Any]] = []
    for code in _WEATHER_INDEX_ORDER:
        series = by_code.get(code)
        if not series:
            continue
        latest = series[-1]  # rows are date-ascending
        ref_date = latest["date"] - timedelta(days=7)
        ref = next((row for row in reversed(series) if row["date"] <= ref_date), None)
        trend = (
            latest["value"] - ref["value"]
            if ref is not None and latest["value"] is not None and ref["value"] is not None
            else None
        )
        entries.append(
            {
                "index_code": code,
                "latest_date": latest["date"],
                "value": latest["value"],
                "zscore": latest["zscore"],
                "trend_7d_delta": trend,
            }
        )

    return WeatherIndexSummaryResponse.model_validate(
        {"farm_id": farm_id, "as_of": datetime.now(UTC), "indices": list(entries)}
    )


# --- Weather risk (Phase 2) ------------------------------------------------


@router.get(
    "/farms/{farm_id}/blocks/{block_id}/weather-risk/{risk_code}/timeseries",
    response_model=WeatherRiskTimeseriesResponse,
    summary="Daily disease/pest risk-score series for a block.",
)
async def get_weather_risk_timeseries(
    farm_id: UUID,
    block_id: UUID,
    risk_code: str,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    context: RequestContext = Depends(
        requires_capability("weather_risk.read", farm_id_param="farm_id")
    ),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherRiskTimeseriesResponse:
    """One pathogen's daily 0-100 risk series for a block over ``[from, to)``.

    Nested under the farm so RBAC is the farm-scoped ``weather_risk.read``; the
    repository's ``blocks`` join also enforces the block belongs to ``farm_id``
    (an empty series otherwise), so a caller cannot read across farm scopes.
    """
    _ensure_tenant(context)
    repo = WeatherRepository(tenant_session)
    rows = await repo.read_weather_risk_timeseries(
        farm_id=farm_id,
        block_id=block_id,
        risk_code=risk_code,
        since=from_date,
        until=to_date,
    )
    return WeatherRiskTimeseriesResponse.model_validate(
        {
            "farm_id": farm_id,
            "block_id": block_id,
            "risk_code": risk_code,
            "points": list(rows),
        }
    )


@router.get(
    "/farms/{farm_id}/weather-risk/summary",
    response_model=WeatherRiskSummaryResponse,
    summary="Latest disease/pest risk score per block per pathogen.",
)
async def get_weather_risk_summary(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("weather_risk.read", farm_id_param="farm_id")
    ),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherRiskSummaryResponse:
    """Map-overlay data: the most recent score per block per pathogen across
    the farm. Blocks with no risk rows yet simply do not appear.
    """
    _ensure_tenant(context)
    repo = WeatherRepository(tenant_session)
    rows = await repo.read_weather_risk_summary(farm_id=farm_id)
    return WeatherRiskSummaryResponse.model_validate(
        {"farm_id": farm_id, "as_of": datetime.now(UTC), "risks": list(rows)}
    )


# --- Subscriptions ---------------------------------------------------------


@router.post(
    "/blocks/{block_id}/weather/subscriptions",
    response_model=SubscriptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe a block to a weather provider.",
)
async def create_subscription(
    block_id: UUID,
    payload: SubscriptionCreate,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> SubscriptionRead:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    await _guard_subscriptions_lock(tenant_session=tenant_session, farm_id=farm_id)
    return await service.create_subscription(
        block_id=block_id,
        payload=payload,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/blocks/{block_id}/weather/subscriptions",
    response_model=list[SubscriptionRead],
    summary="List a block's weather subscriptions.",
)
async def list_subscriptions(
    block_id: UUID,
    include_inactive: bool = False,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[SubscriptionRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.list_subscriptions(block_id=block_id, include_inactive=include_inactive)
    return list(rows)


@router.delete(
    "/blocks/{block_id}/weather/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a weather subscription.",
)
async def revoke_subscription(
    block_id: UUID,
    subscription_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    await _guard_subscriptions_lock(tenant_session=tenant_session, farm_id=farm_id)
    await service.revoke_subscription(
        block_id=block_id,
        subscription_id=subscription_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


# --- Refresh --------------------------------------------------------------


@router.post(
    "/blocks/{block_id}/weather/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger weather fetch now.",
)
async def trigger_refresh(
    block_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.refresh", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    cid = _correlation_id(request)
    queued = await service.trigger_refresh(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=cid,
    )
    return {
        "queued_farm_ids": queued,
        "correlation_id": str(cid) if cid else None,
    }


# --- Reads ----------------------------------------------------------------


@router.get(
    "/blocks/{block_id}/weather/forecast",
    response_model=ForecastResponse,
    summary="Daily-aggregated forecast in the farm's local timezone.",
)
async def get_forecast(
    block_id: UUID,
    horizon_days: int = Query(default=5, ge=1, le=10),
    provider_code: str = Query(default="open_meteo"),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> ForecastResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.get_forecast(
        block_id=block_id,
        horizon_days=horizon_days,
        provider_code=provider_code,
    )


@router.get(
    "/blocks/{block_id}/weather/observations",
    response_model=list[HourlyObservationRead],
    summary="Hourly observations in [since, until).",
)
async def list_observations(
    block_id: UUID,
    since: datetime = Query(...),
    until: datetime = Query(...),
    provider_code: str | None = Query(default=None),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[HourlyObservationRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.get_observations(
        block_id=block_id,
        since=since,
        until=until,
        provider_code=provider_code,
    )
    return list(rows)


@router.get(
    "/blocks/{block_id}/weather/derived",
    response_model=list[DerivedDailyRead],
    summary="Daily derived weather signals (GDD, ET0, rolling rainfall).",
)
async def list_derived_daily(
    block_id: UUID,
    since: date_type = Query(...),
    until: date_type = Query(...),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[DerivedDailyRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.get_derived_daily(
        block_id=block_id,
        since=since,
        until=until,
    )
    return list(rows)
