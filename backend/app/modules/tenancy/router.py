"""FastAPI router: /api/v1/admin/tenants â€” PlatformAdmin tenant lifecycle.

All endpoints gated by the `platform.manage_tenants` capability.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.tenancy.schemas import (
    ArchiveEventResponse,
    CreateTenantRequest,
    PurgeTenantRequest,
    RequestDeleteRequest,
    SuspendTenantRequest,
    TenantDetailResponse,
    TenantListResponse,
    TenantMetaResponse,
    TenantResponse,
    TenantSettingsResponse,
    TenantSidecarResponse,
    TenantSubscriptionResponse,
    UpdateTenantRequest,
)
from app.modules.tenancy.service import (
    InvalidStatusTransitionError,
    NothingToProvisionError,
    PURGE_GRACE_DAYS,
    PurgeNotEligibleError,
    SlugAlreadyExistsError,
    SlugConfirmationMismatchError,
    TenantNotFoundError,
    TenantService,
    TenantSnapshot,
    get_tenant_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.keycloak import KeycloakNotConfiguredError
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin-tenants"])


def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> TenantService:
    return get_tenant_service(session)


_ManageTenants = Depends(requires_capability("platform.manage_tenants"))


def _detail(snapshot: TenantSnapshot) -> TenantDetailResponse:
    return TenantDetailResponse.model_validate(snapshot, from_attributes=True)


def _not_found(tenant_id: UUID) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Tenant not found",
        detail=f"No tenant with id {tenant_id}",
        type_="https://agripulse.cloud/problems/tenant-not-found",
        extras={"tenant_id": str(tenant_id)},
    )


def _conflict_status(exc: InvalidStatusTransitionError) -> APIError:
    return APIError(
        status_code=status.HTTP_409_CONFLICT,
        title="Invalid tenant status transition",
        detail=str(exc),
        type_="https://agripulse.cloud/problems/tenant-invalid-transition",
        extras={"current_status": exc.current, "attempted": exc.attempted},
    )


# ---- Create ---------------------------------------------------------------


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant.",
)
async def create_tenant(
    payload: CreateTenantRequest,
    context: RequestContext = _ManageTenants,
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
            owner_email=str(payload.owner_email),
            owner_full_name=payload.owner_full_name,
            actor_user_id=context.user_id,
        )
    except SlugAlreadyExistsError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Tenant slug already exists",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/tenant-slug-conflict",
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
        provisioning_failed=result.provisioning_failed,
        owner_user_id=result.owner_user_id,
    )


@router.post(
    "/{tenant_id}/retry-provisioning",
    response_model=TenantDetailResponse,
    summary="Retry Keycloak provisioning for a tenant in 'pending_provision'.",
)
async def retry_provisioning(
    tenant_id: UUID,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    try:
        snapshot = await service.retry_provisioning(
            tenant_id, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    except NothingToProvisionError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Nothing to provision",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/tenant-nothing-to-provision",
        ) from exc
    except KeycloakNotConfiguredError as exc:
        raise APIError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Keycloak provisioning disabled",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/keycloak-not-configured",
        ) from exc
    return _detail(snapshot)


# ---- Picker values --------------------------------------------------------


@router.get(
    "/_meta",
    response_model=TenantMetaResponse,
    summary="Picker values for the admin-portal forms.",
)
async def tenant_meta(
    context: RequestContext = _ManageTenants,
) -> TenantMetaResponse:
    del context
    return TenantMetaResponse(
        statuses=[
            "active",
            "suspended",
            "pending_delete",
            "pending_provision",
            "archived",
        ],
        tiers=["free", "standard", "premium", "enterprise"],
        locales=["en", "ar"],
        unit_systems=["feddan", "acre", "hectare"],
        purge_grace_days=PURGE_GRACE_DAYS,
    )


# ---- Read -----------------------------------------------------------------


@router.get(
    "",
    response_model=TenantListResponse,
    summary="List tenants (paginated).",
)
async def list_tenants(
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
    status_filter: Annotated[
        Literal[
            "active", "suspended", "pending_delete", "pending_provision", "archived"
        ]
        | None,
        Query(alias="status"),
    ] = None,
    search: Annotated[str | None, Query(max_length=64)] = None,
    include_deleted: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TenantListResponse:
    del context  # capability check already enforced
    result = await service.list_tenants(
        status=status_filter,
        search=search,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return TenantListResponse(
        items=[_detail(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantDetailResponse,
    summary="Get one tenant.",
)
async def get_tenant(
    tenant_id: UUID,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    del context
    try:
        snapshot = await service.get_tenant(tenant_id)
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    return _detail(snapshot)


@router.get(
    "/{tenant_id}/sidecar",
    response_model=TenantSidecarResponse,
    summary="Detail-page sidecar: settings, subscription, members, recent audit.",
)
async def get_tenant_sidecar(
    tenant_id: UUID,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
    audit_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TenantSidecarResponse:
    del context
    try:
        sidecar = await service.get_tenant_sidecar(tenant_id, audit_limit=audit_limit)
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    return TenantSidecarResponse(
        tenant_id=sidecar.tenant_id,
        settings=(
            TenantSettingsResponse.model_validate(sidecar.settings, from_attributes=True)
            if sidecar.settings is not None
            else None
        ),
        subscription=(
            TenantSubscriptionResponse.model_validate(
                sidecar.subscription, from_attributes=True
            )
            if sidecar.subscription is not None
            else None
        ),
        active_member_count=sidecar.active_member_count,
        recent_events=[
            ArchiveEventResponse.model_validate(e, from_attributes=True)
            for e in sidecar.recent_events
        ],
    )


# ---- Update profile -------------------------------------------------------


@router.patch(
    "/{tenant_id}",
    response_model=TenantDetailResponse,
    summary="Update tenant profile fields.",
)
async def update_tenant(
    tenant_id: UUID,
    payload: UpdateTenantRequest,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    patch = payload.model_dump(exclude_unset=True)
    if "contact_email" in patch and patch["contact_email"] is not None:
        patch["contact_email"] = str(patch["contact_email"])
    try:
        snapshot = await service.update_tenant(
            tenant_id, patch=patch, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    return _detail(snapshot)


# ---- Lifecycle ------------------------------------------------------------


@router.post(
    "/{tenant_id}/suspend",
    response_model=TenantDetailResponse,
    summary="Suspend a tenant. Sign-ins blocked while status='suspended'.",
)
async def suspend_tenant(
    tenant_id: UUID,
    payload: SuspendTenantRequest,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    try:
        snapshot = await service.suspend_tenant(
            tenant_id, reason=payload.reason, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    return _detail(snapshot)


@router.post(
    "/{tenant_id}/reactivate",
    response_model=TenantDetailResponse,
    summary="Reactivate a suspended tenant.",
)
async def reactivate_tenant(
    tenant_id: UUID,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    try:
        snapshot = await service.reactivate_tenant(
            tenant_id, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    return _detail(snapshot)


@router.post(
    "/{tenant_id}/delete",
    response_model=TenantDetailResponse,
    summary="Mark tenant for deletion. 30-day grace window before purge.",
)
async def request_delete(
    tenant_id: UUID,
    payload: RequestDeleteRequest,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    try:
        snapshot = await service.request_delete(
            tenant_id, reason=payload.reason, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    return _detail(snapshot)


@router.post(
    "/{tenant_id}/cancel-delete",
    response_model=TenantDetailResponse,
    summary="Cancel a pending deletion. Tenant returns to 'suspended'.",
)
async def cancel_delete(
    tenant_id: UUID,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> TenantDetailResponse:
    try:
        snapshot = await service.cancel_delete(
            tenant_id, actor_user_id=context.user_id
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    return _detail(snapshot)


@router.post(
    "/{tenant_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Hard-delete tenant. DROP SCHEMA + remove public rows. Irreversible.",
)
async def purge_tenant(
    tenant_id: UUID,
    payload: PurgeTenantRequest,
    context: RequestContext = _ManageTenants,
    service: TenantService = Depends(_service),
) -> None:
    try:
        await service.purge_tenant(
            tenant_id,
            slug_confirmation=payload.slug_confirmation,
            force=payload.force,
            actor_user_id=context.user_id,
        )
    except TenantNotFoundError as exc:
        raise _not_found(tenant_id) from exc
    except InvalidStatusTransitionError as exc:
        raise _conflict_status(exc) from exc
    except SlugConfirmationMismatchError as exc:
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Slug confirmation mismatch",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/tenant-slug-mismatch",
        ) from exc
    except PurgeNotEligibleError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Purge not yet eligible",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/tenant-purge-not-eligible",
            extras={"eligible_at": exc.eligible_at.isoformat()},
        ) from exc
