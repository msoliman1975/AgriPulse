"""Self-service platform admin management.

Backs the `/platform/admins` UI in the Platform Management Portal.
Mirrors Keycloak's `platform_role` user attribute into a public DB
table (`public.platform_role_assignments`) so the listing page can
render without round-tripping the Keycloak admin API on every load.

Source of truth: still Keycloak (the JWT claim is what
`requires_capability` reads). The DB mirror is a convenience for
listing + audit.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.iam.users_service import TenantUserAlreadyExistsError
from app.shared.keycloak import KeycloakAdminClient, KeycloakError, get_keycloak_client


class PlatformAdminNotFoundError(LookupError):
    pass


class PlatformAdminsRoleService:
    """List/invite/remove platform admins.

    Distinct from `platform_admins.service.PlatformAdminsService`
    (which manages *tenant* admins on any tenant). This one operates
    on platform-tier role assignments — the seed PlatformAdmin and
    any extras invited via the /platform/admins UI.
    """

    def __init__(
        self,
        *,
        public_session: AsyncSession,
        keycloak: KeycloakAdminClient | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._public = public_session
        self._kc = keycloak or get_keycloak_client()
        self._audit = audit or get_audit_service()
        self._log = get_logger(__name__)

    # ---- Reads --------------------------------------------------------

    async def list_admins(self) -> list[dict[str, Any]]:
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT u.id AS user_id,
                           u.email::text AS email,
                           u.full_name,
                           u.keycloak_subject,
                           pra.role AS role,
                           pra.granted_at AS granted_at,
                           pra.granted_by AS granted_by
                    FROM public.platform_role_assignments pra
                    JOIN public.users u ON u.id = pra.user_id
                    WHERE pra.revoked_at IS NULL
                      AND u.deleted_at IS NULL
                    ORDER BY pra.role, u.full_name
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    # ---- Writes -------------------------------------------------------

    async def invite_admin(
        self,
        *,
        email: str,
        full_name: str,
        role: str,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Invite a new platform admin.

        Posture mirrors `iam.users_service.invite_user`:
          1. Try Keycloak first. If it succeeds, the JWT claim will
             carry `platform_role` on the user's next sign-in.
          2. Insert a `public.users` row + a
             `public.platform_role_assignments` row.
          3. Return the user_id + KC provisioning status so the UI
             can surface the right success message.
        """
        if role not in ("PlatformAdmin", "PlatformSupport"):
            raise ValueError(f"Invalid platform role: {role!r}")

        # If the email already maps to an active platform admin, surface
        # 409 — caller should re-use them.
        existing = (
            await self._public.execute(
                text(
                    """
                    SELECT pra.id, u.id AS user_id
                    FROM public.platform_role_assignments pra
                    JOIN public.users u ON u.id = pra.user_id
                    WHERE u.email = :email
                      AND pra.role = :role
                      AND pra.revoked_at IS NULL
                    """
                ),
                {"email": email, "role": role},
            )
        ).first()
        if existing is not None:
            raise TenantUserAlreadyExistsError(email)

        global_user = (
            await self._public.execute(
                text("SELECT id, keycloak_subject FROM public.users WHERE email = :e"),
                {"e": email},
            )
        ).first()

        kc_subject: str | None = global_user.keycloak_subject if global_user else None
        provisioning_status = "pending"

        if global_user is None:
            try:
                kc_user_id = await self._kc.invite_platform_admin(
                    email=email, full_name=full_name, role=role
                )
                kc_subject = kc_user_id
                provisioning_status = "succeeded"
            except KeycloakError as exc:
                self._log.warning(
                    "platform_admin_invite_keycloak_failed",
                    email=email,
                    error=str(exc),
                )
                provisioning_status = "pending"
        elif kc_subject and not kc_subject.startswith("pending::"):
            # User already exists globally — just set the platform_role
            # attribute on their existing KC account.
            try:
                await self._kc.set_platform_role(keycloak_user_id=kc_subject, role=role)
                provisioning_status = "succeeded"
            except KeycloakError as exc:
                self._log.warning(
                    "platform_admin_attach_keycloak_failed",
                    email=email,
                    error=str(exc),
                )
                provisioning_status = "pending"

        # Upsert the public.users row.
        if global_user is None:
            user_id = uuid4()
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.users
                        (id, keycloak_subject, email, full_name, status,
                         created_by, updated_by)
                    VALUES (:id, :sub, :email, :name, 'active', :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": user_id,
                    "sub": kc_subject or f"pending::{email}",
                    "email": email,
                    "name": full_name,
                    "actor": actor_user_id,
                },
            )
        else:
            user_id = global_user.id

        # Insert the role assignment. Partial-unique index makes
        # re-invites safe — a UniqueViolation here means the role was
        # already active (handled above), so we treat it as a soft no-op.
        try:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.platform_role_assignments
                        (id, user_id, role, granted_by)
                    VALUES (:id, :uid, :role, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": uuid4(),
                    "uid": user_id,
                    "role": role,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            raise TenantUserAlreadyExistsError(email) from exc

        await self._audit.record_archive(
            event_type="platform.platform_admin_added",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            details={
                "email": email,
                "role": role,
                "keycloak_provisioning": provisioning_status,
            },
        )
        return {
            "user_id": user_id,
            "keycloak_subject": kc_subject,
            "keycloak_provisioning": provisioning_status,
            "role": role,
        }

    async def remove_admin(
        self,
        *,
        user_id: UUID,
        role: str,
        actor_user_id: UUID | None,
    ) -> None:
        """Soft-revoke the platform-role assignment + clear the KC
        attribute. Safe-by-default: refuses to remove the LAST
        PlatformAdmin (a tenant has to keep at least one Owner — the
        platform should keep at least one Admin)."""
        if role == "PlatformAdmin":
            count = (
                await self._public.execute(
                    text(
                        """
                        SELECT count(*) AS c
                        FROM public.platform_role_assignments
                        WHERE role = 'PlatformAdmin' AND revoked_at IS NULL
                        """
                    )
                )
            ).scalar_one()
            if int(count) <= 1:
                raise ValueError(
                    "Cannot remove the last PlatformAdmin. Promote another "
                    "user first, then revoke this one."
                )

        result = await self._public.execute(
            text(
                """
                UPDATE public.platform_role_assignments
                SET revoked_at = now()
                WHERE user_id = :uid AND role = :role AND revoked_at IS NULL
                """
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id, "role": role},
        )
        if (cast("CursorResult[Any]", result).rowcount or 0) == 0:
            raise PlatformAdminNotFoundError(f"user {user_id} is not a {role}")

        # Clear the Keycloak attribute (best-effort).
        kc_sub = await self._user_keycloak_subject(user_id=user_id)
        if kc_sub and not kc_sub.startswith("pending::"):
            try:
                await self._kc.clear_platform_role(keycloak_user_id=kc_sub)
            except KeycloakError as exc:
                self._log.warning(
                    "platform_admin_remove_keycloak_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )

        await self._audit.record_archive(
            event_type="platform.platform_admin_removed",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            details={"role": role},
        )

    # ---- Helpers ------------------------------------------------------

    async def _user_keycloak_subject(self, *, user_id: UUID) -> str | None:
        row = (
            await self._public.execute(
                text("SELECT keycloak_subject FROM public.users WHERE id = :uid").bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True))
                ),
                {"uid": user_id},
            )
        ).first()
        return row.keycloak_subject if row is not None else None


def get_platform_admins_role_service(
    public_session: AsyncSession,
) -> PlatformAdminsRoleService:
    return PlatformAdminsRoleService(public_session=public_session)
