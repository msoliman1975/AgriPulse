"""FastAPI routes for the alerts module.

Mounted under /api/v1 by the app factory. Endpoints:

  GET    /alerts                                — list alerts (filterable)
  PATCH  /alerts/{alert_id}                     — acknowledge / resolve / snooze
  GET    /rules/defaults                        — platform-curated rule catalog
  GET    /rules/overrides                       — tenant overrides
  PUT    /rules/overrides/{rule_code}           — upsert override
  POST   /blocks/{block_id}/alerts:evaluate     — admin/debug on-demand eval

RBAC:
  * Reads use ``alert.read`` and ``alert_rule.read`` (every farm-scope
    role grants these per the capability catalog).
  * Acknowledge / snooze require ``alert.acknowledge`` / ``alert.snooze``.
  * Resolve requires ``alert.resolve``.
  * Override management requires ``alert_rule.manage`` — tenant-scoped,
    not per-farm, since rules apply tenant-wide.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.errors import AlertNotFoundError
from app.modules.alerts.schemas import (
    AlertResponse,
    AlertTransitionRequest,
    DefaultRuleResponse,
    EvaluateBlockResponse,
    RuleOverrideResponse,
    RuleOverrideUpsertRequest,
    TenantRuleCreateRequest,
    TenantRuleResponse,
    TenantRuleUpdateRequest,
)
from app.modules.alerts.service import (
    AlertsServiceImpl,
    TenantRuleCodeAlreadyExistsError,
    TenantRuleCodeConflictsWithDefaultError,
    TenantRuleNotFoundError,
    get_alerts_service,
)
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
            type_="https://missionagre.io/problems/tenant-required",
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
            type_="https://missionagre.io/problems/alert-invalid-transition",
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


# ---------- Rules ---------------------------------------------------------


@router.get(
    "/rules/defaults",
    response_model=list[DefaultRuleResponse],
    summary="Platform-curated rule catalog.",
)
async def list_default_rules(
    context: RequestContext = Depends(requires_capability("alert_rule.read")),
    service: AlertsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_default_rules())


@router.get(
    "/rules/overrides",
    response_model=list[RuleOverrideResponse],
    summary="Tenant rule overrides.",
)
async def list_overrides(
    context: RequestContext = Depends(requires_capability("alert_rule.read")),
    service: AlertsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_overrides())


@router.put(
    "/rules/overrides/{rule_code}",
    response_model=RuleOverrideResponse,
    summary="Upsert a tenant rule override.",
)
async def upsert_override(
    rule_code: str,
    payload: RuleOverrideUpsertRequest,
    context: RequestContext = Depends(requires_capability("alert_rule.manage")),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.upsert_override(
        rule_code=rule_code,
        modified_conditions=payload.modified_conditions,
        modified_actions=payload.modified_actions,
        modified_severity=payload.modified_severity,
        is_disabled=payload.is_disabled,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---------- On-demand evaluation -----------------------------------------


@router.post(
    "/blocks/{block_id}/alerts:evaluate",
    response_model=EvaluateBlockResponse,
    summary="Run the alerts engine for one block (admin / debug).",
)
async def evaluate_block(
    block_id: UUID,
    context: RequestContext = Depends(requires_capability("alert_rule.manage")),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    summary = await service.evaluate_block(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {
        "block_id": str(block_id),
        "rules_evaluated": summary["rules_evaluated"],
        "rules_skipped_disabled": summary["rules_skipped_disabled"],
        "alerts_opened": summary["alerts_opened"],
    }


# ---------- Tenant rule authoring -----------------------------------------


def _tenant_rule_not_found(code: str) -> "APIError":
    from app.core.errors import APIError

    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Tenant rule not found",
        detail=f"No tenant rule with code {code!r}",
        type_="https://missionagre.io/problems/alerts/tenant-rule-not-found",
        extras={"code": code},
    )


@router.get(
    "/rules/tenant",
    response_model=list[TenantRuleResponse],
    summary="List tenant-authored alert rules.",
)
async def list_tenant_rules(
    context: RequestContext = Depends(requires_capability("alert_rule.read")),
    service: AlertsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_tenant_rules())


@router.get(
    "/rules/tenant/{code}",
    response_model=TenantRuleResponse,
    summary="Read one tenant-authored rule.",
)
async def get_tenant_rule(
    code: str,
    context: RequestContext = Depends(requires_capability("alert_rule.read")),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    out = await service.get_tenant_rule(code=code)
    if out is None:
        raise _tenant_rule_not_found(code)
    return out


@router.post(
    "/rules/tenant",
    response_model=TenantRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant-authored alert rule.",
)
async def create_tenant_rule(
    payload: TenantRuleCreateRequest,
    context: RequestContext = Depends(requires_capability("alert_rule.manage")),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    try:
        return await service.create_tenant_rule(
            code=payload.code,
            name_en=payload.name_en,
            name_ar=payload.name_ar,
            description_en=payload.description_en,
            description_ar=payload.description_ar,
            severity=payload.severity,
            applies_to_crop_categories=payload.applies_to_crop_categories,
            conditions=payload.conditions,
            actions=payload.actions,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantRuleCodeAlreadyExistsError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Tenant rule code already exists",
            detail=str(exc),
            type_="https://missionagre.io/problems/alerts/tenant-rule-code-conflict",
            extras={"code": exc.code},
        ) from exc
    except TenantRuleCodeConflictsWithDefaultError as exc:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Code collides with platform default",
            detail=str(exc),
            type_="https://missionagre.io/problems/alerts/tenant-rule-default-conflict",
            extras={"code": exc.code},
        ) from exc


@router.patch(
    "/rules/tenant/{code}",
    response_model=TenantRuleResponse,
    summary="Update a tenant-authored alert rule.",
)
async def update_tenant_rule(
    code: str,
    payload: TenantRuleUpdateRequest,
    context: RequestContext = Depends(requires_capability("alert_rule.manage")),
    service: AlertsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    updates = payload.model_dump(exclude_unset=True)
    try:
        return await service.update_tenant_rule(
            code=code,
            updates=updates,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantRuleNotFoundError as exc:
        raise _tenant_rule_not_found(code) from exc


@router.delete(
    "/rules/tenant/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Soft-delete a tenant-authored alert rule.",
)
async def delete_tenant_rule(
    code: str,
    context: RequestContext = Depends(requires_capability("alert_rule.manage")),
    service: AlertsServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    try:
        await service.delete_tenant_rule(
            code=code,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    except TenantRuleNotFoundError as exc:
        raise _tenant_rule_not_found(code) from exc
