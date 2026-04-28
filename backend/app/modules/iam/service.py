"""IAM service: public Protocol + concrete implementation."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.repository import UserRepository
from app.modules.iam.schemas import (
    FarmScopeResponse,
    MeResponse,
    PlatformRoleResponse,
    TenantMembershipResponse,
    TenantRoleResponse,
    UserPreferencesResponse,
)


class UserNotFoundError(LookupError):
    """The user_id from the JWT does not exist in `public.users`.

    For MVP this is a 404 — first login should provision the row before
    a /me call ever runs (a Phase 2 sync handler upserts on token issuance).
    """


class UserService(Protocol):
    """Public contract for the iam module."""

    async def get_me(self, user_id: UUID) -> MeResponse: ...


class UserServiceImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get_me(self, user_id: UUID) -> MeResponse:
        user = await self._repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise UserNotFoundError(f"user {user_id} not found")

        prefs = await self._repo.get_preferences(user_id)
        prefs_resp = (
            UserPreferencesResponse.model_validate(prefs)
            if prefs is not None
            else _default_preferences_response()
        )

        platform_roles = await self._repo.get_platform_roles(user_id)
        memberships = await self._repo.get_memberships_with_tenant_roles(user_id)
        farm_scopes = await self._repo.get_farm_scopes(user_id)

        return MeResponse(
            id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            phone=user.phone,
            avatar_url=user.avatar_url,
            status=user.status,
            last_login_at=user.last_login_at,
            preferences=prefs_resp,
            platform_roles=[
                PlatformRoleResponse(role=r.role, granted_at=r.granted_at)
                for r in platform_roles
            ],
            tenant_memberships=[
                TenantMembershipResponse(
                    tenant_id=tenant.id,
                    tenant_slug=tenant.slug,
                    tenant_name=tenant.name,
                    status=membership.status,
                    joined_at=membership.joined_at,
                    tenant_roles=[
                        TenantRoleResponse(role=r.role, granted_at=r.granted_at)
                        for r in roles
                    ],
                )
                for membership, tenant, roles in memberships
            ],
            farm_scopes=[
                FarmScopeResponse(
                    farm_id=s.farm_id, role=s.role, granted_at=s.granted_at
                )
                for s in farm_scopes
            ],
        )


def _default_preferences_response() -> UserPreferencesResponse:
    """Used when a user has no preferences row yet (lazy-creation deferred)."""
    return UserPreferencesResponse(
        language="en",
        numerals="western",
        unit_system="feddan",
        timezone="Africa/Cairo",
        date_format="YYYY-MM-DD",
        notification_channels=["in_app", "email"],
    )


def get_user_service(session: AsyncSession) -> UserService:
    return UserServiceImpl(session)
