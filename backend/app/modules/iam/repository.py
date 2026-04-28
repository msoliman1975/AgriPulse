"""Async DB access for iam. Internal to the module."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import (
    FarmScope,
    PlatformRoleAssignment,
    TenantMembership,
    TenantRoleAssignment,
    User,
    UserPreferences,
)
from app.modules.tenancy.models import Tenant


class UserRepository:
    """Reads everything required to render GET /api/v1/me."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_preferences(self, user_id: UUID) -> UserPreferences | None:
        return await self._session.get(UserPreferences, user_id)

    async def get_platform_roles(self, user_id: UUID) -> Sequence[PlatformRoleAssignment]:
        stmt = select(PlatformRoleAssignment).where(
            PlatformRoleAssignment.user_id == user_id,
            PlatformRoleAssignment.revoked_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get_memberships_with_tenant_roles(
        self, user_id: UUID
    ) -> list[tuple[TenantMembership, Tenant, list[TenantRoleAssignment]]]:
        """Return active memberships, the tenant they belong to, and active
        tenant roles per membership.
        """
        memb_stmt = (
            select(TenantMembership, Tenant)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                TenantMembership.user_id == user_id,
                TenantMembership.deleted_at.is_(None),
                Tenant.deleted_at.is_(None),
            )
        )
        memberships = (await self._session.execute(memb_stmt)).all()

        out: list[tuple[TenantMembership, Tenant, list[TenantRoleAssignment]]] = []
        for membership, tenant in memberships:
            roles_stmt = select(TenantRoleAssignment).where(
                TenantRoleAssignment.membership_id == membership.id,
                TenantRoleAssignment.revoked_at.is_(None),
            )
            roles = list((await self._session.execute(roles_stmt)).scalars().all())
            out.append((membership, tenant, roles))
        return out

    async def get_farm_scopes(self, user_id: UUID) -> list[FarmScope]:
        stmt = (
            select(FarmScope)
            .join(
                TenantMembership,
                TenantMembership.id == FarmScope.membership_id,
            )
            .where(
                TenantMembership.user_id == user_id,
                FarmScope.revoked_at.is_(None),
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())
