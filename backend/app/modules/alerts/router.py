"""FastAPI routes for the alerts module — alert lifecycle only.

Stage 2 of the rules sunset removed every `/rules/*` and
`/blocks/{block_id}/alerts:evaluate` endpoint. Trees own rule
authoring + alert generation now (PR-E + PR-F). The remaining routes
cover the alert lifecycle that both legacy and tree-sourced alerts
share.

Mounted under /api/v1 by the app factory. Endpoints:

  GET    /alerts                — list alerts (filterable)
  PATCH  /alerts/{alert_id}     — acknowledge / resolve / snooze

RBAC:
  * Reads use ``alert.read`` (every farm-scope role grants this).
  * Acknowledge / snooze require ``alert.acknowledge`` / ``alert.snooze``.
  * Resolve requires ``alert.resolve``.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.errors import AlertNotFoundError
from app.modules.alerts.schemas import AlertResponse, AlertTransitionRequest
from app.modules.alerts.service import AlertsServiceImpl, get_alerts_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["alerts"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> AlertsServiceImpl:
    return get_alerts_service(tenant_session=tenant_session, public_session=public_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


# ---------- Alerts ---------------------------------------------------------


@router.get(
    "/alerts",
    response_model=list[AlertResponse],
    summary="List alerts in the current tenant.",
)
async def list_alerts(
    block_id: UUID | None = Query(default=None),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    severity: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("alert.read")),
    service: AlertsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list_alerts(
        block_id=block_id,
        status_filter=tuple(status_filter or ()),
        severity_filter=tuple(severity or ()),
        limit=limit,
    )
    return list(rows)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    summary="Acknowledge / resolve / snooze an alert.",
)
async def transition_alert(
    alert_id: UUID,
    payload: AlertTransitionRequest,
    context: RequestContext = Depends(get_current_context),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)

    chosen = sum(
        1 for v in (payload.acknowledge, payload.resolve, payload.snooze_until is not None) if v
    )
    if chosen != 1:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid transition payload",
            detail="Exactly one of `acknowledge`, `resolve`, `snooze_until` must be set.",
            type_="https://agripulse.cloud/problems/alert-invalid-transition",
        )
    if payload.acknowledge:
        action = "acknowledge"
        cap = "alert.acknowledge"
    elif payload.resolve:
        action = "resolve"
        cap = "alert.resolve"
    else:
        action = "snooze"
        cap = "alert.snooze"

    if not has_capability(context, cap):
        # No farm scope here — alerts list is tenant-wide; the caller
        # already has alert.read because they got the alert id.
        raise AlertNotFoundError(alert_id)

    return await service.transition_alert(
        alert_id=alert_id,
        action=action,
        snooze_until=payload.snooze_until,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
