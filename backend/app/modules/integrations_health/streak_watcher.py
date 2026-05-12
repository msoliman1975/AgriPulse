"""Consecutive-failure-streak alerter (PR-IH11).

Beat task `integrations_health.check_failure_streaks` runs every few
minutes. For each active tenant:

  1. Scan recent attempts (weather + imagery) for subscriptions that
     have N or more consecutive failures, where N comes from
     `settings.integration_failure_streak_threshold`.
  2. For each such subscription, compute the streak's anchor — the
     timestamp of its FIRST failure. This is the dedup key: while the
     streak persists the anchor doesn't move, so we fire once.
  3. Insert an inbox notification for every TenantOwner / TenantAdmin
     in that tenant.
  4. Record (subscription_id, streak_started_at) in the tenant's
     `integration_failure_alerts` dedup table so subsequent sweeps
     don't re-fire.

When the streak resets (a success arrives), the *next* failure begins
a new streak with a fresh anchor — naturally a new alert if it
crosses the threshold.

A streak that's already past the threshold when this task is added to
the cluster will get one "late" alert on the first sweep. That's the
right behavior: the operator should learn about persistent failures
even if they predate the watcher.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.notifications.repository import NotificationsRepository
from app.shared.db.ids import uuid7
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)


def _run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="integrations_health.check_failure_streaks",
    bind=False,
    ignore_result=True,
)
def check_failure_streaks() -> dict[str, Any]:
    """Beat entry point. Walks every tenant and fires fresh streak alerts."""
    return _run_async(_check_failure_streaks_async())


async def _check_failure_streaks_async() -> dict[str, Any]:
    threshold = get_settings().integration_failure_streak_threshold
    factory = AsyncSessionLocal()

    # Step 1: list active tenants.
    async with factory() as session:
        tenants = (
            await session.execute(
                text(
                    """
                    SELECT id, schema_name
                    FROM public.tenants
                    WHERE status = 'active' AND deleted_at IS NULL
                    """
                )
            )
        ).all()

    total_alerts = 0
    for t in tenants:
        try:
            schema = sanitize_tenant_schema(t.schema_name)
        except ValueError:
            continue
        try:
            sent = await _check_one_tenant(t.id, schema, threshold)
        except Exception:  # noqa: BLE001
            _log.exception("streak_watcher_tenant_failed", tenant_id=str(t.id))
            continue
        total_alerts += sent

    return {"tenants_scanned": len(tenants), "alerts_sent": total_alerts}


async def _check_one_tenant(
    tenant_id: UUID, schema: str, threshold: int
) -> int:
    """Returns the number of fresh alerts inserted for this tenant."""
    factory = AsyncSessionLocal()
    sent = 0

    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))

        # Step 2: find subscriptions whose newest attempt is the Nth+
        # consecutive failure. `failed_streak_position` on the most
        # recent row tells us how far into the streak we are; the same
        # row's `started_at` is the streak's tail. Read it directly
        # from the view so the streak-counting logic stays in one place.
        candidates = (
            await session.execute(
                text(
                    """
                    WITH ranked AS (
                        SELECT
                            attempt_id,
                            kind,
                            subscription_id,
                            block_id,
                            provider_code,
                            started_at,
                            failed_streak_position,
                            error_code,
                            ROW_NUMBER() OVER (
                                PARTITION BY kind, subscription_id
                                ORDER BY started_at DESC
                            ) AS rn
                        FROM v_integration_recent_attempts
                    )
                    SELECT *
                    FROM ranked
                    WHERE rn = 1
                      AND failed_streak_position >= :threshold
                    """
                ),
                {"threshold": threshold},
            )
        ).mappings().all()

        if not candidates:
            return 0

        # Step 3: for each candidate, look up the streak's anchor —
        # the started_at of the first failure in this streak. That's
        # the row with failed_streak_position = 1 for the same
        # (kind, subscription_id) within the current streak window.
        for c in candidates:
            anchor = (
                await session.execute(
                    text(
                        """
                        SELECT started_at
                        FROM v_integration_recent_attempts
                        WHERE kind = :k
                          AND subscription_id = :sid
                          AND failed_streak_position = 1
                          AND started_at <= :tail
                        ORDER BY started_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "k": c["kind"],
                        "sid": c["subscription_id"],
                        "tail": c["started_at"],
                    },
                )
            ).first()
            if anchor is None:
                # Should not happen — by definition position>=threshold>=1
                # implies a position=1 row exists in the same streak.
                continue
            streak_started_at = anchor.started_at

            # Step 4: try to claim the alert. If the row already exists
            # we've already fired for this streak.
            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO integration_failure_alerts (
                            id, subscription_id, kind, provider_code,
                            streak_started_at, streak_length_at_alert
                        ) VALUES (
                            :id, :sid, :kind, :pcode,
                            :anchor, :len
                        )
                        """
                    ),
                    {
                        "id": uuid7(),
                        "sid": c["subscription_id"],
                        "kind": c["kind"],
                        "pcode": c["provider_code"],
                        "anchor": streak_started_at,
                        "len": c["failed_streak_position"],
                    },
                )
            except Exception:  # noqa: BLE001  IntegrityError on uq_… constraint
                # Already alerted on this streak — skip silently.
                continue

            # Step 5: fan out to TenantOwner / TenantAdmin inboxes.
            await _fanout_inbox(
                session=session,
                tenant_id=tenant_id,
                schema=schema,
                kind=c["kind"],
                provider_code=c["provider_code"],
                block_id=c["block_id"],
                streak_length=c["failed_streak_position"],
                error_code=c["error_code"],
                streak_started_at=streak_started_at,
            )
            sent += 1

    return sent


async def _fanout_inbox(
    *,
    session: Any,
    tenant_id: UUID,
    schema: str,
    kind: str,
    provider_code: str | None,
    block_id: UUID,
    streak_length: int,
    error_code: str | None,
    streak_started_at: datetime,
) -> None:
    """Insert one inbox item per TenantOwner / TenantAdmin in this tenant.

    The session is already scoped to the tenant schema (search_path
    set above), so the public-table lookup for memberships uses the
    fully-qualified name and the `in_app_inbox` insert lands in the
    tenant schema.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT tm.user_id
                FROM public.tenant_memberships tm
                JOIN public.tenant_role_assignments tra
                  ON tra.membership_id = tm.id
                WHERE tm.tenant_id = :tid
                  AND tm.status = 'active'
                  AND tm.deleted_at IS NULL
                  AND tra.role IN ('TenantOwner', 'TenantAdmin')
                  AND tra.revoked_at IS NULL
                """
            ),
            {"tid": tenant_id},
        )
    ).all()
    if not rows:
        return

    title = (
        f"{kind.title()} integration failing"
        + (f" ({provider_code})" if provider_code else "")
    )
    body = (
        f"{streak_length} consecutive failures on this block "
        f"since {streak_started_at:%Y-%m-%d %H:%M UTC}."
        + (f" Most recent error: {error_code}." if error_code else "")
    )
    link = "/settings/integrations/health"

    # Use the existing notifications repository so the inbox row shape
    # matches everything else the bell icon reads.
    repo = NotificationsRepository(tenant_session=session, public_session=session)
    for r in rows:
        await repo.insert_inbox_item(
            item_id=uuid7(),
            user_id=r.user_id,
            alert_id=None,
            recommendation_id=None,
            severity="warning",
            title=title,
            body=body,
            link_url=link,
        )

    _log.info(
        "integration_failure_alert_sent",
        tenant_id=str(tenant_id),
        kind=kind,
        provider_code=provider_code,
        block_id=str(block_id),
        streak_length=streak_length,
        recipients=len(rows),
    )
