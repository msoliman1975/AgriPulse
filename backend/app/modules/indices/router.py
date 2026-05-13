"""FastAPI routes for the indices module.

One endpoint in PR-C:

  GET /api/v1/blocks/{block_id}/indices/{index_code}/timeseries

Per-farm RBAC: same pattern as imagery â€” block-only routes look up
the block's farm_id, gate on `index.read`, and surface denial as 404.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.errors import BlockNotVisibleError
from app.modules.indices.schemas import IndexTimeseriesResponse, TimeseriesGranularity
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
