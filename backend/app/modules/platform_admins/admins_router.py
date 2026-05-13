"""Self-service platform admin endpoints.

Mounted at /api/v1/admin/platform-admins. PlatformAdmin only via
`platform.manage_platform_admins`.

  GET    /platform-admins                â€” list current platform admins
  POST   /platform-admins:invite         â€” invite a PlatformAdmin / Support
  DELETE /platform-admins/{user_id}      â€” revoke role
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.users_service import TenantUserAlreadyExistsError
from app.modules.platform_admins.admins_service import (
    PlatformAdminNotFoundError,
    PlatformAdminsRoleService,
    get_platform_admins_role_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(
    prefix="/api/v1/admin/platform-admins",
    tags=["admin-platform-admins"],
)


def _service(
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> PlatformAdminsRoleService:
    return get_platform_admins_role_service(public_session=public_session)


class PlatformAdminRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    full_name: str | None
    keycloak_subject: str | None
    role: Literal["PlatformAdmin", "PlatformSupport"]
    granted_at: datetime
    granted_by: UUID | None


class InvitePlatformAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["PlatformAdmin", "PlatformSupport"] = "PlatformAdmin"


class InvitePlatformAdminResponse(BaseModel):
    user_id: UUID
    keycloak_subject: str | None
    keycloak_provisioning: Literal["succeeded", "pending"]
    role: Literal["PlatformAdmin", "PlatformSupport"]


@router.get("", response_model=list[PlatformAdminRow])
async def list_platform_admins(
    context: RequestContext = Depends(
        requires_capability("platform.manage_platform_admins")
    ),
    service: PlatformAdminsRoleService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_admins()


@router.post(
    ":invite",
    response_model=InvitePlatformAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_platform_admin(
    payload: InvitePlatformAdminRequest,
    context: RequestContext = Depends(
        requires_capability("platform.manage_platform_admins")
    ),
    service: PlatformAdminsRoleService = Depends(_service),
) -> dict[str, Any]:
    try:
        return await service.invite_admin(
            email=str(payload.email),
            full_name=payload.full_name,
            role=payload.role,
            actor_user_id=context.user_id,
        )
    except TenantUserAlreadyExistsError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Already a platform admin",
            detail=f"{exc.email!r} already has an active platform role.",
            type_="https://agripulse.cloud/problems/platform-admin-already-exists",
        ) from exc


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_platform_admin(
    user_id: UUID,
    role: Literal["PlatformAdmin", "PlatformSupport"] = Query(
        default="PlatformAdmin"
    ),
    context: RequestContext = Depends(
        requires_capability("platform.manage_platform_admins")
    ),
    service: PlatformAdminsRoleService = Depends(_service),
) -> None:
    try:
        await service.remove_admin(
            user_id=user_id,
            role=role,
            actor_user_id=context.user_id,
        )
    except PlatformAdminNotFoundError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Platform admin not found",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/platform-admin-not-found",
        ) from exc
    except ValueError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Cannot remove last admin",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/platform-admin-last",
        ) from exc
