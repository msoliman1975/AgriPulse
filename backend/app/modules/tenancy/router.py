"""FastAPI router: POST /api/v1/admin/tenants (PlatformAdmin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.tenancy.schemas import CreateTenantRequest, TenantResponse
from app.modules.tenancy.service import (
    SlugAlreadyExistsError,
    TenantService,
    get_tenant_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin-tenants"])


def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> TenantService:
    return get_tenant_service(session)


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant.",
)
async def create_tenant(
    payload: CreateTenantRequest,
    context: RequestContext = Depends(requires_capability("platform.manage_tenants")),
    service: TenantService = Depends(_service),
) -> TenantResponse:
    try:
        result = await service.create_tenant(
            slug=payload.slug,
            name=payload.name,
            contact_email=str(payload.contact_email),
            legal_name=payload.legal_name,
            tax_id=payload.tax_id,
            contact_phone=payload.contact_phone,
            default_locale=payload.default_locale,
            default_unit_system=payload.default_unit_system,
            initial_tier=payload.initial_tier,
            actor_user_id=context.user_id,
        )
    except SlugAlreadyExistsError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Tenant slug already exists",
            detail=str(exc),
            type_="https://missionagre.io/problems/tenant-slug-conflict",
            extras={"slug": payload.slug},
        ) from exc

    return TenantResponse(
        id=result.tenant_id,
        slug=result.slug,
        name=result.name,
        schema_name=result.schema_name,
        contact_email=result.contact_email,
        default_locale=result.default_locale,
        default_unit_system=result.default_unit_system,
        status=result.status,
        created_at=result.created_at,
    )
