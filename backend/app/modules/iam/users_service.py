"""Tenant user management — list / invite / patch / suspend / delete.

Sister service to ``UserServiceImpl`` (which only does ``GET /me``).
Lives here so the existing /me path is untouched and tests for it
continue to pass without re-stubbing.

Lifecycle posture mirrors ``tenancy.service``:

* Keycloak calls happen inside the service in best-effort fashion.
  When ``keycloak_provisioning_enabled=False`` the Noop client raises
  ``KeycloakNotConfiguredError`` and we catch it — the DB rows still
  land and the row is marked `pending_provision` for an operator to
  finish via `kcadm.sh` per the runbook fallback.
* Keycloak failures on suspend/reactivate/delete are softer: we log,
  continue, and trust the next sync (or operator intervention) to
  reconcile. The DB is the source of truth for membership.status.
* Audit on every write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.iam.models import (
    TenantMembership,
    TenantRoleAssignment,
    User,
    UserPreferences,
)
from app.shared.keycloak import (
    KeycloakAdminClient,
    KeycloakError,
    get_keycloak_client,
)
from app.shared.keycloak.client import group_name_for


class TenantUserNotFoundError(LookupError):
    pass


class TenantUserAlreadyExistsError(Exception):
    def __init__(self, email: str) -> None:
        super().__init__(f"User with email {email!r} already exists in this tenant")
        self.email = email


class TenantUsersService:
    """Tenant-scoped user management.

    The session passed in is the platform-level admin session
    (``get_admin_db_session``) since users + memberships live in
    ``public.*``. The current tenant id comes from the request context.
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

    async def list_users(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        """All non-deleted memberships in the tenant + the joined user
        row + tenant_role_assignments + preferences. One DB round-trip
        for the join, then a second for preferences."""
        rows = (
            await self._public.execute(
                text(
                    """
                    SELECT u.id AS user_id,
                           u.email::text AS email,
                           u.full_name,
                           u.phone,
                           u.avatar_url,
                           u.status AS user_status,
                           u.last_login_at,
                           u.keycloak_subject,
                           m.id AS membership_id,
                           m.status AS membership_status,
                           m.joined_at,
                           COALESCE(
                               (
                                 SELECT array_agg(role)
                                   FROM public.tenant_role_assignments tra
                                  WHERE tra.membership_id = m.id
                                    AND tra.revoked_at IS NULL
                               ),
                               ARRAY[]::text[]
                           ) AS tenant_roles
                    FROM public.tenant_memberships m
                    JOIN public.users u ON u.id = m.user_id
                    WHERE m.tenant_id = :tid
                      AND m.deleted_at IS NULL
                      AND u.deleted_at IS NULL
                    ORDER BY u.full_name
                    """
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"tid": tenant_id},
            )
        ).mappings().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            user_id = row["user_id"]
            prefs = (
                await self._public.execute(
                    select(UserPreferences).where(UserPreferences.user_id == user_id)
                )
            ).scalars().one_or_none()
            out.append(
                {
                    "id": user_id,
                    "email": row["email"],
                    "full_name": row["full_name"],
                    "phone": row["phone"],
                    "avatar_url": row["avatar_url"],
                    "status": row["user_status"],
                    "last_login_at": row["last_login_at"],
                    "keycloak_subject": row["keycloak_subject"],
                    "membership_id": row["membership_id"],
                    "membership_status": row["membership_status"],
                    "joined_at": row["joined_at"],
                    "tenant_roles": list(row["tenant_roles"] or []),
                    "preferences": prefs,
                }
            )
        return out

    async def _resolve_tenant(
        self, *, tenant_schema: str
    ) -> tuple[UUID, str]:
        """Get (tenant_id, tenant_slug) from the request context's schema."""
        row = (
            await self._public.execute(
                text("SELECT id, slug FROM public.tenants WHERE schema_name = :s"),
                {"s": tenant_schema},
            )
        ).first()
        if row is None:
            raise LookupError(f"tenant not found for schema {tenant_schema!r}")
        return row.id, row.slug

    # ---- Writes -------------------------------------------------------

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str,
        phone: str | None,
        tenant_role: str,
        tenant_schema: str,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        tenant_id, slug = await self._resolve_tenant(tenant_schema=tenant_schema)

        # If this email already maps to a user with an active membership in
        # this tenant, surface 409 — caller should re-use them.
        existing = (
            await self._public.execute(
                text(
                    """
                    SELECT u.id, m.id AS membership_id
                    FROM public.users u
                    JOIN public.tenant_memberships m ON m.user_id = u.id
                    WHERE u.email = :email
                      AND m.tenant_id = :tid
                      AND m.deleted_at IS NULL
                    """
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"email": email, "tid": tenant_id},
            )
        ).first()
        if existing is not None:
            raise TenantUserAlreadyExistsError(email)

        # Reuse a global user row if email already exists — they may be a
        # member of another tenant. Otherwise insert.
        global_user_row = (
            await self._public.execute(
                text("SELECT id, keycloak_subject FROM public.users WHERE email = :e"),
                {"e": email},
            )
        ).first()

        keycloak_subject: str | None = (
            global_user_row.keycloak_subject if global_user_row else None
        )
        provisioning_status = "pending"

        # Try to invite via Keycloak. Best-effort; a Noop client raises
        # KeycloakNotConfiguredError and we mark the row as pending.
        if global_user_row is None:
            try:
                group_id = await self._kc.ensure_group(slug)
                kc_user_id = await self._kc.invite_user(
                    email=email,
                    full_name=full_name,
                    group_id=group_id,
                    roles=(tenant_role,),
                )
                keycloak_subject = kc_user_id
                provisioning_status = "succeeded"
            except KeycloakError as exc:
                self._log.warning(
                    "iam_invite_keycloak_failed",
                    email=email,
                    error=str(exc),
                )
                # Continue — the DB rows still land below.
                provisioning_status = "pending"
        elif keycloak_subject and not keycloak_subject.startswith("pending::"):
            # User already exists globally with a real Keycloak subject —
            # add them to the new tenant's group + assign tenant_role.
            try:
                group_id = await self._kc.ensure_group(slug)
                await self._kc.add_existing_user_to_group(
                    keycloak_user_id=keycloak_subject,
                    group_id=group_id,
                    roles=(tenant_role,),
                )
                provisioning_status = "succeeded"
            except KeycloakError as exc:
                self._log.warning(
                    "iam_invite_attach_existing_failed",
                    email=email,
                    error=str(exc),
                )
                provisioning_status = "pending"
        else:
            # Existing global row but Keycloak subject is itself pending
            # (the original invite couldn't reach KC). Nothing to attach
            # to — leave pending and the operator runbook handles both.
            provisioning_status = "pending"

        if global_user_row is None:
            user_id = uuid4()
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.users
                        (id, keycloak_subject, email, full_name, phone, status,
                         created_by, updated_by)
                    VALUES (:id, :kc_sub, :email, :name, :phone, 'active',
                            :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": user_id,
                    "kc_sub": keycloak_subject or f"pending::{email}",
                    "email": email,
                    "name": full_name,
                    "phone": phone,
                    "actor": actor_user_id,
                },
            )
        else:
            user_id = global_user_row.id

        membership_id = uuid4()
        try:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.tenant_memberships
                        (id, tenant_id, user_id, status, invited_by, joined_at,
                         created_by, updated_by)
                    VALUES (:id, :tid, :uid, 'active', :actor, NULL,
                            :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": membership_id,
                    "tid": tenant_id,
                    "uid": user_id,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            raise TenantUserAlreadyExistsError(email) from exc

        # Initial tenant role assignment.
        await self._public.execute(
            text(
                """
                INSERT INTO public.tenant_role_assignments
                    (membership_id, role, granted_by)
                VALUES (:mid, :role, :actor)
                """
            ).bindparams(
                bindparam("mid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"mid": membership_id, "role": tenant_role, "actor": actor_user_id},
        )

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_invited",
            actor_user_id=actor_user_id,
            subject_kind="tenant_membership",
            subject_id=membership_id,
            farm_id=None,
            details={
                "email": email,
                "tenant_role": tenant_role,
                "keycloak_provisioning": provisioning_status,
            },
        )
        return {
            "user_id": user_id,
            "membership_id": membership_id,
            "keycloak_provisioning": provisioning_status,
            "keycloak_subject": keycloak_subject,
        }

    async def update_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        updates: dict[str, Any],
        preferences_patch: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        # Confirm the user is a member of this tenant before allowing
        # an admin to edit them — prevents cross-tenant leak.
        await self._require_membership(user_id=user_id, tenant_id=tenant_id)
        if updates:
            # Static allow-list of editable user columns.
            allowed = {"full_name", "phone", "avatar_url"}
            sets: list[str] = []
            params: dict[str, Any] = {"id": user_id, "actor": actor_user_id}
            for col, value in updates.items():
                if col not in allowed:
                    continue
                sets.append(f"{col} = :{col}")
                params[col] = value
            if sets:
                sets.extend(["updated_by = :actor", "updated_at = now()"])
                await self._public.execute(
                    text(
                        f"UPDATE public.users SET {', '.join(sets)} "  # noqa: S608
                        "WHERE id = :id AND deleted_at IS NULL"
                    ).bindparams(
                        bindparam("id", type_=PG_UUID(as_uuid=True)),
                        bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    ),
                    params,
                )
        if preferences_patch:
            allowed_prefs = {
                "language",
                "numerals",
                "unit_system",
                "timezone",
                "date_format",
                "notification_channels",
                "dashboard_layout",
            }
            patch = {k: v for k, v in preferences_patch.items() if k in allowed_prefs}
            if patch:
                # Upsert the prefs row (lazy-creation).
                cols = ", ".join(["user_id", *patch.keys()])
                placeholders = ", ".join([":user_id", *(f":{k}" for k in patch.keys())])
                update_set = ", ".join(
                    [f"{k} = EXCLUDED.{k}" for k in patch.keys()] + ["updated_at = now()"]
                )
                bind_params: list[Any] = [
                    bindparam("user_id", type_=PG_UUID(as_uuid=True))
                ]
                await self._public.execute(
                    text(
                        f"INSERT INTO public.user_preferences ({cols}) "  # noqa: S608
                        f"VALUES ({placeholders}) "
                        f"ON CONFLICT (user_id) DO UPDATE SET {update_set}"
                    ).bindparams(*bind_params),
                    {"user_id": user_id, **patch},
                )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_updated",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            farm_id=None,
            details={
                "fields": sorted(updates.keys()) if updates else [],
                "preferences": sorted((preferences_patch or {}).keys()),
            },
        )

    async def suspend_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        await self._require_membership(user_id=user_id, tenant_id=tenant_id)
        await self._set_membership_status(
            user_id=user_id, tenant_id=tenant_id, status="suspended"
        )
        kc_subject = await self._user_keycloak_subject(user_id=user_id)
        if kc_subject and not kc_subject.startswith("pending::"):
            try:
                await self._kc.disable_user(keycloak_user_id=kc_subject)
            except KeycloakError as exc:
                self._log.warning("iam_suspend_keycloak_failed", error=str(exc))
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_suspended",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            farm_id=None,
            details={},
        )

    async def reactivate_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        await self._require_membership(
            user_id=user_id, tenant_id=tenant_id, allow_suspended=True
        )
        await self._set_membership_status(
            user_id=user_id, tenant_id=tenant_id, status="active"
        )
        kc_subject = await self._user_keycloak_subject(user_id=user_id)
        if kc_subject and not kc_subject.startswith("pending::"):
            try:
                await self._kc.enable_user(keycloak_user_id=kc_subject)
            except KeycloakError as exc:
                self._log.warning("iam_reactivate_keycloak_failed", error=str(exc))
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            farm_id=None,
            details={},
        )

    async def delete_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        await self._require_membership(
            user_id=user_id, tenant_id=tenant_id, allow_suspended=True
        )
        # Soft-delete the membership; do NOT remove the global user row
        # because they may belong to other tenants.
        await self._public.execute(
            text(
                "UPDATE public.tenant_memberships "
                "SET deleted_at = now(), status = 'archived', "
                "    updated_by = :actor, updated_at = now() "
                "WHERE user_id = :uid AND tenant_id = :tid AND deleted_at IS NULL"
            ).bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"uid": user_id, "tid": tenant_id, "actor": actor_user_id},
        )
        # If the user has no other active memberships, soft-delete the
        # global user row + their Keycloak account so a long-since-departed
        # employee isn't left enabled.
        remaining = (
            await self._public.execute(
                text(
                    "SELECT count(*) AS c FROM public.tenant_memberships "
                    "WHERE user_id = :uid AND deleted_at IS NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).first()
        if remaining is not None and int(remaining.c) == 0:
            await self._public.execute(
                text(
                    "UPDATE public.users "
                    "SET deleted_at = now(), status = 'archived', "
                    "    updated_by = :actor, updated_at = now() "
                    "WHERE id = :uid AND deleted_at IS NULL"
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "actor": actor_user_id},
            )
            kc_subject = await self._user_keycloak_subject(user_id=user_id)
            if kc_subject and not kc_subject.startswith("pending::"):
                try:
                    await self._kc.delete_user(keycloak_user_id=kc_subject)
                except KeycloakError as exc:
                    self._log.warning("iam_delete_keycloak_failed", error=str(exc))
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_deleted",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            farm_id=None,
            details={},
        )

    # ---- Helpers ------------------------------------------------------

    async def _require_membership(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        allow_suspended: bool = False,
    ) -> None:
        clauses = [
            "m.user_id = :uid",
            "m.tenant_id = :tid",
            "m.deleted_at IS NULL",
        ]
        if not allow_suspended:
            clauses.append("m.status = 'active'")
        sql = (
            "SELECT 1 FROM public.tenant_memberships m WHERE "
            + " AND ".join(clauses)
            + " LIMIT 1"
        )
        row = (
            await self._public.execute(
                text(sql).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            raise TenantUserNotFoundError(
                f"user {user_id} not a member of tenant {tenant_id}"
            )

    async def _set_membership_status(
        self, *, user_id: UUID, tenant_id: UUID, status: str
    ) -> None:
        await self._public.execute(
            text(
                "UPDATE public.tenant_memberships SET status = :status, "
                "updated_at = now() "
                "WHERE user_id = :uid AND tenant_id = :tid AND deleted_at IS NULL"
            ).bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
            ),
            {"uid": user_id, "tid": tenant_id, "status": status},
        )

    async def _user_keycloak_subject(self, *, user_id: UUID) -> str | None:
        row = (
            await self._public.execute(
                text(
                    "SELECT keycloak_subject FROM public.users WHERE id = :uid"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).first()
        return row.keycloak_subject if row is not None else None


def get_tenant_users_service(public_session: AsyncSession) -> TenantUsersService:
    return TenantUsersService(public_session=public_session)


# Silence unused-import warnings — kept for potential future caller use.
_ = group_name_for
_ = User
_ = TenantMembership
_ = TenantRoleAssignment
_ = datetime
_ = UTC
