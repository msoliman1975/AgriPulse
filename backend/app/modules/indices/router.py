"""FastAPI routes for the indices module.

  GET /api/v1/blocks/{block_id}/indices/{index_code}/timeseries
  GET /api/v1/indices/catalog

Per-farm RBAC: same pattern as imagery â€” block-only routes look up
the block's farm_id, gate on `index.read`, and surface denial as 404.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.errors import BlockNotVisibleError
from app.modules.indices.schemas import (
    IndexCatalogEntry,
    IndexTimeseriesResponse,
    TimeseriesGranularity,
)
from app.modules.indices.service import IndicesService, get_indices_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.blocks import read_block_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["indices"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> IndicesService:
    return get_indices_service(tenant_session=tenant_session)


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
    """Look up the farm_id that owns this block; 404 if missing.

    Uses the shared cross-module reader so this module doesn't have to
    grow its own SQL for the same lookup the imagery router needs.
    """
    block = await read_block_context(tenant_session, block_id=block_id)
    if block is None:
        raise BlockNotVisibleError(str(block_id))
    return block["farm_id"]


@router.get(
    "/indices/catalog",
    response_model=list[IndexCatalogEntry],
    summary="List the supported indices from public.indices_catalog.",
)
async def list_index_catalog(
    context: RequestContext = Depends(get_current_context),
    service: IndicesService = Depends(_service),
) -> list[IndexCatalogEntry]:
    """Catalog endpoint for the SPA's index labels, bounds and units.

    Mirrors `GET /api/v1/weather/indices/catalog`: a tenant scope is
    enough, because these rows are platform-wide curated data rather
    than per-farm, so there is no farm to gate on.

    The SPA previously hardcoded index metadata, which is how `msi`'s
    [0, 3] range and `ndmi`'s existence both went missing from pickers
    that had drifted from the backend. `unit` is the newest reason to
    read it from here: `lst` is degrees Celsius and every other index is
    dimensionless, so a hardcoded formatter cannot be right for both.
    """
    _ensure_tenant(context)
    return list(await service.list_catalog())


@router.get(
    "/blocks/{block_id}/indices/{index_code}/timeseries",
    response_model=IndexTimeseriesResponse,
    summary="Index time-series for a block (daily or weekly bucket).",
)
async def get_index_timeseries(
    block_id: UUID,
    index_code: str,
    granularity: TimeseriesGranularity = Query(default="daily"),
    from_datetime: datetime | None = Query(default=None, alias="from"),
    to_datetime: datetime | None = Query(default=None, alias="to"),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: IndicesService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "index.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    response = await service.get_timeseries(
        block_id=block_id,
        index_code=index_code,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        granularity=granularity,
    )
    return response.model_dump(mode="json")
