"""FastAPI router: GET /api/v1/me + tenant user management."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.iam.schemas import (
    MeResponse,
    TenantUserResponse,
    UserInviteRequest,
    UserInviteResponse,
    UserUpdateRequest,
)
from app.modules.iam.service import UserNotFoundError, UserService, get_user_service
from app.modules.iam.users_service import (
    TenantUserAlreadyExistsError,
    TenantUserNotFoundError,
    TenantUsersService,
    get_tenant_users_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["iam"])


def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> UserService:
    return get_user_service(session)


def _users_service(
    session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> TenantUsersService:
    return get_tenant_users_service(session, tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )
    return schema


async def _resolve_tenant_id(
    *, schema: str, session: AsyncSession
) -> UUID:
    row = (
        await session.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :s"),
            {"s": schema},
        )
    ).first()
    if row is None:
        raise APIError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Tenant not found",
            detail="Could not resolve tenant id from JWT-claimed schema.",
            type_="https://missionagre.io/problems/tenant-not-found",
        )
    return row.id


def _user_not_found(user_id: UUID) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="User not found",
        detail=f"No user with id {user_id} in this tenant.",
        type_="https://missionagre.io/problems/iam/user-not-found",
        extras={"user_id": str(user_id)},
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user profile, preferences, and authorization scopes.",
)
async def get_me(
    context: RequestContext = Depends(get_current_context),
    service: UserService = Depends(_service),
) -> MeResponse:
    try:
        return await service.get_me(context.user_id)
    except UserNotFoundError as exc:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="User not found",
            detail="No user record exists for this token. Sign out and back in.",
            type_="https://missionagre.io/problems/user-not-found",
        ) from exc


# ---------- Tenant user management ----------------------------------------


@router.get(
    "/users",
    response_model=list[TenantUserResponse],
    summary="List users in the current tenant.",
)
async def list_tenant_users(
    context: RequestContext = Depends(requires_capability("user.read")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    return await service.list_users(tenant_id=tenant_id)


@router.post(
    "/users:invite",
    response_model=UserInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new user to the current tenant.",
)
async def invite_tenant_user(
    payload: UserInviteRequest,
    context: RequestContext = Depends(requires_capability("user.invite")),
    service: TenantUsersService = Depends(_users_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    try:
        return await service.invite_user(
            email=str(payload.email),
            full_name=payload.full_name,
            phone=payload.phone,
            tenant_role=payload.tenant_role,
            tenant_schema=schema,
            actor_user_id=context.user_id,
        )
    except TenantUserAlreadyExistsError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="User already a tenant member",
            detail=str(exc),
            type_="https://missionagre.io/problems/iam/user-already-exists",
            extras={"email": exc.email},
        ) from exc


@router.patch(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Update a tenant user's profile / preferences.",
)
async def update_tenant_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    context: RequestContext = Depends(requires_capability("user.update")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    body = payload.model_dump(exclude_unset=True)
    preferences_patch = body.pop("preferences", None)
    try:
        await service.update_user(
            user_id=user_id,
            tenant_id=tenant_id,
            updates=body,
            preferences_patch=preferences_patch,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantUserNotFoundError as exc:
        raise _user_not_found(user_id) from exc


@router.post(
    "/users/{user_id}:suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Suspend a tenant user. Sign-ins blocked for this tenant.",
)
async def suspend_tenant_user(
    user_id: UUID,
    context: RequestContext = Depends(requires_capability("user.suspend")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    try:
        await service.suspend_user(
            user_id=user_id,
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantUserNotFoundError as exc:
        raise _user_not_found(user_id) from exc


@router.post(
    "/users/{user_id}:reactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Reactivate a suspended tenant user.",
)
async def reactivate_tenant_user(
    user_id: UUID,
    context: RequestContext = Depends(requires_capability("user.suspend")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    try:
        await service.reactivate_user(
            user_id=user_id,
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantUserNotFoundError as exc:
        raise _user_not_found(user_id) from exc


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Soft-delete a tenant user.",
)
async def delete_tenant_user(
    user_id: UUID,
    context: RequestContext = Depends(requires_capability("user.delete")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    try:
        await service.delete_user(
            user_id=user_id,
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantUserNotFoundError as exc:
        raise _user_not_found(user_id) from exc
