"""Farm-config subscription template endpoints (PR-2).

Mounted under /api/v1 by the app factory. Endpoints:

  GET  /api/v1/farms/{farm_id}/config/subscriptions/template
  PUT  /api/v1/farms/{farm_id}/config/subscriptions/template
  POST /api/v1/farms/{farm_id}/config/subscriptions/apply-preview
  POST /api/v1/farms/{farm_id}/config/subscriptions/apply

All four require ``farm.manage_config`` (granted to FarmManager +
TenantAdmin + TenantOwner — see PR-1). The router is gated behind
``settings.farm_config_template_enabled``; when OFF every route returns
404 so a half-rolled-out tenant doesn't get a half-working UI.

Note: deliberately NO ``from __future__ import annotations``.
FastAPI/Pydantic v2's TypeAdapter cannot resolve string annotations
like ``request: Request`` and silently demotes them to required query
parameters, breaking POST validation.
"""

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.farms import config_template
from app.modules.farms.config_schemas import (
    ApplyPreviewRequest,
    ApplyPreviewResponse,
    ApplyResponse,
    IrrigationTemplateSchema,
    LockStateResponse,
    LockToggleRequest,
    OrgTemplateSchema,
    SimpleApplyPreviewResponse,
    SimpleApplyResponse,
    SubscriptionsTemplateReplaceRequest,
    SubscriptionsTemplateResponse,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["farms.config"])


def _ensure_feature_enabled() -> None:
    if not get_settings().farm_config_template_enabled:
        # 404 (not 403) so the route appears not-mounted to a tenant
        # whose flag is off — keeps the UI's "menu vs available" story
        # cleaner.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# ---------- GET template -----------------------------------------------------


@router.get(
    "/farms/{farm_id}/config/subscriptions/template",
    response_model=SubscriptionsTemplateResponse,
    summary="Get the farm subscription template (imagery + weather).",
)
async def get_subscriptions_template(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    imagery = await config_template.get_imagery_template(session, farm_id)
    weather = await config_template.get_weather_template(session, farm_id)
    return {
        "imagery": [
            {
                "product_id": r.product_id,
                "cadence_hours": r.cadence_hours,
                "cloud_cover_max_pct": r.cloud_cover_max_pct,
                "is_active": r.is_active,
            }
            for r in imagery
        ],
        "weather": [
            {
                "provider_code": r.provider_code,
                "cadence_hours": r.cadence_hours,
                "is_active": r.is_active,
            }
            for r in weather
        ],
    }


# ---------- PUT template (atomic replace) -----------------------------------


@router.put(
    "/farms/{farm_id}/config/subscriptions/template",
    response_model=SubscriptionsTemplateResponse,
    summary="Replace the farm subscription template (imagery + weather).",
)
async def replace_subscriptions_template(
    farm_id: UUID,
    payload: SubscriptionsTemplateReplaceRequest,
    request: Request,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    try:
        await config_template.replace_imagery_template(
            session,
            farm_id=farm_id,
            rows=[
                config_template.ImageryTemplateRow(
                    product_id=r.product_id,
                    cadence_hours=r.cadence_hours,
                    cloud_cover_max_pct=r.cloud_cover_max_pct,
                    is_active=r.is_active,
                )
                for r in payload.imagery
            ],
            updated_by=context.user_id,
        )
        await config_template.replace_weather_template(
            session,
            farm_id=farm_id,
            rows=[
                config_template.WeatherTemplateRow(
                    provider_code=r.provider_code,
                    cadence_hours=r.cadence_hours,
                    is_active=r.is_active,
                )
                for r in payload.weather
            ],
            updated_by=context.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await get_subscriptions_template(farm_id, context=context, session=session)


# ---------- Apply preview ---------------------------------------------------


@router.post(
    "/farms/{farm_id}/config/subscriptions/apply-preview",
    response_model=ApplyPreviewResponse,
    summary="Preview what Apply would change for each target block.",
)
async def apply_subscriptions_preview(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    diff = await config_template.compute_apply_diff(
        session, farm_id=farm_id, target_block_ids=target
    )
    return {
        "imagery": [_diff_to_wire(d) for d in diff.imagery],
        "weather": [_diff_to_wire(d) for d in diff.weather],
        "total_blocks": diff.total_blocks,
        "matched_blocks": diff.matched_blocks,
    }


# ---------- Apply -----------------------------------------------------------


@router.post(
    "/farms/{farm_id}/config/subscriptions/apply",
    response_model=ApplyResponse,
    summary="Reconcile target blocks to the farm subscription template.",
)
async def apply_subscriptions(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    request: Request,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    counts = await config_template.apply_template(
        session,
        farm_id=farm_id,
        target_block_ids=target,
        updated_by=context.user_id,
    )
    return {
        "blocks_touched": counts.blocks_touched,
        "imagery_added": counts.imagery_added,
        "imagery_updated": counts.imagery_updated,
        "imagery_deactivated": counts.imagery_deactivated,
        "weather_added": counts.weather_added,
        "weather_updated": counts.weather_updated,
        "weather_deactivated": counts.weather_deactivated,
    }


# ---------- Helpers ---------------------------------------------------------


def _diff_to_wire(d: config_template.BlockDiff) -> dict[str, Any]:
    return {
        "block_id": d.block_id,
        "will_add": list(d.will_add),
        "will_update": list(d.will_update),
        "will_deactivate": list(d.will_deactivate),
        "matches": d.matches,
    }


def _require_tenant(context: RequestContext) -> None:
    if context.tenant_schema is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a tenant-scoped JWT.",
        )


# ---------- PR-3: Lock state -----------------------------------------------


@router.get(
    "/farms/{farm_id}/config/locks",
    response_model=LockStateResponse,
    summary="Return the three per-category lock booleans.",
)
async def get_locks(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    return cast(
        "dict[str, Any]",
        await config_template.get_lock_state(session, farm_id=farm_id),
    )


@router.post(
    "/farms/{farm_id}/config/{category}/lock",
    summary="Lock a Shared category (subscriptions | irrigation | org).",
)
async def lock_category(
    farm_id: UUID,
    category: str,
    payload: LockToggleRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    _validate_category(category)
    result = await config_template.lock_category(
        session,
        farm_id=farm_id,
        category=category,  # type: ignore[arg-type]
        force_overwrite=payload.force_overwrite,
        updated_by=context.user_id,
    )
    return result


@router.post(
    "/farms/{farm_id}/config/{category}/unlock",
    summary="Unlock a Shared category.",
)
async def unlock_category(
    farm_id: UUID,
    category: str,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    _validate_category(category)
    await config_template.unlock_category(
        session,
        farm_id=farm_id,
        category=category,  # type: ignore[arg-type]
        updated_by=context.user_id,
    )
    return {"locked": False}


# ---------- PR-3: Irrigation template --------------------------------------


@router.get(
    "/farms/{farm_id}/config/irrigation/template",
    response_model=IrrigationTemplateSchema,
    summary="Get the farm irrigation defaults template.",
)
async def get_irrigation_template(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    tpl = await config_template.get_irrigation_template(session, farm_id=farm_id)
    return tpl.as_dict()


@router.put(
    "/farms/{farm_id}/config/irrigation/template",
    response_model=IrrigationTemplateSchema,
    summary="Replace the farm irrigation defaults template.",
)
async def put_irrigation_template(
    farm_id: UUID,
    payload: IrrigationTemplateSchema,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    tpl = config_template.IrrigationTemplate(
        irrigation_system=payload.irrigation_system,
        irrigation_source=payload.irrigation_source,
        flow_rate_m3_per_hour=(
            Decimal(str(payload.flow_rate_m3_per_hour))
            if payload.flow_rate_m3_per_hour is not None
            else None
        ),
    )
    await config_template.replace_irrigation_template(
        session, farm_id=farm_id, tpl=tpl, updated_by=context.user_id
    )
    return tpl.as_dict()


@router.post(
    "/farms/{farm_id}/config/irrigation/apply-preview",
    response_model=SimpleApplyPreviewResponse,
    summary="Preview what irrigation Apply would change.",
)
async def apply_irrigation_preview(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    diffs = await config_template.compute_irrigation_apply_diff(
        session, farm_id=farm_id, target_block_ids=target
    )
    return {
        "blocks": [
            {
                "block_id": str(d.block_id),
                "before": d.before,
                "after": d.after,
                "matches": d.matches,
            }
            for d in diffs
        ],
        "total_blocks": len(diffs),
        "matched_blocks": sum(1 for d in diffs if d.matches),
    }


@router.post(
    "/farms/{farm_id}/config/irrigation/apply",
    response_model=SimpleApplyResponse,
    summary="Apply the irrigation template to the target blocks.",
)
async def apply_irrigation(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    return await config_template.apply_irrigation_template(
        session, farm_id=farm_id, target_block_ids=target, updated_by=context.user_id
    )


# ---------- PR-3: Org template (additive tags merge) -----------------------


@router.get(
    "/farms/{farm_id}/config/org/template",
    response_model=OrgTemplateSchema,
    summary="Get the farm org template (default_tags).",
)
async def get_org_template(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    tpl = await config_template.get_org_template(session, farm_id=farm_id)
    return {"default_tags": list(tpl.default_tags)}


@router.put(
    "/farms/{farm_id}/config/org/template",
    response_model=OrgTemplateSchema,
    summary="Replace the farm org template (default_tags).",
)
async def put_org_template(
    farm_id: UUID,
    payload: OrgTemplateSchema,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    tpl = config_template.OrgTemplate(default_tags=tuple(payload.default_tags))
    await config_template.replace_org_template(
        session, farm_id=farm_id, tpl=tpl, updated_by=context.user_id
    )
    return {"default_tags": list(tpl.default_tags)}


@router.post(
    "/farms/{farm_id}/config/org/apply-preview",
    response_model=SimpleApplyPreviewResponse,
    summary="Preview what an org Apply would change (additive tag merge).",
)
async def apply_org_preview(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    diffs = await config_template.compute_org_apply_diff(
        session, farm_id=farm_id, target_block_ids=target
    )
    return {
        "blocks": [
            {
                "block_id": str(d.block_id),
                "before": d.before,
                "after": d.after,
                "matches": d.matches,
            }
            for d in diffs
        ],
        "total_blocks": len(diffs),
        "matched_blocks": sum(1 for d in diffs if d.matches),
    }


@router.post(
    "/farms/{farm_id}/config/org/apply",
    response_model=SimpleApplyResponse,
    summary="Apply the org template (additive — never removes block-local tags).",
)
async def apply_org(
    farm_id: UUID,
    payload: ApplyPreviewRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_feature_enabled()
    _require_tenant(context)
    target = tuple(payload.block_ids) if payload.block_ids is not None else None
    return await config_template.apply_org_template(
        session, farm_id=farm_id, target_block_ids=target, updated_by=context.user_id
    )


# ---------- Helpers --------------------------------------------------------


def _validate_category(category: str) -> None:
    if category not in ("subscriptions", "irrigation", "org"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown category {category!r}",
        )
