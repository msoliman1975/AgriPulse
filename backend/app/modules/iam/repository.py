"""Async DB access for iam. Internal to the module."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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

    async def upsert_from_jwt(
        self,
        *,
        sub: UUID,
        email: str,
        full_name: str,
    ) -> User:
        """Ensure a `public.users` row exists matching the current JWT.

        Three cases, in order:

        1. **Row exists with id == sub** — return as-is. Hot path; one
           query, no writes.
        2. **Row exists by email, id != sub** — Keycloak re-issued the
           user (delete+recreate). Re-key the row: id := sub,
           keycloak_subject := sub. The FK targets carry through via
           ON UPDATE CASCADE (migration 0023) so memberships,
           preferences, role grants follow. Refresh display name + email
           verification flag while we're here.
        3. **No row** — first-ever login for this email. Insert a new
           row with id = sub.

        The upsert is idempotent and safe under concurrent first-logins
        for the same user (PK + email unique constraints serialise the
        write).
        """
        # Case 1: fast path.
        user = await self._session.get(User, sub)
        if user is not None and user.deleted_at is None:
            return user

        # Case 2: same email, different sub (KC user recreated).
        # Use a raw UPDATE so the PK change cascades cleanly through the
        # ON UPDATE CASCADE FKs (migration 0023). ORM identity-map can
        # mis-handle PK mutation, hence the textual SQL and the
        # session.expire() afterwards.
        if email:
            stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
            existing = (await self._session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                await self._session.execute(
                    text(
                        "UPDATE public.users "
                        "SET id = :new_id, keycloak_subject = :new_sub, "
                        "    full_name = COALESCE(NULLIF(:full_name, ''), full_name) "
                        "WHERE id = :old_id"
                    ).bindparams(
                        bindparam("new_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("old_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    {
                        "new_id": sub,
                        "new_sub": str(sub),
                        "old_id": existing.id,
                        "full_name": full_name or "",
                    },
                )
                # Drop the now-stale ORM object so the next get() re-reads
                # the (rekeyed) row from the database.
                await self._session.flush()
                self._session.expire(existing)
                refreshed = await self._session.get(User, sub)
                if refreshed is not None:
                    return refreshed

        # Case 3: brand-new user.
        user = User(
            id=sub,
            keycloak_subject=str(sub),
            email=email or f"{sub}@no-email.local",
            full_name=full_name or email or str(sub),
        )
        self._session.add(user)
        await self._session.flush()
        return user

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
                    "WHERE id IN :ids AND deleted_at IS NULL"
                ).bindparams(bindparam("ids", type_=PG_UUID(as_uuid=True), expanding=True)),
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
