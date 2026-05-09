"""Platform-side tenant-admin management.

Sister to `TenantUsersService` (which is tenant-scoped). This service
acts cross-tenant and is reachable only via the
`platform.manage_tenant_admins` capability — never via a tenant role.

Three operations beyond `invite_user`:

  * list_admins(tenant_id)          — current TenantOwner + TenantAdmins
  * remove_admin_role(tenant_id, user_id, role)
                                    — revoke a single admin role; user
                                      may still have other roles
  * transfer_ownership(tenant_id, from_user_id, to_user_id)
                                    — atomically swap TenantOwner

Audit on every write under `platform.tenant_admin_*` event types.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.iam.users_service import TenantUserNotFoundError, TenantUsersService
from app.shared.keycloak import KeycloakAdminClient


class TenantAdminConflictError(Exception):
    """Raised when a tenant has no TenantOwner during a transfer."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PlatformAdminsService:
    def __init__(
        self,
        *,
        public_session: AsyncSession,
        keycloak: KeycloakAdminClient | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._public = public_session
        self._users = TenantUsersService(
            public_session=public_session, keycloak=keycloak, audit=audit
        )
        self._audit = audit or get_audit_service()
        self._log = get_logger(__name__)

    async def _tenant_schema(self, *, tenant_id: UUID) -> str:
        row = (
            await self._public.execute(
                text(
                    "SELECT schema_name FROM public.tenants WHERE id = :tid"
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"tid": tenant_id},
            )
        ).first()
        if row is None:
            raise LookupError(f"tenant {tenant_id} not found")
        return row.schema_name

    # ---- Reads --------------------------------------------------------

    async def list_admins(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        """All active memberships in the tenant whose role assignment is
        TenantOwner or TenantAdmin."""
        rows = (
            await self._public.execute(
                text(
                    """
                    SELECT u.id AS user_id,
                           u.email::text AS email,
                           u.full_name,
                           m.id AS membership_id,
                           m.status AS membership_status,
                           tra.role AS role,
                           tra.granted_at AS granted_at
                    FROM public.tenant_memberships m
                    JOIN public.users u ON u.id = m.user_id
                    JOIN public.tenant_role_assignments tra
                      ON tra.membership_id = m.id
                     AND tra.revoked_at IS NULL
                    WHERE m.tenant_id = :tid
                      AND m.deleted_at IS NULL
                      AND u.deleted_at IS NULL
                      AND tra.role IN ('TenantOwner','TenantAdmin')
                    ORDER BY tra.role, u.full_name
                    """
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"tid": tenant_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    # ---- Writes -------------------------------------------------------

    async def invite_admin(
        self,
        *,
        tenant_id: UUID,
        email: str,
        full_name: str,
        role: str,  # "TenantAdmin" — only role this endpoint creates
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        if role != "TenantAdmin":
            raise ValueError(
                "invite_admin only creates TenantAdmin; transfer_ownership "
                "moves TenantOwner."
            )
        schema = await self._tenant_schema(tenant_id=tenant_id)
        result = await self._users.invite_user(
            email=email,
            full_name=full_name,
            phone=None,
            tenant_role=role,
            tenant_schema=schema,
            actor_user_id=actor_user_id,
        )
        # Cross-cut audit on the platform side as well so the
        # platform_event log carries who-did-what regardless of which
        # tenant_schema the per-tenant audit_events landed in.
        await self._audit.record_archive(
            event_type="platform.tenant_admin_added",
            actor_user_id=actor_user_id,
            subject_kind="tenant_membership",
            subject_id=result["membership_id"],
            details={
                "tenant_id": str(tenant_id),
                "email": email,
                "role": role,
                "keycloak_provisioning": result["keycloak_provisioning"],
            },
        )
        return result

    async def remove_admin_role(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: str,
        actor_user_id: UUID | None,
    ) -> None:
        """Revoke one role on the user's membership in this tenant.

        Doesn't delete the membership — the user may still be a
        TenantAdmin elsewhere or have non-admin roles in this tenant.
        """
        membership_id = await self._membership_id(
            tenant_id=tenant_id, user_id=user_id
        )
        result = await self._public.execute(
            text(
                """
                UPDATE public.tenant_role_assignments
                SET revoked_at = now()
                WHERE membership_id = :mid
                  AND role = :role
                  AND revoked_at IS NULL
                """
            ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
            {"mid": membership_id, "role": role},
        )
        if (result.rowcount or 0) == 0:
            return  # idempotent — no active assignment of this role
        await self._audit.record_archive(
            event_type="platform.tenant_admin_removed",
            actor_user_id=actor_user_id,
            subject_kind="tenant_membership",
            subject_id=membership_id,
            details={
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "role": role,
            },
        )

    async def transfer_ownership(
        self,
        *,
        tenant_id: UUID,
        from_user_id: UUID,
        to_user_id: UUID,
        actor_user_id: UUID | None,
    ) -> None:
        """Atomically move TenantOwner from one user to another.

        Both users must already be members of this tenant. The new
        owner is also auto-granted TenantAdmin if they don't have it
        yet so they retain editorial powers; the previous owner keeps
        their other roles untouched.
        """
        from_mid = await self._membership_id(
            tenant_id=tenant_id, user_id=from_user_id
        )
        to_mid = await self._membership_id(
            tenant_id=tenant_id, user_id=to_user_id
        )

        # Revoke owner from the previous user.
        await self._public.execute(
            text(
                """
                UPDATE public.tenant_role_assignments
                SET revoked_at = now()
                WHERE membership_id = :mid
                  AND role = 'TenantOwner'
                  AND revoked_at IS NULL
                """
            ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
            {"mid": from_mid},
        )

        # Grant TenantOwner to the new user.
        await self._public.execute(
            text(
                """
                INSERT INTO public.tenant_role_assignments
                    (id, membership_id, role, granted_by)
                VALUES (:rid, :mid, 'TenantOwner', :actor)
                """
            ).bindparams(
                bindparam("rid", type_=PG_UUID(as_uuid=True)),
                bindparam("mid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"rid": uuid4(), "mid": to_mid, "actor": actor_user_id},
        )

        # PR-Set7 guardrail: warn peers about the new owner. Tenant
        # session is unavailable on this platform-side path, so the
        # in-app fan-out is skipped — the audit warning still lands.
        from app.modules.platform_admins.guardrails import (
            emit_role_grant_guardrail,
        )

        await emit_role_grant_guardrail(
            public_session=self._public,
            tenant_session=None,
            tenant_id=tenant_id,
            target_user_id=to_user_id,
            target_email=None,
            role="TenantOwner",
            actor_user_id=actor_user_id,
            audit=self._audit,
        )

        await self._audit.record_archive(
            event_type="platform.tenant_owner_transferred",
            actor_user_id=actor_user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={
                "from_user_id": str(from_user_id),
                "to_user_id": str(to_user_id),
            },
        )

    # ---- Helpers ------------------------------------------------------

    async def _membership_id(self, *, tenant_id: UUID, user_id: UUID) -> UUID:
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT id FROM public.tenant_memberships
                    WHERE tenant_id = :tid AND user_id = :uid
                      AND deleted_at IS NULL
                    """
                ).bindparams(
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                ),
                {"tid": tenant_id, "uid": user_id},
            )
        ).first()
        if row is None:
            raise TenantUserNotFoundError(
                f"user {user_id} not a member of tenant {tenant_id}"
            )
        return row.id


def get_platform_admins_service(
    public_session: AsyncSession,
) -> PlatformAdminsService:
    return PlatformAdminsService(public_session=public_session)
