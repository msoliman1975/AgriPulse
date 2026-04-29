"""Async DB access for iam. Internal to the module."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import (
    FarmScope,
    PlatformRoleAssignment,
    TenantMembership,
    TenantRoleAssignment,
    User,
    UserPreferences,
)


@dataclass(frozen=True, slots=True)
class TenantSummary:
    """Slim view of a tenant returned by /me. Avoids importing tenancy's ORM
    model so the iam module respects the import-linter contract."""

    id: UUID
    slug: str
    name: str


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
    ) -> list[tuple[TenantMembership, TenantSummary, list[TenantRoleAssignment]]]:
        """Return active memberships, a TenantSummary for each, and the
        active tenant-wide roles per membership.

        The tenant join uses raw SQL against ``public.tenants`` so iam
        does not import tenancy's ORM model — see ARCHITECTURE.md § 6.1.
        """
        memb_stmt = select(TenantMembership).where(
            TenantMembership.user_id == user_id,
            TenantMembership.deleted_at.is_(None),
        )
        memberships = list((await self._session.execute(memb_stmt)).scalars().all())
        if not memberships:
            return []

        tenant_ids = {m.tenant_id for m in memberships}
        tenants_rows = (
            await self._session.execute(
                text(
                    "SELECT id, slug, name FROM public.tenants "
                    "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                ),
                {"ids": list(tenant_ids)},
            )
        ).all()
        tenants_by_id = {
            row.id: TenantSummary(id=row.id, slug=row.slug, name=row.name) for row in tenants_rows
        }

        out: list[tuple[TenantMembership, TenantSummary, list[TenantRoleAssignment]]] = []
        for membership in memberships:
            tenant = tenants_by_id.get(membership.tenant_id)
            if tenant is None:
                continue  # tenant soft-deleted; skip stale membership
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
