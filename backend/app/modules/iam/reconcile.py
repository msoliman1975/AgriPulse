"""IH-6: DB -> Keycloak reconciler.

The DB (`public.users` + `tenant_memberships` + `tenant_role_assignments`
+ `platform_role_assignments`) is the source of truth for who may sign
in and with what tenant context. Keycloak carries the same facts as the
user's `enabled` flag and `tenant_id` / `tenant_role` attributes, which
project into the JWT. Those can drift: a role flipped directly in the DB,
a membership suspended outside the KC-aware path, or a soft-deleted user
whose login was never disabled (gap G11).

This module is the periodic backstop (Beat task `iam.reconcile_keycloak`)
that walks every provisioned user, computes the desired Keycloak state
from the DB, and pushes corrections:

  * enabled flag   — on when the user is active and has at least one
                     active membership or platform role; off otherwise.
  * tenant attrs   — the canonical (most-recent active) membership's
                     tenant_id + role, for users that have one.

Corrections are audited (archive scope) and counted. Idempotent: a
already-consistent user is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.keycloak import (
    KeycloakAdminClient,
    KeycloakError,
    get_keycloak_client,
)

_AUDIT_EVENT_TYPE = "iam.keycloak_reconciled"


@dataclass(frozen=True)
class DesiredUserState:
    """What Keycloak *should* say about a user, derived from the DB."""

    user_id: UUID
    keycloak_subject: str
    enabled: bool
    # Set only when the user has a canonical active membership; left None
    # for platform-only users (we don't touch their tenant attrs).
    tenant_id: str | None
    tenant_role: str | None


async def reconcile_users(
    desired: list[DesiredUserState],
    kc: KeycloakAdminClient,
    *,
    audit: AuditService | None = None,
) -> dict[str, int]:
    """Apply the desired state to Keycloak. Returns a count summary
    ``{"checked": N, "corrected": M, "skipped": K}``."""
    audit = audit or get_audit_service()
    log = get_logger(__name__)
    checked = corrected = skipped = 0

    for d in desired:
        if d.keycloak_subject.startswith("pending::"):
            skipped += 1
            continue
        try:
            state = await kc.get_user_state(keycloak_user_id=d.keycloak_subject)
        except KeycloakError as exc:
            skipped += 1
            log.warning("reconcile_get_state_failed", user_id=str(d.user_id), error=str(exc))
            continue
        if state is None:
            skipped += 1
            continue

        checked += 1
        changes: list[str] = []
        try:
            if state.enabled != d.enabled:
                if d.enabled:
                    await kc.enable_user(keycloak_user_id=d.keycloak_subject)
                else:
                    await kc.disable_user(keycloak_user_id=d.keycloak_subject)
                changes.append("enabled" if d.enabled else "disabled")

            if (
                d.enabled
                and d.tenant_id is not None
                and d.tenant_role is not None
                and (state.tenant_id != d.tenant_id or state.tenant_role != d.tenant_role)
            ):
                await kc.set_tenant_attributes(
                    keycloak_user_id=d.keycloak_subject,
                    tenant_id=d.tenant_id,
                    tenant_role=d.tenant_role,
                )
                changes.append("tenant_attrs")
        except KeycloakError as exc:
            log.warning("reconcile_apply_failed", user_id=str(d.user_id), error=str(exc))
            continue

        if changes:
            corrected += 1
            await audit.record_archive(
                event_type=_AUDIT_EVENT_TYPE,
                actor_user_id=None,
                actor_kind="system",
                subject_kind="user",
                subject_id=d.user_id,
                details={
                    "changes": changes,
                    "tenant_id": d.tenant_id,
                    "tenant_role": d.tenant_role,
                    "enabled": d.enabled,
                },
            )

    summary = {"checked": checked, "corrected": corrected, "skipped": skipped}
    log.info("reconcile_keycloak.completed", **summary)
    return summary


async def run_keycloak_reconcile(
    *,
    kc: KeycloakAdminClient | None = None,
    audit: AuditService | None = None,
) -> dict[str, int]:
    """Load desired states from the DB and reconcile once."""
    kc = kc or get_keycloak_client()
    factory = AsyncSessionLocal()
    async with factory() as session:
        desired = await _load_desired_states(session)
    return await reconcile_users(desired, kc, audit=audit)


async def _load_desired_states(session: AsyncSession) -> list[DesiredUserState]:
    """Every provisioned user + their canonical active membership/role and
    whether they hold any active platform role."""
    stmt = text(
        """
        SELECT
            u.id AS user_id,
            u.keycloak_subject AS keycloak_subject,
            (u.deleted_at IS NULL AND u.status <> 'archived') AS user_active,
            m.tenant_id AS tenant_id,
            m.role AS tenant_role,
            (p.user_id IS NOT NULL) AS has_platform
        FROM public.users u
        LEFT JOIN LATERAL (
            SELECT mm.tenant_id,
                   (SELECT tra.role
                      FROM public.tenant_role_assignments tra
                     WHERE tra.membership_id = mm.id
                       AND tra.revoked_at IS NULL
                     ORDER BY tra.granted_at DESC
                     LIMIT 1) AS role
            FROM public.tenant_memberships mm
            WHERE mm.user_id = u.id
              AND mm.deleted_at IS NULL
              AND mm.status = 'active'
            ORDER BY mm.joined_at DESC NULLS LAST
            LIMIT 1
        ) m ON true
        LEFT JOIN LATERAL (
            SELECT pra.user_id
            FROM public.platform_role_assignments pra
            WHERE pra.user_id = u.id
              AND pra.revoked_at IS NULL
            LIMIT 1
        ) p ON true
        WHERE u.keycloak_subject IS NOT NULL
          AND u.keycloak_subject NOT LIKE 'pending::%'
        """
    )
    rows = (await session.execute(stmt)).all()
    desired: list[DesiredUserState] = []
    for r in rows:
        has_membership = r.tenant_id is not None
        enabled = bool(r.user_active) and (has_membership or bool(r.has_platform))
        # Only carry tenant attrs when the user is enabled, has a
        # membership, and that membership resolves to a concrete role.
        set_attrs = enabled and has_membership and r.tenant_role is not None
        desired.append(
            DesiredUserState(
                user_id=r.user_id,
                keycloak_subject=r.keycloak_subject,
                enabled=enabled,
                tenant_id=str(r.tenant_id) if set_attrs else None,
                tenant_role=r.tenant_role if set_attrs else None,
            )
        )
    return desired
