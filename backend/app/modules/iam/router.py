"""FastAPI router: GET /api/v1/me + tenant user management."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.iam.field_enrolment import get_field_enrolment_service
from app.modules.iam.schemas import (
    MeResponse,
    TenantUserResponse,
    UserInviteRequest,
    UserInviteResponse,
    UserResendInviteResponse,
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
from app.shared.rbac.check import (
    PermissionDeniedError,
    has_capability,
    requires_capability,
)

router = APIRouter(prefix="/api/v1", tags=["iam"])


def _require_field_enrol(context: RequestContext, farm_id: UUID | None) -> None:
    """``user.field_enrol`` on ``farm_id``, or tenant-wide when none is named.

    Not ``requires_capability`` because the farm arrives in the request *body*
    on the enrolment route, and that dependency only reads path and query
    params. Passing ``farm_id=None`` deliberately narrows to the tenant- and
    platform-role branches of the resolver, so an unscoped call still needs an
    unscoped grant: a farm manager must say which farm they are acting on.
    """
    if not has_capability(context, "user.field_enrol", farm_id=farm_id):
        raise PermissionDeniedError("user.field_enrol", farm_id=farm_id)


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
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


async def _resolve_tenant_id(*, schema: str, session: AsyncSession) -> UUID:
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
            type_="https://agripulse.cloud/problems/tenant-not-found",
        )
    return row.id


def _user_not_found(user_id: UUID) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="User not found",
        detail=f"No user with id {user_id} in this tenant.",
        type_="https://agripulse.cloud/problems/iam/user-not-found",
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
        return await service.get_me(
            context.user_id,
            email=context.email,
            full_name=context.full_name,
        )
    except UserNotFoundError as exc:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="User not found",
            detail="No user record exists for this token. Sign out and back in.",
            type_="https://agripulse.cloud/problems/user-not-found",
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
            type_="https://agripulse.cloud/problems/iam/user-already-exists",
            extras={"email": exc.email},
        ) from exc


@router.post(
    "/users/{user_id}:resend-invite",
    response_model=UserResendInviteResponse,
    summary="Re-issue a user's first-login credential (welcome email / temp password).",
)
async def resend_tenant_user_invite(
    user_id: UUID,
    context: RequestContext = Depends(requires_capability("user.invite")),
    service: TenantUsersService = Depends(_users_service),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    try:
        return await service.resend_invite(
            user_id=user_id,
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantUserNotFoundError as exc:
        raise _user_not_found(user_id) from exc


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


# ---------- Field enrolment (phone + PIN) -----------------------------------


class FieldEnrolmentRequest(BaseModel):
    """Give one field worker app access.

    No email: this whole path exists because the person does not have one.
    """

    phone: str = Field(min_length=6, max_length=32)
    full_name: str = Field(min_length=1, max_length=200)
    farm_id: UUID
    role: Literal["Scout", "FieldOperator"] = "Scout"
    # Link an existing `resources` worker rather than creating a second row for
    # somebody the farm already knows about.
    worker_id: UUID | None = None


class FieldEnrolmentResponse(BaseModel):
    """The PIN is here **once**.

    It is not stored in readable form and no endpoint returns it again — a
    forgotten PIN is re-issued, not looked up. The client is expected to show
    it, let the supervisor read it aloud, and then drop it.
    """

    user_id: UUID
    membership_id: UUID
    worker_id: UUID | None
    phone: str
    pin: str


@router.post(
    "/users/field-enrolment",
    response_model=FieldEnrolmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enrol a field worker who signs in with a phone number and a PIN.",
)
async def enrol_field_worker(
    payload: FieldEnrolmentRequest,
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    # Checked against the farm in the body, so the manager of that farm can do
    # this without holding tenant-wide `user.invite`.
    _require_field_enrol(context, payload.farm_id)
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    slug_row = (
        await session.execute(
            text("SELECT slug FROM public.tenants WHERE id = :t"), {"t": tenant_id}
        )
    ).first()
    service = get_field_enrolment_service(public_session=session, tenant_session=tenant_session)
    result = await service.enrol(
        tenant_id=tenant_id,
        tenant_slug=str(slug_row.slug) if slug_row else schema,
        farm_id=payload.farm_id,
        phone=payload.phone,
        full_name=payload.full_name,
        role=payload.role,
        worker_id=payload.worker_id,
        actor_user_id=context.user_id,
    )
    return {
        "user_id": result.user_id,
        "membership_id": result.membership_id,
        "worker_id": result.worker_id,
        "phone": result.phone,
        "pin": result.pin,
    }


class WorkerBrief(BaseModel):
    id: UUID
    name: str
    role: str | None = None
    # The number the farm already recorded. Returned so enrolment does not ask
    # an operator to retype the username — a typo there mints a second account
    # rather than failing, because the phone *is* the username.
    phone: str | None = None
    has_phone: bool
    # Set only for people already enrolled; PIN reissue is keyed on the user,
    # and a worker row does not carry one.
    user_id: UUID | None = None


class FieldEnrolmentAuditResponse(BaseModel):
    """A worklist, not a directory: each bucket implies a different next step."""

    total: int
    enrolled: list[WorkerBrief]
    ready_to_enrol: list[WorkerBrief]
    # `FieldWorker` holds no capabilities, so these people can be scheduled but
    # can never sign in. Re-role them before enrolling.
    blocked_by_role: list[WorkerBrief]
    # The phone is the username, so no phone means no possible account.
    missing_phone: list[WorkerBrief]


class ReRoleRequest(BaseModel):
    # Required, and the update is scoped to it. Without a farm this is a bulk
    # write over every worker in the tenant, which a farm manager must not
    # have — and the ids come from an audit that is already per-farm.
    farm_id: UUID
    worker_ids: list[UUID] = Field(min_length=1, max_length=500)
    role: Literal["Scout", "FieldOperator"] = "Scout"


class ReRoleResponse(BaseModel):
    updated: int


class PinReissueResponse(BaseModel):
    """The new PIN, shown once. The previous one stops working immediately."""

    user_id: UUID
    pin: str


@router.get(
    "/users/field-enrolment/audit",
    response_model=FieldEnrolmentAuditResponse,
    summary="Which workers can be given the app, and which cannot yet.",
)
async def audit_field_workers(
    farm_id: UUID | None = None,
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    # A farm manager runs their own pre-flight by naming their farm; omitting
    # it asks for every worker in the tenant and needs the tenant-wide grant.
    _require_field_enrol(context, farm_id)
    _ensure_tenant(context)
    service = get_field_enrolment_service(public_session=session, tenant_session=tenant_session)
    return await service.audit_workers(farm_id=farm_id)


@router.post(
    "/users/field-enrolment/re-role",
    response_model=ReRoleResponse,
    summary="Promote FieldWorker rows so they can hold an app login.",
)
async def re_role_field_workers(
    payload: ReRoleRequest,
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _require_field_enrol(context, payload.farm_id)
    _ensure_tenant(context)
    service = get_field_enrolment_service(public_session=session, tenant_session=tenant_session)
    updated = await service.re_role_field_workers(
        farm_id=payload.farm_id, worker_ids=tuple(payload.worker_ids), role=payload.role
    )
    return {"updated": updated}


@router.post(
    "/users/{user_id}/field-pin:reissue",
    response_model=PinReissueResponse,
    summary="Issue a new PIN for a field worker who forgot theirs.",
)
async def reissue_field_pin(
    user_id: UUID,
    # Same capability as enrolling: handing someone a working credential is the
    # same act whether it is their first or their third. Naming a farm lets
    # that farm's manager do it; the service then verifies the target is
    # actually scoped there, so the farm is a claim to be checked and not a
    # way to reach a scout on somebody else's farm.
    farm_id: UUID | None = None,
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _require_field_enrol(context, farm_id)
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, session=session)
    service = get_field_enrolment_service(public_session=session, tenant_session=tenant_session)
    pin = await service.reissue_pin(tenant_id=tenant_id, user_id=user_id, farm_id=farm_id)
    return {"user_id": user_id, "pin": pin}
