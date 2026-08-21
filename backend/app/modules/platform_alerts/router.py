"""Platform-admin API for `public.platform_alerts`.

Gated on `platform.manage_tenants`, the same capability the cross-tenant
health rollup uses - this is the same audience reading the same class of
cross-tenant operational state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_alerts.repository import PlatformAlertsRepository
from app.modules.platform_alerts.schemas import (
    PlatformAlertPage,
    PlatformAlertRow,
    PlatformAlertSummary,
    SweepResult,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/alerts", tags=["admin-platform-alerts"])

_CAP = "platform.manage_tenants"


@router.get("", response_model=PlatformAlertPage)
async def list_alerts(
    status_filter: str = Query(
        "live",
        alias="status",
        pattern="^(live|open|acknowledged|resolved)$",
        description=(
            "`live` (default) means open or acknowledged. An acknowledged "
            "alert is still an unfixed problem, so it stays in the working set."
        ),
    ),
    severity: str | None = Query(None, pattern="^(critical|warning)$"),
    category: str | None = Query(None, pattern="^(imagery|thermal|weather|index_calc|task)$"),
    tenant_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    del context
    items, total = await PlatformAlertsRepository(session).list_alerts(
        status=status_filter,
        severity=severity,
        category=category,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/summary", response_model=PlatformAlertSummary)
async def alert_summary(
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    """Counts only. This is polled by the banner on every page, so it stays
    a single aggregate over one index rather than a trimmed list read."""
    del context
    return await PlatformAlertsRepository(session).summary()


@router.post("/{alert_id}/acknowledge", response_model=PlatformAlertRow)
async def acknowledge_alert(
    alert_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    """Say "seen, being worked on". Keeps the alert live and keeps the red
    bar up - only resolving takes it out of the count."""
    row = await PlatformAlertsRepository(session).acknowledge(
        alert_id=alert_id, user_id=context.user_id, user_email=context.email or None
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found, or already resolved.",
        )
    await session.commit()
    return row


@router.post("/{alert_id}/resolve", response_model=PlatformAlertRow)
async def resolve_alert(
    alert_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    """Close by hand.

    The next sweep will re-open this alert under the same key if the cause
    is still there. That is deliberate: resolving is a claim that the
    problem is fixed, and the sweep is what checks the claim.
    """
    del context
    row = await PlatformAlertsRepository(session).resolve(alert_id=alert_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found, or already resolved.",
        )
    await session.commit()
    return row


@router.post("/sweep", response_model=SweepResult)
async def run_sweep_now(
    context: RequestContext = Depends(requires_capability(_CAP)),
) -> dict[str, Any]:
    """Force a sweep in-process and return its counts.

    Runs inline rather than via `.delay()` so the caller sees the result.
    The sweep is read-mostly and linear in tenant count; if that stops
    being true this should become an enqueue plus a poll.
    """
    del context
    from app.modules.platform_alerts.tasks import run_sweep

    return await run_sweep()
