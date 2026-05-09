"""Platform-side tenant-admin endpoints.

Mounted at /api/v1/admin/tenants/{tenant_id}/admins. PlatformAdmin
only via `platform.manage_tenant_admins`.

  GET    /admins                                — list current admins
  POST   /admins:invite                         — invite a TenantAdmin
  DELETE /admins/{user_id}?role=TenantAdmin     — revoke role
  POST   /admins/{user_id}:transfer-ownership   — make this user the new
                                                  TenantOwner
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admins.service import (
    PlatformAdminsService,
    TenantAdminConflictError,
    get_platform_admins_service,
)
from app.modules.iam.users_service import (
    TenantUserAlreadyExistsError,
    TenantUserNotFoundError,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(
    prefix="/api/v1/admin/tenants/{tenant_id}/admins",
    tags=["admin-tenant-admins"],
)


def _service(
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> PlatformAdminsService:
    return get_platform_admins_service(public_session=public_session)


class TenantAdminRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    full_name: str | None
    membership_id: UUID
    membership_status: str
    role: str
    granted_at: datetime


class InviteAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)


class InviteAdminResponse(BaseModel):
    user_id: UUID
    membership_id: UUID
    keycloak_provisioning: str
    keycloak_subject: str | None


@router.get("", response_model=list[TenantAdminRow])
async def list_admins(
    tenant_id: UUID,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenant_admins")
    ),
    service: PlatformAdminsService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_admins(tenant_id=tenant_id)


@router.post(
    ":invite",
    response_model=InviteAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_admin(
    tenant_id: UUID,
    payload: InviteAdminRequest,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenant_admins")
    ),
    service: PlatformAdminsService = Depends(_service),
) -> dict[str, Any]:
    try:
        return await service.invite_admin(
            tenant_id=tenant_id,
            email=str(payload.email),
            full_name=payload.full_name,
            role="TenantAdmin",
            actor_user_id=context.user_id,
        )
    except TenantUserAlreadyExistsError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="User already in tenant",
            detail=f"{exc.email!r} already has an active membership.",
            type_="https://missionagre.io/problems/tenant-admin-already-member",
        ) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_admin_role(
    tenant_id: UUID,
    user_id: UUID,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenant_admins")
    ),
    service: PlatformAdminsService = Depends(_service),
) -> None:
    try:
        await service.remove_admin_role(
            tenant_id=tenant_id,
            user_id=user_id,
            role="TenantAdmin",
            actor_user_id=context.user_id,
        )
    except TenantUserNotFoundError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="User not in tenant",
            detail=str(exc),
            type_="https://missionagre.io/problems/tenant-admin-not-found",
        ) from exc


class TransferOwnershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_user_id: UUID = Field(
        description="Current TenantOwner; verified before the transfer."
    )


@router.post("/{user_id}:transfer-ownership", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def transfer_ownership(
    tenant_id: UUID,
    user_id: UUID,
    payload: TransferOwnershipRequest,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenant_admins")
    ),
    service: PlatformAdminsService = Depends(_service),
) -> None:
    try:
        await service.transfer_ownership(
            tenant_id=tenant_id,
            from_user_id=payload.from_user_id,
            to_user_id=user_id,
            actor_user_id=context.user_id,
        )
    except TenantUserNotFoundError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="User not in tenant",
            detail=str(exc),
            type_="https://missionagre.io/problems/tenant-admin-not-found",
        ) from exc
    except TenantAdminConflictError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Ownership transfer conflict",
            detail=str(exc),
            type_="https://missionagre.io/problems/tenant-admin-conflict",
        ) from exc
