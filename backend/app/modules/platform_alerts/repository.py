"""Data access for `public.platform_alerts`.

Every write goes through `upsert` so a detector can be re-run as often as
the sweep likes without multiplying rows: the partial unique index on
`alert_key` turns a repeat detection into an UPDATE that bumps
`last_seen_at` and `occurrences`.

The session handed in here is a **public** session. Nothing in this module
sets a tenant search_path; `tenant_id` is carried as a plain column so one
query can read across every tenant at once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

# Columns every read returns, so the list page and the summary agree on shape.
_COLS = """
    id, alert_key, category, kind, severity, status,
    tenant_id, tenant_slug, tenant_name, farm_id, farm_name,
    title, detail, context,
    first_seen_at, last_seen_at, occurrences,
    acknowledged_at, acknowledged_by, acknowledged_by_email,
    resolved_at, resolved_reason
"""


class PlatformAlertsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        alert_key: str,
        category: str,
        kind: str,
        severity: str,
        title: str,
        detail: str | None,
        context: dict[str, Any],
        tenant_id: UUID | None = None,
        tenant_slug: str | None = None,
        tenant_name: str | None = None,
        farm_id: UUID | None = None,
        farm_name: str | None = None,
    ) -> None:
        """Open the alert, or refresh it if it is already live.

        The conflict target repeats the index predicate (``WHERE status <>
        'resolved'``) because the unique index is partial - without it
        Postgres cannot match the arbiter and raises.

        On conflict the row is updated in place, including ``severity``. That
        is what lets an alert escalate from warning to critical without
        opening a second card for the same problem. ``first_seen_at`` is left
        alone so the page can show how long this has actually been going on,
        and ``status`` is left alone so a re-detection does not silently
        un-acknowledge something an operator has already seen.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO public.platform_alerts (
                    alert_key, category, kind, severity,
                    tenant_id, tenant_slug, tenant_name, farm_id, farm_name,
                    title, detail, context
                ) VALUES (
                    :alert_key, :category, :kind, :severity,
                    :tenant_id, :tenant_slug, :tenant_name, :farm_id, :farm_name,
                    :title, :detail, :context
                )
                ON CONFLICT (alert_key) WHERE status <> 'resolved'
                DO UPDATE SET
                    severity      = EXCLUDED.severity,
                    title         = EXCLUDED.title,
                    detail        = EXCLUDED.detail,
                    context       = EXCLUDED.context,
                    tenant_slug   = EXCLUDED.tenant_slug,
                    tenant_name   = EXCLUDED.tenant_name,
                    farm_name     = EXCLUDED.farm_name,
                    last_seen_at  = now(),
                    occurrences   = public.platform_alerts.occurrences + 1
                """
            ).bindparams(
                bindparam("tenant_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                bindparam("context", type_=JSONB),
            ),
            {
                "alert_key": alert_key,
                "category": category,
                "kind": kind,
                "severity": severity,
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "tenant_name": tenant_name,
                "farm_id": farm_id,
                "farm_name": farm_name,
                "title": title,
                "detail": detail,
                "context": context,
            },
        )

    async def auto_resolve_absent(self, *, kinds: list[str], seen_keys: list[str]) -> int:
        """Close live alerts of these kinds that this sweep did not re-detect.

        Only kinds the sweep actually recomputes from scratch may be passed
        here. ``task_error`` must not be: it is written by a Celery signal,
        not by the sweep, so "the sweep did not see it" is no evidence that
        it stopped - ``auto_resolve_quiet`` handles that one on a timer.

        ``seen_keys`` binds as a real ``text[]`` rather than an IN-list so a
        sweep that finds several hundred problems still sends one parameter.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE public.platform_alerts
                   SET status = 'resolved',
                       resolved_at = now(),
                       resolved_reason = 'auto'
                 WHERE status <> 'resolved'
                   AND kind = ANY(:kinds)
                   AND NOT (alert_key = ANY(:seen_keys))
                """
            ).bindparams(
                bindparam("kinds", type_=ARRAY(Text())),
                bindparam("seen_keys", type_=ARRAY(Text())),
            ),
            {"kinds": kinds, "seen_keys": seen_keys},
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def auto_resolve_quiet(self, *, kind: str, quiet_hours: int) -> int:
        """Close alerts of a signal-written kind that have gone quiet.

        Used for ``task_error``, whose only recovery signal is the absence of
        another failure.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE public.platform_alerts
                   SET status = 'resolved',
                       resolved_at = now(),
                       resolved_reason = 'auto'
                 WHERE status <> 'resolved'
                   AND kind = :kind
                   AND last_seen_at < now() - make_interval(hours => :quiet_hours)
                """
            ),
            {"kind": kind, "quiet_hours": quiet_hours},
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def auto_resolve_missing_tenants(self) -> int:
        """Close alerts naming a tenant that is no longer active.

        This is what stands in for a foreign key. A purge drops the tenant
        schema; without this the alerts it raised would stay live forever
        with nothing left to fix.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE public.platform_alerts
                   SET status = 'resolved',
                       resolved_at = now(),
                       resolved_reason = 'auto'
                 WHERE status <> 'resolved'
                   AND tenant_id IS NOT NULL
                   AND NOT EXISTS (
                        SELECT 1 FROM public.tenants t
                         WHERE t.id = public.platform_alerts.tenant_id
                           AND t.status = 'active'
                           AND t.deleted_at IS NULL
                   )
                """
            )
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def list_alerts(
        self,
        *,
        status: str | None,
        severity: str | None,
        category: str | None,
        tenant_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered page of alerts plus the unpaginated total.

        ``status='live'`` is the page default and means open **or**
        acknowledged - an acknowledged alert is still a broken thing, it has
        just been seen. Only ``resolved`` leaves the working set.
        """
        where = ["TRUE"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status == "live":
            where.append("status <> 'resolved'")
        elif status:
            where.append("status = :status")
            params["status"] = status
        if severity:
            where.append("severity = :severity")
            params["severity"] = severity
        if category:
            where.append("category = :category")
            params["category"] = category
        if tenant_id is not None:
            where.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        clause = " AND ".join(where)

        total = (
            await self._session.execute(
                text(f"SELECT count(*) FROM public.platform_alerts WHERE {clause}"),  # noqa: S608
                params,
            )
        ).scalar_one()

        # Worst first, then unseen before acknowledged, then freshest. The
        # severity ordering is written as an explicit boolean rather than
        # ORDER BY severity: 'critical' happens to sort before 'warning'
        # alphabetically, and relying on that would reverse silently the day
        # a severity is renamed.
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT {_COLS}
                          FROM public.platform_alerts
                         WHERE {clause}
                         ORDER BY (severity = 'critical') DESC,
                                  (status = 'open') DESC,
                                  last_seen_at DESC
                         LIMIT :limit OFFSET :offset
                        """  # noqa: S608
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows], int(total)

    async def summary(self) -> dict[str, Any]:
        """Counts for the red bar. One row, cheap enough to poll."""
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                          count(*) FILTER (
                            WHERE status <> 'resolved' AND severity = 'critical'
                          ) AS critical,
                          count(*) FILTER (
                            WHERE status <> 'resolved' AND severity = 'warning'
                          ) AS warning,
                          count(*) FILTER (WHERE status = 'open')         AS open,
                          count(*) FILTER (WHERE status = 'acknowledged') AS acknowledged,
                          max(last_seen_at) FILTER (
                            WHERE status <> 'resolved'
                          ) AS newest_at
                        FROM public.platform_alerts
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        return dict(row)

    async def acknowledge(
        self, *, alert_id: UUID, user_id: UUID | None, user_email: str | None
    ) -> dict[str, Any] | None:
        """Mark one live alert acknowledged.

        COALESCE on every acknowledgement column keeps the first operator's
        name on the row: re-acking is a no-op rather than a rewrite.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        f"""
                        UPDATE public.platform_alerts
                           SET status = 'acknowledged',
                               acknowledged_at = COALESCE(acknowledged_at, now()),
                               acknowledged_by = COALESCE(acknowledged_by, :user_id),
                               acknowledged_by_email =
                                   COALESCE(acknowledged_by_email, :user_email)
                         WHERE id = :alert_id
                           AND status <> 'resolved'
                        RETURNING {_COLS}
                        """  # noqa: S608
                    ).bindparams(
                        bindparam("user_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("alert_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"alert_id": alert_id, "user_id": user_id, "user_email": user_email},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def resolve(self, *, alert_id: UUID) -> dict[str, Any] | None:
        """Close one alert by hand.

        Recorded as ``manual`` so the list can distinguish "an operator said
        this is fine" from "the sweep stopped seeing it", which are very
        different claims about whether anything was actually fixed.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        f"""
                        UPDATE public.platform_alerts
                           SET status = 'resolved',
                               resolved_at = now(),
                               resolved_reason = 'manual'
                         WHERE id = :alert_id
                           AND status <> 'resolved'
                        RETURNING {_COLS}
                        """  # noqa: S608
                    ).bindparams(bindparam("alert_id", type_=PG_UUID(as_uuid=True))),
                    {"alert_id": alert_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def newest_seen_at(self) -> datetime | None:
        return (
            await self._session.execute(
                text("SELECT max(last_seen_at) FROM public.platform_alerts")
            )
        ).scalar_one_or_none()
