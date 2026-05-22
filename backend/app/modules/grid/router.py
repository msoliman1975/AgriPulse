"""FastAPI routes for the grid-zones module.

PR-1 surface — three endpoints under
``/api/v1/blocks/{block_id}/grid-configs/{product_id}``:

  * GET    — fetch the current active config (or 404 if none).
  * PUT    — set/replace the cell size (creates a fresh config + cells,
             soft-retiring any prior active config).
  * POST   /preview — guardrail dry-run, no writes.

RBAC: same per-farm pattern as ``indices``/``imagery`` — look up the
farm_id from the block, gate on ``index.read`` (preview / GET) or
``imagery.manage`` (PUT), surface denial as a 404.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.grid.errors import GridConfigNotFoundError
from app.modules.grid.schemas import (
    CellSizePreviewRequest,
    CellSizePreviewResponse,
    GridCellHistoryResponse,
    GridCellsResponse,
    GridConfigBody,
    GridConfigResponse,
)
from app.modules.grid.service import GridService, get_grid_service
from app.modules.imagery.errors import BlockNotVisibleError
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.blocks import read_block_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["grid"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> GridService:
    return get_grid_service(tenant_session=tenant_session)


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
    block = await read_block_context(tenant_session, block_id=block_id)
    if block is None:
        raise BlockNotVisibleError(str(block_id))
    return block["farm_id"]


@router.get(
    "/blocks/{block_id}/grid-configs/{product_id}",
    response_model=GridConfigResponse,
    summary="Active grid config for (block, imagery product).",
)
async def get_grid_config(
    block_id: UUID,
    product_id: UUID,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: GridService = Depends(_service),
) -> GridConfigResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "index.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    config = await service.get_active_config(block_id=block_id, product_id=product_id)
    if config is None:
        raise GridConfigNotFoundError(str(block_id), str(product_id))
    return config


@router.put(
    "/blocks/{block_id}/grid-configs/{product_id}",
    response_model=GridConfigResponse,
    summary="Create or replace the grid config; regenerates cells.",
)
async def put_grid_config(
    block_id: UUID,
    product_id: UUID,
    body: GridConfigBody,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: GridService = Depends(_service),
) -> GridConfigResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    # Cell size is a write op that reshapes the per-cell observation
    # stream — gate on imagery.subscription.manage (same scope that
    # owns the subscription cadence), not index.read.
    if not has_capability(context, "imagery.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.upsert_config(
        block_id=block_id,
        product_id=product_id,
        cell_size_m=body.cell_size_m,
        created_by=context.user_id,
    )


@router.post(
    "/blocks/{block_id}/grid-configs/{product_id}/preview",
    response_model=CellSizePreviewResponse,
    summary="Guardrail dry-run for a cell size; no writes.",
)
async def preview_cell_size(
    block_id: UUID,
    product_id: UUID,
    body: CellSizePreviewRequest,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: GridService = Depends(_service),
) -> CellSizePreviewResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "index.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.preview_cell_size(
        block_id=block_id,
        product_id=product_id,
        cell_size_m=body.cell_size_m,
    )


@router.get(
    "/blocks/{block_id}/grid-cells",
    response_model=GridCellsResponse,
    summary="Cells + values for a block at a specific (or latest) scene time.",
)
async def get_grid_cells(
    block_id: UUID,
    product_id: UUID = Query(..., description="Imagery product UUID."),
    index_code: str = Query(..., alias="index"),
    at: datetime | None = Query(default=None, description="Scene time; latest if omitted."),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: GridService = Depends(_service),
) -> GridCellsResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "index.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.get_cells_with_values(
        block_id=block_id,
        product_id=product_id,
        index_code=index_code,
        at=at,
    )


@router.get(
    "/grid-cells/{cell_id}/history",
    response_model=GridCellHistoryResponse,
    summary="Time series for one cell + index.",
)
async def get_grid_cell_history(
    cell_id: UUID,
    product_id: UUID = Query(...),
    index_code: str = Query(..., alias="index"),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: GridService = Depends(_service),
) -> GridCellHistoryResponse:
    _ensure_tenant(context)
    # Resolve cell → block to apply the same per-farm RBAC the rest of
    # the grid module uses. Missing cell = 404 via shared helper.
    ctx = await service.resolve_cell_context(cell_id=cell_id)
    if ctx is None:
        raise BlockNotVisibleError(str(cell_id))
    farm_id = await _resolve_farm_id(block_id=ctx["block_id"], tenant_session=tenant_session)
    if not has_capability(context, "index.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(cell_id))
    return await service.get_cell_history(
        cell_id=cell_id,
        product_id=product_id,
        index_code=index_code,
    )
