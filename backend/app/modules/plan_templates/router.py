"""Plan-templates REST API.

E2 ships the tenant apply surface (appliable / preview / apply). Platform
authoring (whole-tree CRUD + publish) lands in PR-E3.

Two sessions like the farms router: tenant-scoped (search_path) for
blocks/plans + public for the template catalog.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.plan_templates.schemas import (
    AppliableTemplate,
    PlanTemplateApplyRequest,
    PlanTemplateApplyResponse,
    PlanTemplatePreviewResponse,
)
from app.modules.plan_templates.service import (
    PlanTemplatesService,
    get_plan_templates_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["plan-templates"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> PlanTemplatesService:
    return get_plan_templates_service(public_session=public_session, tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


def _require(context: RequestContext, cap: str, farm_id: UUID) -> None:
    if not has_capability(context, cap, farm_id=farm_id):
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail=f"Missing capability {cap} for this farm.",
            type_="https://agripulse.cloud/problems/forbidden",
        )


@router.get(
    "/plan-templates/appliable",
    response_model=list[AppliableTemplate],
    summary="Published templates that match a farm's blocks, with the blocks they fit.",
)
async def list_appliable(
    farm_id: UUID = Query(...),
    context: RequestContext = Depends(get_current_context),
    service: PlanTemplatesService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    _require(context, "plan_template.read", farm_id)
    return await service.list_appliable(farm_id=farm_id)


@router.post(
    "/plan-templates/{template_id}/preview",
    response_model=PlanTemplatePreviewResponse,
    summary="Dry-run the schedule a template would generate per block (no writes).",
)
async def preview(
    template_id: UUID,
    payload: PlanTemplateApplyRequest,
    context: RequestContext = Depends(get_current_context),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    _require(context, "plan_template.read", payload.farm_id)
    return await service.preview(
        template_id=template_id,
        farm_id=payload.farm_id,
        season_year=payload.season_year,
        blocks=payload.blocks,
    )


@router.post(
    "/plan-templates/{template_id}/apply",
    response_model=PlanTemplateApplyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a template to a farm's matching blocks (idempotent per season).",
)
async def apply(
    template_id: UUID,
    payload: PlanTemplateApplyRequest,
    context: RequestContext = Depends(get_current_context),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    _require(context, "plan_template.apply", payload.farm_id)
    return await service.apply(
        template_id=template_id,
        farm_id=payload.farm_id,
        season_label=payload.season_label,
        season_year=payload.season_year,
        blocks=payload.blocks,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
