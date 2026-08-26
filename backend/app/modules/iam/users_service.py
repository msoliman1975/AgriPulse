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
from sqlalchemy.dialects.postgresql import ARRAY
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
from app.shared.keycloak.field_identity import is_synthetic_email
from app.shared.rbac import FARM_TIER_ROLES, assignment_tier


class TenantUserNotFoundError(LookupError):
    pass


class TenantUserAlreadyExistsError(Exception):
    def __init__(self, email: str) -> None:
        super().__init__(f"User with email {email!r} already exists in this tenant")
        self.email = email


class FarmsNotInTenantError(LookupError):
    """One or more requested farm ids are not live farms of this tenant.

    Checked before any write. `farm_scopes` lives in `public` and carries
    only a logical cross-schema reference to the tenant's farms, so nothing
    in the database would reject a farm id belonging to another tenant — the
    grant would be accepted and then resolve against a farm the member
    cannot see.
    """

    def __init__(self, farm_ids: tuple[UUID, ...]) -> None:
        super().__init__("not farms of this tenant: " + ", ".join(str(f) for f in farm_ids))
        self.farm_ids = farm_ids


class AlreadyInAnotherTenantError(Exception):
    """This person already belongs to a different tenant.

    A person belongs to exactly one tenant. The reason is one attribute:
    Keycloak's `tenant_id` is single-valued and the JWT carries one value, so
    a request resolves exactly one tenant schema, while `farm_scopes` is
    multi-valued and spans every membership. A second membership therefore
    produces a token that names farms in a tenant it cannot reach — the API
    authorizes the farm and then looks for it in the wrong schema, with no
    error anywhere.

    Raised before anything is written, so a refused invite leaves neither a
    Keycloak group membership nor a half-provisioned row behind.
    """

    def __init__(self, email: str, tenant_slug: str) -> None:
        super().__init__(
            f"{email} already belongs to the tenant {tenant_slug!r}. "
            "A person can belong to only one tenant. Remove them from that "
            "tenant first, or invite them under a different address."
        )
        self.email = email
        self.tenant_slug = tenant_slug


class LastTenantOwnerError(Exception):
    """The change would leave the tenant with no active TenantOwner."""

    def __init__(self, tenant_id: UUID) -> None:
        super().__init__(
            "a tenant must keep at least one TenantOwner; appoint another "
            "owner before changing this one"
        )
        self.tenant_id = tenant_id


class TenantUsersService:
    """Tenant-scoped user management.

    The session passed in is the platform-level admin session
    (``get_admin_db_session``) since users + memberships live in
    ``public.*``. The current tenant id comes from the request context.

    `tenant_session` is optional. When provided, the TenantAdmin/Owner
    grant guardrail (PR-Set7) fans out an in_app_inbox notification to
    peer admins. Without it, the audit-warning still fires; only the
    in-app heads-up is skipped.
    """

    def __init__(
        self,
        *,
        public_session: AsyncSession,
        tenant_session: AsyncSession | None = None,
        keycloak: KeycloakAdminClient | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session
        self._kc = keycloak or get_keycloak_client()
        self._audit = audit or get_audit_service()
        self._log = get_logger(__name__)

    # ---- Reads --------------------------------------------------------

    async def list_users(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        """All non-deleted memberships in the tenant + the joined user
        row + tenant_role_assignments + farm_scopes + preferences. One DB
        round-trip for the join, then a second for preferences.

        Both role tiers are returned because a member holds exactly one of
        them: a farm-tier member has no `tenant_role_assignments` row at
        all, so a reader that looks only at `tenant_roles` shows them as
        having no role.
        """
        rows = (
            (
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
                           ) AS tenant_roles,
                           COALESCE(
                               (
                                 SELECT jsonb_agg(
                                            jsonb_build_object(
                                                'farm_id', fs.farm_id,
                                                'role', fs.role
                                            )
                                            ORDER BY fs.role, fs.farm_id
                                        )
                                   FROM public.farm_scopes fs
                                  WHERE fs.membership_id = m.id
                                    AND fs.revoked_at IS NULL
                               ),
                               '[]'::jsonb
                           ) AS farm_roles
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
            )
            .mappings()
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            user_id = row["user_id"]
            prefs = (
                (
                    await self._public.execute(
                        select(UserPreferences).where(UserPreferences.user_id == user_id)
                    )
                )
                .scalars()
                .one_or_none()
            )
            # A field worker's address is synthesised from their phone to
            # satisfy NOT NULL/UNIQUE; nothing can be delivered to it. Pickers
            # fall back to `full_name || email`, which renders
            # `+2010…@scouts…` where a name belongs and reads as a data-entry
            # error somebody will try to "fix". Say which handle is real
            # instead of making every caller sniff the domain.
            synthetic = is_synthetic_email(row["email"])
            out.append(
                {
                    "id": user_id,
                    "email": row["email"],
                    "identity_kind": "phone" if synthetic else "email",
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
                    "farm_roles": list(row["farm_roles"] or []),
                    "preferences": prefs,
                }
            )
        return out

    async def _resolve_tenant(self, *, tenant_schema: str) -> tuple[UUID, str]:
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

    async def _assert_farms_in_tenant(self, *, farm_ids: tuple[UUID, ...]) -> None:
        """Every id must be a live farm of the caller's tenant.

        Reads through the tenant session, whose search_path is already pinned
        to the caller's schema, so a farm id from another tenant simply is not
        found. Nothing downstream would catch it: `public.farm_scopes.farm_id`
        is a logical reference, not a foreign key (see
        `feedback_no_tenant_to_public_foreign_keys` — a real FK there would
        make DROP SCHEMA take an ACCESS EXCLUSIVE lock platform-wide).
        """
        if not farm_ids:
            return
        if self._tenant is None:
            raise FarmsNotInTenantError(farm_ids)
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM farms " "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                ).bindparams(
                    bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))),
                ),
                {"ids": list(farm_ids)},
            )
        ).all()
        found = {r.id for r in rows}
        missing = tuple(f for f in farm_ids if f not in found)
        if missing:
            raise FarmsNotInTenantError(missing)

    async def _assert_free_of_other_tenants(self, *, email: str, tenant_id: UUID) -> None:
        """Refuse an invite for somebody who is live in a different tenant.

        Matched on the email rather than a user id because that is all an
        invite carries, and it is the same key `public.users` is unique on.
        Archived memberships (`deleted_at IS NOT NULL`) do not count: a person
        who left one tenant is free to be invited by another.
        """
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT t.slug AS slug
                      FROM public.users u
                      JOIN public.tenant_memberships m ON m.user_id = u.id
                      JOIN public.tenants t ON t.id = m.tenant_id
                     WHERE u.email = :email
                       AND m.tenant_id <> :tid
                       AND m.deleted_at IS NULL
                       AND u.deleted_at IS NULL
                     LIMIT 1
                    """
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"email": email, "tid": tenant_id},
            )
        ).first()
        if row is not None:
            raise AlreadyInAnotherTenantError(email, str(row.slug))

    async def _sync_farm_scopes_to_kc(self, *, membership_id: UUID) -> None:
        """Re-project a membership's active farm scopes into Keycloak.

        The JWT carries `farm_scopes`, so without this the member signs in
        and is 403 on every farm endpoint — the same failure the field
        enrolment path documents. Best-effort: a Keycloak hiccup must not
        roll back a grant that is already committed to the database.
        """
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT u.keycloak_subject AS kc,
                           COALESCE(
                               (
                                 SELECT jsonb_agg(DISTINCT jsonb_build_object(
                                            'farm_id', fs.farm_id::text,
                                            'role', fs.role))
                                   FROM public.tenant_memberships m2
                                   JOIN public.farm_scopes fs
                                     ON fs.membership_id = m2.id
                                    AND fs.revoked_at IS NULL
                                  WHERE m2.user_id = u.id
                                    AND m2.deleted_at IS NULL
                                    AND m2.status = 'active'
                               ),
                               '[]'::jsonb
                           ) AS scopes
                    FROM public.tenant_memberships m
                    JOIN public.users u ON u.id = m.user_id
                    WHERE m.id = :mid
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id},
            )
        ).first()
        # The attribute is per Keycloak user, not per membership, so the
        # aggregation walks out to the user rather than reading this
        # membership's rows. Since a person belongs to one tenant that is now
        # the same set, but the shape is kept deliberately: it also drops the
        # scopes of an archived membership, which reading one membership's
        # rows would leave in the token after an offboarding.
        if row is None or not row.kc or row.kc.startswith("pending::"):
            return
        try:
            await self._kc.set_farm_scopes(keycloak_user_id=row.kc, scopes=list(row.scopes or []))
        except Exception as exc:  # best-effort, never fatal
            self._log.warning(
                "iam_farm_scopes_keycloak_sync_failed",
                membership_id=str(membership_id),
                error=str(exc),
            )

    async def _grant_role(
        self,
        *,
        membership_id: UUID,
        role: str,
        farm_ids: tuple[UUID, ...],
        actor_user_id: UUID | None,
    ) -> None:
        """Write one role for a membership, into the table its tier uses.

        `granted_by` is a nullable FK to `public.users` in both tables, so
        the actor bind is wrapped in a SELECT: an actor id that is not a real
        user row null-coerces instead of raising IntegrityError. That is the
        same pattern the surrounding INSERTs use.
        """
        if assignment_tier(role) == "farm" and not farm_ids:
            # The loop below would write nothing and return successfully,
            # leaving a member with no role at all. The API layer already
            # rejects this, but the service is called directly by scripts
            # and tests, so it fails here rather than silently.
            raise ValueError(
                f"role {role!r} is granted per farm; farm_ids must name at "
                f"least one farm (farm-tier roles: {', '.join(FARM_TIER_ROLES)})"
            )
        if assignment_tier(role) == "tenant":
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.tenant_role_assignments
                        (membership_id, role, granted_by)
                    VALUES (:mid, :role,
                            (SELECT id FROM public.users WHERE id = :actor))
                    """
                ).bindparams(
                    bindparam("mid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {"mid": membership_id, "role": role, "actor": actor_user_id},
            )
            return

        for farm_id in farm_ids:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.farm_scopes
                        (membership_id, farm_id, role, granted_by)
                    VALUES (:mid, :fid, :role,
                            (SELECT id FROM public.users WHERE id = :actor))
                    """
                ).bindparams(
                    bindparam("mid", type_=PG_UUID(as_uuid=True)),
                    bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "mid": membership_id,
                    "fid": farm_id,
                    "role": role,
                    "actor": actor_user_id,
                },
            )

    async def _revoke_all_roles(self, *, membership_id: UUID) -> dict[str, Any]:
        """Revoke every active role of both tiers. Returns what was revoked.

        Revoke, not delete: both tables carry `revoked_at`, and that history
        is what answers "who could do this last March?" for an auditor.
        """
        tenant_rows = (
            await self._public.execute(
                text(
                    """
                    UPDATE public.tenant_role_assignments
                       SET revoked_at = now()
                     WHERE membership_id = :mid AND revoked_at IS NULL
                    RETURNING role
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id},
            )
        ).all()
        farm_rows = (
            await self._public.execute(
                text(
                    """
                    UPDATE public.farm_scopes
                       SET revoked_at = now()
                     WHERE membership_id = :mid AND revoked_at IS NULL
                    RETURNING farm_id, role
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id},
            )
        ).all()
        return {
            "tenant_roles": [r.role for r in tenant_rows],
            "farm_roles": [{"farm_id": str(r.farm_id), "role": r.role} for r in farm_rows],
        }

    async def assign_role(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        tenant_schema: str,
        role: str,
        farm_ids: tuple[UUID, ...],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Replace a member's role. Revokes whatever they held first.

        Replacement rather than addition, because the capability resolver
        stops at the first tier that grants what it is checking. Two live
        roles would mean no screen could say which one is in force, and
        revoking the one a reader can see would take nothing away.

        Crossing tiers is allowed in both directions and is the point of the
        endpoint: promoting a Scout to TenantAdmin drops their farm scopes
        and gives them a tenant assignment, and the reverse demotes.
        """
        tier = assignment_tier(role)
        farm_ids = tuple(farm_ids)
        await self._assert_farms_in_tenant(farm_ids=farm_ids)

        membership = (
            await self._public.execute(
                text(
                    """
                    SELECT m.id AS membership_id, u.email::text AS email
                    FROM public.tenant_memberships m
                    JOIN public.users u ON u.id = m.user_id
                    WHERE m.user_id = :uid
                      AND m.tenant_id = :tid
                      AND m.deleted_at IS NULL
                      AND u.deleted_at IS NULL
                    """
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )
        ).first()
        if membership is None:
            raise TenantUserNotFoundError(str(user_id))

        # A tenant must keep at least one owner. Checked before the revoke,
        # because the revoke below would otherwise remove the last one and
        # leave nobody able to appoint a replacement.
        await self._assert_not_last_owner(
            membership_id=membership.membership_id,
            tenant_id=tenant_id,
            new_role=role,
        )

        revoked = await self._revoke_all_roles(membership_id=membership.membership_id)
        await self._grant_role(
            membership_id=membership.membership_id,
            role=role,
            farm_ids=farm_ids,
            actor_user_id=actor_user_id,
        )

        # Keycloak carries both halves of the answer: `tenant_role` is one
        # user attribute and `farm_scopes` is another. A tier change has to
        # rewrite both, or the JWT keeps granting the role that was just
        # revoked until something else happens to rewrite the attribute.
        await self._sync_role_to_kc(
            membership_id=membership.membership_id,
            tenant_id=tenant_id,
            tenant_role=role if tier == "tenant" else None,
        )
        await self._sync_farm_scopes_to_kc(membership_id=membership.membership_id)

        from app.modules.platform_admins.guardrails import (
            emit_role_grant_guardrail,
            is_guarded_role,
        )

        if is_guarded_role(role):
            await emit_role_grant_guardrail(
                public_session=self._public,
                tenant_session=self._tenant,
                tenant_id=tenant_id,
                target_user_id=user_id,
                target_email=membership.email,
                role=role,  # type: ignore[arg-type]
                actor_user_id=actor_user_id,
                audit=self._audit,
            )

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_role_changed",
            actor_user_id=actor_user_id,
            subject_kind="tenant_membership",
            subject_id=membership.membership_id,
            farm_id=None,
            details={
                "email": membership.email,
                "role": role,
                "role_tier": tier,
                "farm_ids": [str(f) for f in farm_ids],
                "revoked": revoked,
            },
        )
        return {
            "membership_id": membership.membership_id,
            "role": role,
            "role_tier": tier,
            "farm_ids": list(farm_ids),
            "revoked": revoked,
        }

    async def _assert_not_last_owner(
        self, *, membership_id: UUID, tenant_id: UUID, new_role: str
    ) -> None:
        """Refuse a change that would leave the tenant with no TenantOwner.

        TenantOwner is the only role holding `tenant.transfer_ownership`, so
        a tenant with none of them cannot appoint one and recovery needs a
        PlatformAdmin. The platform-admins revoke path already enforces the
        same rule; this is the second door into the same state.
        """
        if new_role == "TenantOwner":
            return
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT
                        bool_or(tra.membership_id = :mid) AS is_owner,
                        count(*) AS owners
                    FROM public.tenant_role_assignments tra
                    JOIN public.tenant_memberships m ON m.id = tra.membership_id
                    WHERE m.tenant_id = :tid
                      AND m.deleted_at IS NULL
                      AND tra.revoked_at IS NULL
                      AND tra.role = 'TenantOwner'
                    """
                ).bindparams(
                    bindparam("mid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"mid": membership_id, "tid": tenant_id},
            )
        ).first()
        if row is not None and row.is_owner and row.owners <= 1:
            raise LastTenantOwnerError(tenant_id)

    async def _sync_role_to_kc(
        self, *, membership_id: UUID, tenant_id: UUID, tenant_role: str | None
    ) -> None:
        """Rewrite the Keycloak `tenant_role` attribute after a change.

        `tenant_role=None` means the member moved to the farm tier, so the
        attribute is cleared and the claim stops granting the old
        tenant-wide role. Best-effort like every other Keycloak call here:
        the database is the source of truth and reconcile catches up.
        """
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT u.keycloak_subject AS kc
                    FROM public.tenant_memberships m
                    JOIN public.users u ON u.id = m.user_id
                    WHERE m.id = :mid
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id},
            )
        ).first()
        if row is None or not row.kc or row.kc.startswith("pending::"):
            return
        try:
            await self._kc.set_tenant_attributes(
                keycloak_user_id=row.kc,
                tenant_id=tenant_id,
                tenant_role=tenant_role,
            )
        except Exception as exc:  # best-effort, never fatal
            self._log.warning(
                "iam_tenant_role_keycloak_sync_failed",
                membership_id=str(membership_id),
                error=str(exc),
            )

    async def _provision_in_keycloak(
        self,
        *,
        email: str,
        full_name: str,
        slug: str,
        tenant_id: UUID,
        kc_roles: tuple[str, ...],
        existing_subject: str | None,
        is_new_global_user: bool,
    ) -> tuple[str | None, str, bool, str | None]:
        """Create or attach the Keycloak user for an invite.

        Returns ``(subject, provisioning_status, email_sent, temp_password)``.

        Best-effort throughout: a Noop client raises
        ``KeycloakNotConfiguredError`` and a real one can simply be down. In
        either case the caller still writes the database rows and the row is
        left ``pending`` for an operator to finish per the runbook.

        ``kc_roles`` is empty for a farm-tier invite. That is not the same as
        "no attributes": ``tenant_id`` is still written, because a member
        with no tenant claim has no tenant context at all.
        """
        keycloak_subject = existing_subject
        # First-login credential outcome (IH-2). For a brand-new KC user we
        # either emailed the reset link or minted a temp password the caller
        # hands off. On the attach-existing path the user already has a
        # credential, so there is nothing new to surface.
        keycloak_email_sent = False
        temporary_password: str | None = None

        if is_new_global_user:
            try:
                group_id = await self._kc.ensure_group(slug)
                invite_result = await self._kc.invite_user(
                    email=email,
                    full_name=full_name,
                    group_id=group_id,
                    roles=kc_roles,
                    tenant_id=tenant_id,
                )
                return (
                    invite_result.keycloak_user_id,
                    "succeeded",
                    invite_result.email_sent,
                    invite_result.temporary_password,
                )
            except KeycloakError as exc:
                self._log.warning("iam_invite_keycloak_failed", email=email, error=str(exc))
                return keycloak_subject, "pending", keycloak_email_sent, temporary_password

        if keycloak_subject and not keycloak_subject.startswith("pending::"):
            # The user exists globally with a real subject — add them to this
            # tenant's group and set this tenant's attributes.
            try:
                group_id = await self._kc.ensure_group(slug)
                await self._kc.add_existing_user_to_group(
                    keycloak_user_id=keycloak_subject,
                    group_id=group_id,
                    roles=kc_roles,
                    tenant_id=tenant_id,
                )
                return keycloak_subject, "succeeded", keycloak_email_sent, temporary_password
            except KeycloakError as exc:
                self._log.warning("iam_invite_attach_existing_failed", email=email, error=str(exc))
                return keycloak_subject, "pending", keycloak_email_sent, temporary_password

        # Existing global row whose Keycloak subject is itself pending: the
        # original invite never reached Keycloak. Nothing to attach to, so
        # leave it pending and let the operator runbook cover both rows.
        return keycloak_subject, "pending", keycloak_email_sent, temporary_password

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str,
        phone: str | None,
        tenant_role: str,
        tenant_schema: str,
        actor_user_id: UUID | None,
        farm_ids: tuple[UUID, ...] = (),
    ) -> dict[str, Any]:
        """Invite a member and give them exactly one role.

        `tenant_role` is now any role in `TENANT_ASSIGNABLE_ROLES`, not only
        the tenant tier. A farm-tier role is written to `public.farm_scopes`
        for each named farm and leaves the member with no tenant role at all
        — the shape a scout has had since PR #269/#270.
        """
        tier = assignment_tier(tenant_role)
        farm_ids = tuple(farm_ids)
        tenant_id, slug = await self._resolve_tenant(tenant_schema=tenant_schema)
        # Before anything is created, so a bad farm id does not leave a
        # provisioned Keycloak user and a member with no role behind.
        await self._assert_farms_in_tenant(farm_ids=farm_ids)
        # Only a tenant-tier role becomes the Keycloak `tenant_role`
        # attribute and a realm role. A farm role is not a realm role (see
        # APP_REALM_ROLES) and would be rejected by the assignment guard.
        kc_roles: tuple[str, ...] = (tenant_role,) if tier == "tenant" else ()

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

        # A person belongs to one tenant. Checked before Keycloak is touched,
        # because `_provision_in_keycloak` writes `tenant_id` on the attach
        # path and that attribute holds a single value — provisioning first
        # and refusing afterwards would leave the person pointing at this
        # tenant while their real one still holds their rows.
        await self._assert_free_of_other_tenants(email=email, tenant_id=tenant_id)

        # Reuse the global user row when the email already exists. After the
        # check above the only way to get here is a person whose memberships
        # are all archived — someone who left another tenant and is being
        # taken on by this one. Their Keycloak account is reused rather than
        # duplicated, because the email is the username.
        global_user_row = (
            await self._public.execute(
                text("SELECT id, keycloak_subject, deleted_at FROM public.users WHERE email = :e"),
                {"e": email},
            )
        ).first()

        # An archived row is a person who was offboarded from their last
        # tenant: `delete_user` soft-deletes `public.users` and deletes their
        # Keycloak account once no membership survives. Reusing that row as-is
        # would hand them a membership and no way to sign in — `get_me` raises
        # on a deleted user, and the account it points at no longer exists.
        #
        # This path used to be a rarity, because somebody could simply be
        # invited into a second tenant. Now that a person belongs to one
        # tenant, offboard-then-reinvite is the only way to move between them,
        # so it is the path the refusal message sends people down and it has
        # to work. Local id kept — their audit trail and any logical reference
        # to it survive — while Keycloak is provisioned fresh.
        revived = global_user_row is not None and global_user_row.deleted_at is not None

        (
            keycloak_subject,
            provisioning_status,
            keycloak_email_sent,
            temporary_password,
        ) = await self._provision_in_keycloak(
            email=email,
            full_name=full_name,
            slug=slug,
            tenant_id=tenant_id,
            kc_roles=kc_roles,
            existing_subject=(
                None if revived else (global_user_row.keycloak_subject if global_user_row else None)
            ),
            # A revived person needs a Keycloak account created, not attached
            # to: theirs was deleted when they were offboarded.
            is_new_global_user=global_user_row is None or revived,
        )

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
            if revived:
                # Bring the row back and repoint it at the new Keycloak
                # account. Without the `keycloak_subject` update they would
                # keep the id of an account that was deleted, and every token
                # check would resolve to nobody.
                await self._public.execute(
                    text(
                        """
                        UPDATE public.users
                           SET deleted_at = NULL,
                               status = 'active',
                               keycloak_subject = :kc_sub,
                               full_name = :name,
                               phone = COALESCE(:phone, phone),
                               updated_by = :actor,
                               updated_at = now()
                         WHERE id = :uid
                        """
                    ).bindparams(
                        bindparam("uid", type_=PG_UUID(as_uuid=True)),
                        bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    ),
                    {
                        "uid": user_id,
                        "kc_sub": keycloak_subject or f"pending::{email}",
                        "name": full_name,
                        "phone": phone,
                        "actor": actor_user_id,
                    },
                )

        membership_id = uuid4()
        # `invited_by` has a FK to public.users but is nullable. Wrap the
        # bind in a SELECT so an actor UUID that doesn't exist in
        # public.users null-coerces instead of raising IntegrityError.
        # The audit slots (created_by / updated_by) are bare nullable
        # UUIDs with no FK, so they keep the raw bind.
        try:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.tenant_memberships
                        (id, tenant_id, user_id, status, invited_by, joined_at,
                         created_by, updated_by)
                    VALUES (:id, :tid, :uid, 'active',
                            (SELECT id FROM public.users WHERE id = :actor),
                            NULL, :actor, :actor)
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

        # Initial role assignment, in whichever table the tier belongs to.
        await self._grant_role(
            membership_id=membership_id,
            role=tenant_role,
            farm_ids=farm_ids,
            actor_user_id=actor_user_id,
        )
        if tier == "farm":
            await self._sync_farm_scopes_to_kc(membership_id=membership_id)

        # PR-Set7 guardrail: log + notify peers when a high-trust role
        # was just granted.
        from app.modules.platform_admins.guardrails import (
            emit_role_grant_guardrail,
            is_guarded_role,
        )

        if is_guarded_role(tenant_role):
            await emit_role_grant_guardrail(
                public_session=self._public,
                tenant_session=self._tenant,
                tenant_id=tenant_id,
                target_user_id=user_id,
                target_email=email,
                role=tenant_role,  # type: ignore[arg-type]
                actor_user_id=actor_user_id,
                audit=self._audit,
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
                "role_tier": tier,
                "farm_ids": [str(f) for f in farm_ids],
                "keycloak_provisioning": provisioning_status,
            },
        )
        return {
            "user_id": user_id,
            "membership_id": membership_id,
            "keycloak_provisioning": provisioning_status,
            "keycloak_subject": keycloak_subject,
            "keycloak_email_sent": keycloak_email_sent,
            "temporary_password": temporary_password,
        }

    async def resend_invite(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Re-issue the first-login credential for a tenant member whose
        welcome email never arrived. Returns the same email_sent /
        temporary_password shape as ``invite_user`` so the UI can show a
        copy-able credential when SMTP is unavailable.

        A member still pending Keycloak provisioning (no real subject)
        can't be re-invited — surface that as ``pending`` so the caller
        knows to retry provisioning first."""
        await self._require_membership(user_id=user_id, tenant_id=tenant_id, allow_suspended=True)
        kc_subject = await self._user_keycloak_subject(user_id=user_id)
        if not kc_subject or kc_subject.startswith("pending::"):
            return {
                "keycloak_provisioning": "pending",
                "keycloak_email_sent": False,
                "temporary_password": None,
            }
        try:
            result = await self._kc.resend_invite(keycloak_user_id=kc_subject)
        except KeycloakError as exc:
            self._log.warning("iam_resend_invite_failed", user_id=str(user_id), error=str(exc))
            return {
                "keycloak_provisioning": "pending",
                "keycloak_email_sent": False,
                "temporary_password": None,
            }
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="iam.user_invite_resent",
            actor_user_id=actor_user_id,
            subject_kind="user",
            subject_id=user_id,
            farm_id=None,
            details={"keycloak_email_sent": result.email_sent},
        )
        return {
            "keycloak_provisioning": "succeeded",
            "keycloak_email_sent": result.email_sent,
            "temporary_password": result.temporary_password,
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
                        f"UPDATE public.users SET {', '.join(sets)} "
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
                placeholders = ", ".join([":user_id", *(f":{k}" for k in patch)])
                update_set = ", ".join(
                    [f"{k} = EXCLUDED.{k}" for k in patch] + ["updated_at = now()"]
                )
                bind_params: list[Any] = [bindparam("user_id", type_=PG_UUID(as_uuid=True))]
                await self._public.execute(
                    text(
                        f"INSERT INTO public.user_preferences ({cols}) "
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
        await self._set_membership_status(user_id=user_id, tenant_id=tenant_id, status="suspended")
        kc_subject = await self._user_keycloak_subject(user_id=user_id)
        if kc_subject and not kc_subject.startswith("pending::"):
            try:
                await self._kc.disable_user(keycloak_user_id=kc_subject)
                # Disabling stops the next refresh; it leaves any live access
                # token good until it expires and, on a field handset, leaves
                # an offline refresh token that has simply not been used yet.
                await self._kc.logout_user(keycloak_user_id=kc_subject)
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
        await self._require_membership(user_id=user_id, tenant_id=tenant_id, allow_suspended=True)
        await self._set_membership_status(user_id=user_id, tenant_id=tenant_id, status="active")
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

    async def _sync_scopes_and_end_sessions(self, *, user_id: UUID) -> None:
        """Push the user's surviving farm scopes to Keycloak, then log them out.

        Surviving means every scope on an active, undeleted membership. The
        claim is a property of the person, not of one membership, so the query
        starts at the user: reading the membership being archived would leave
        its revoked farms in the token, and reading only the caller's tenant
        would strip a scope this offboarding did not touch.
        """
        kc_subject = await self._user_keycloak_subject(user_id=user_id)
        if not kc_subject or kc_subject.startswith("pending::"):
            return
        rows = (
            await self._public.execute(
                text(
                    """
                    SELECT fs.farm_id, fs.role
                      FROM public.farm_scopes fs
                      JOIN public.tenant_memberships m ON m.id = fs.membership_id
                     WHERE m.user_id = :uid
                       AND fs.revoked_at IS NULL
                       AND m.deleted_at IS NULL
                       AND m.status = 'active'
                    """
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).all()
        scopes = [{"farm_id": str(r.farm_id), "role": str(r.role)} for r in rows]
        try:
            await self._kc.set_farm_scopes(keycloak_user_id=kc_subject, scopes=scopes)
            await self._kc.logout_user(keycloak_user_id=kc_subject)
        except KeycloakError as exc:
            self._log.warning(
                "iam_offboard_keycloak_sync_failed",
                user_id=str(user_id),
                error=str(exc),
            )

    async def delete_user(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        await self._require_membership(user_id=user_id, tenant_id=tenant_id, allow_suspended=True)
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
        # Revoke this membership's grants. The soft membership-delete does NOT
        # fire the ON DELETE CASCADE, so without this the tenant-role and
        # farm-scope rows linger as active (revoked_at IS NULL) pointing at an
        # archived membership. Scope by the membership(s) for (user, tenant).
        _membership_filter = (
            "membership_id IN (SELECT id FROM public.tenant_memberships "
            "WHERE user_id = :uid AND tenant_id = :tid)"
        )
        for table in ("public.tenant_role_assignments", "public.farm_scopes"):
            await self._public.execute(
                text(
                    f"UPDATE {table} SET revoked_at = now() "
                    f"WHERE revoked_at IS NULL AND {_membership_filter}"
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )

        # Re-project what is left into Keycloak, and end the sessions.
        #
        # Authorization is read from the token — `_build_context` takes
        # `tenant_id` and `farm_scopes` off the validated claims and never
        # queries Postgres — and those claims are filled from Keycloak user
        # attributes. Revoking the rows above therefore changes nothing on its
        # own: a person removed from this tenant who still belongs to another
        # keeps the revoked farm in their attributes, and keeps working access
        # to it. A field session is issued with `offline_access` and refreshes
        # for months, so "it expires eventually" is not a bound worth having.
        #
        # Best-effort, and deliberately after the local writes: an identity
        # provider hiccup must not roll back an offboarding that the operator
        # has been told succeeded. It is logged loudly instead.
        await self._sync_scopes_and_end_sessions(user_id=user_id)

        # If the user has no other active memberships, soft-delete the
        # global user row + their Keycloak account so a long-since-departed
        # employee isn't left enabled — UNLESS they still hold an active
        # platform role, in which case the account is still a real (platform)
        # user and must survive (deleting it would dangle the platform grant
        # and the KC subject it points at).
        remaining = (
            await self._public.execute(
                text(
                    "SELECT count(*) AS c FROM public.tenant_memberships "
                    "WHERE user_id = :uid AND deleted_at IS NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).first()
        platform = (
            await self._public.execute(
                text(
                    "SELECT count(*) AS c FROM public.platform_role_assignments "
                    "WHERE user_id = :uid AND revoked_at IS NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        ).first()
        no_memberships = remaining is not None and int(remaining.c) == 0
        no_platform = platform is None or int(platform.c) == 0
        if no_memberships and no_platform:
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
            "SELECT 1 FROM public.tenant_memberships m WHERE " + " AND ".join(clauses) + " LIMIT 1"
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
            raise TenantUserNotFoundError(f"user {user_id} not a member of tenant {tenant_id}")

    async def _set_membership_status(self, *, user_id: UUID, tenant_id: UUID, status: str) -> None:
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
                text("SELECT keycloak_subject FROM public.users WHERE id = :uid").bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True))
                ),
                {"uid": user_id},
            )
        ).first()
        return row.keycloak_subject if row is not None else None


def get_tenant_users_service(
    public_session: AsyncSession,
    tenant_session: AsyncSession | None = None,
) -> TenantUsersService:
    return TenantUsersService(public_session=public_session, tenant_session=tenant_session)


# Silence unused-import warnings — kept for potential future caller use.
_KEEP_IMPORTS: tuple[Any, ...] = (
    group_name_for,
    User,
    TenantMembership,
    TenantRoleAssignment,
    datetime,
    UTC,
)
