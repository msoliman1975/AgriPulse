"""Plan-templates REST API.

E2 ships the tenant apply surface (appliable / preview / apply). E3 adds the
platform authoring surface (whole-tree CRUD + publish/archive) under the
``plan_template.manage`` capability.

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
    PlanTemplateDetail,
    PlanTemplatePreviewResponse,
    PlanTemplateSummary,
    PlanTemplateWriteRequest,
    ResolvedPhenologyResponse,
)
from app.modules.plan_templates.service import (
    PlanTemplatesService,
    get_plan_templates_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

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


# ---------- Platform authoring (cap plan_template.manage) -------------------
#
# Mounted on the same /plan-templates prefix. The literal sub-paths (``list`` is
# the bare collection; ``phenology`` for the stage-picker) are declared BEFORE
# the ``/{template_id}`` param route so they are not shadowed by it. Tenant
# ``/plan-templates/appliable`` is registered earlier in this file, so it also
# wins over ``/{template_id}``.


@router.get(
    "/plan-templates",
    response_model=list[PlanTemplateSummary],
    summary="List plan templates in the catalog (platform; all statuses).",
)
async def admin_list_templates(
    status_filter: str | None = Query(default=None, alias="status"),
    crop_path: str | None = Query(default=None),
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    statuses = (status_filter,) if status_filter else ()
    return await service.list_templates(status_filter=statuses, crop_path=crop_path)


@router.get(
    "/plan-templates/phenology",
    response_model=ResolvedPhenologyResponse,
    summary="Resolved phenology stages for a crop path (authoring stage-picker).",
)
async def admin_resolve_phenology(
    crop_path: str = Query(min_length=1),
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    del context
    return await service.resolve_phenology(crop_path=crop_path)


@router.post(
    "/plan-templates",
    response_model=PlanTemplateDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a plan template (platform; whole tree).",
)
async def admin_create_template(
    payload: PlanTemplateWriteRequest,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    return await service.create_template(payload=payload, actor_user_id=context.user_id)


@router.get(
    "/plan-templates/{template_id}",
    response_model=PlanTemplateDetail,
    summary="Get a plan template's full tree (platform).",
)
async def admin_get_template(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    del context
    return await service.get_full_tree(template_id=template_id)


@router.put(
    "/plan-templates/{template_id}",
    response_model=PlanTemplateDetail,
    summary="Replace a plan template's whole tree (platform).",
)
async def admin_update_template(
    template_id: UUID,
    payload: PlanTemplateWriteRequest,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    return await service.update_template(
        template_id=template_id, payload=payload, actor_user_id=context.user_id
    )


@router.post(
    "/plan-templates/{template_id}/publish",
    response_model=PlanTemplateDetail,
    summary="Publish a plan template (platform).",
)
async def admin_publish_template(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    return await service.set_status(
        template_id=template_id, status="published", actor_user_id=context.user_id
    )


@router.post(
    "/plan-templates/{template_id}/archive",
    response_model=PlanTemplateDetail,
    summary="Archive a plan template (platform).",
)
async def admin_archive_template(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> dict[str, Any]:
    return await service.set_status(
        template_id=template_id, status="archived", actor_user_id=context.user_id
    )


@router.delete(
    "/plan-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire a plan template (platform; archive + free the code).",
)
async def admin_delete_template(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("plan_template.manage")),
    service: PlanTemplatesService = Depends(_service),
) -> None:
    await service.delete_template(template_id=template_id, actor_user_id=context.user_id)
