"""TenantAdmin / TenantOwner grant guardrails.

When a `role.assign_tenant` write lands with a high-trust role
(TenantAdmin or TenantOwner), we want a paper trail and an in-app
heads-up to the existing TenantAdmins so the action isn't silent.

Locked decision Q3 from the proposal: TenantAdmin can grant
TenantAdmin (convenience > self-defense) but every grant is
logged + notified. PlatformAdmin can always revoke.

Two outputs per grant:

  1. `platform.tenant_admin_role_granted` event in
     `audit_events_archive` with severity=warning.
  2. In-app inbox row for every OTHER TenantAdmin / TenantOwner of
     the tenant (skip the actor and the new grantee).

Both are best-effort: a notification failure shouldn't roll back
the role grant. The audit row is the source of truth for "did we
warn?"; missing inbox rows are diagnosable from the audit details.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service

GuardedRole = Literal["TenantAdmin", "TenantOwner"]
_log = get_logger(__name__)


def is_guarded_role(role: str) -> bool:
    return role in ("TenantAdmin", "TenantOwner")


async def _peer_admin_user_ids(
    *,
    public_session: AsyncSession,
    tenant_id: UUID,
    exclude: tuple[UUID, ...],
) -> list[UUID]:
    """Active TenantAdmin / TenantOwner users on the tenant, excluding
    the listed user ids (typically the actor + the grantee)."""
    rows = (
        await public_session.execute(
            text(
                """
                SELECT DISTINCT m.user_id
                FROM public.tenant_memberships m
                JOIN public.tenant_role_assignments tra
                  ON tra.membership_id = m.id
                 AND tra.revoked_at IS NULL
                WHERE m.tenant_id = :tid
                  AND m.deleted_at IS NULL
                  AND tra.role IN ('TenantAdmin','TenantOwner')
                """
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tenant_id},
        )
    ).all()
    excluded = set(exclude)
    return [r.user_id for r in rows if r.user_id not in excluded]


async def _insert_inbox_row(
    *,
    tenant_session: AsyncSession,
    user_id: UUID,
    title: str,
    body: str,
    link_url: str | None,
) -> None:
    """Direct insert into `in_app_inbox` — bypasses the notifications
    service because it pulls from a template + dispatch row, and this
    is a free-form one-shot. Same shape as alerts/recommendations
    inbox rows so the bell renderer treats it identically."""
    await tenant_session.execute(
        text(
            """
            INSERT INTO in_app_inbox (
                id, user_id, alert_id, recommendation_id,
                severity, title, body, link_url, created_at, updated_at
            ) VALUES (
                :id, :uid, NULL, NULL,
                'warning', :title, :body, :link, now(), now()
            )
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "uid": user_id,
            "title": title,
            "body": body,
            "link": link_url,
        },
    )


async def emit_role_grant_guardrail(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession | None,
    tenant_id: UUID,
    target_user_id: UUID,
    target_email: str | None,
    role: GuardedRole,
    actor_user_id: UUID | None,
    audit: AuditService | None = None,
) -> None:
    """Fire the warning audit + notify peer admins. Safe to call any
    number of times per grant; the audit subject_id is the membership
    so duplicate calls are visible (and harmless) in the log."""
    audit_svc = audit or get_audit_service()

    # Audit first — this is the durable record. Notification failures
    # below shouldn't unwind it.
    await audit_svc.record_archive(
        event_type="platform.tenant_admin_role_granted",
        actor_user_id=actor_user_id,
        subject_kind="user",
        subject_id=target_user_id,
        details={
            "tenant_id": str(tenant_id),
            "role": role,
            "target_email": target_email,
            "severity": "warning",
        },
    )

    # Notification fan-out — best-effort and skipped if the caller
    # didn't pass a tenant session (e.g. platform-side flows that
    # only have a public session in scope). The audit row above is
    # the source of truth for "did we warn?".
    if tenant_session is None:
        _log.info(
            "guardrail_inbox_skipped_no_tenant_session",
            tenant_id=str(tenant_id),
            role=role,
        )
        return

    # Skip the actor (they did the action) and the grantee (they
    # already know).
    excludes: tuple[UUID, ...] = (target_user_id,)
    if actor_user_id is not None:
        excludes = (target_user_id, actor_user_id)
    try:
        peers = await _peer_admin_user_ids(
            public_session=public_session,
            tenant_id=tenant_id,
            exclude=excludes,
        )
    except Exception as exc:
        _log.warning("guardrail_peer_lookup_failed", error=str(exc))
        return

    title = f"{role} role granted"
    body_email = target_email or str(target_user_id)
    body = (
        f"A new {role} was added to this tenant: {body_email}. "
        f"Revoke from /admin if this was unexpected."
    )
    for user_id in peers:
        try:
            await _insert_inbox_row(
                tenant_session=tenant_session,
                user_id=user_id,
                title=title,
                body=body,
                link_url=None,
            )
        except Exception as exc:
            _log.warning(
                "guardrail_inbox_insert_failed",
                user_id=str(user_id),
                error=str(exc),
            )
            # Continue with the next peer; one user's failure
            # doesn't block the others.
            continue
