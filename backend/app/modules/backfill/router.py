"""Backfill console API — PlatformAdmin only.

Mounted at /api/v1/admin/backfill. Every endpoint is gated on
`platform.run_backfill`, which only platform roles can hold: backfill
spends a shared CDSE processing-unit allowance, so until per-tenant quota
accounting exists one tenant must not be able to exhaust it for everyone.

  GET  /tenants                        — tenant picker
  GET  /tenants/{tenant_id}/farms      — farm picker (flags occupied farms)
  POST /tenants/{tenant_id}:estimate   — pre-flight scale, no side effects
  POST /tenants/{tenant_id}/runs       — start a run (409 if farm is busy)
  GET  /runs                           — cross-tenant run list
  GET  /runs/{run_id}                  — one run with per-source progress
  POST /runs/{run_id}:cancel           — release a stuck run (frees the farm)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backfill.service import (
    BackfillConflictError,
    BackfillService,
    FarmNotFoundError,
    NoIntegrationConfigError,
    get_backfill_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/backfill", tags=["admin-backfill"])

_CAP = "platform.run_backfill"


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> BackfillService:
    return get_backfill_service(session)


# --- schemas ---------------------------------------------------------------


class TenantOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    schema_name: str


class FarmOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str | None
    code: str | None
    block_count: int
    # Non-null when a run already holds this farm, so the UI can disable the
    # option instead of letting the admin fill in a form that will 409.
    active_run_id: UUID | None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    farm_id: UUID
    window_from: date
    window_to: date
    imagery: bool = False
    weather: bool = False
    # Its own source, not part of `imagery`: different satellite, cadence,
    # cost and failure modes, so a thermal failure must not hide inside the
    # imagery counter.
    thermal: bool = False
    kind: Literal["backfill", "indices"] = "backfill"

    @model_validator(mode="after")
    def _check(self) -> RunRequest:
        if not (self.imagery or self.weather or self.thermal):
            raise ValueError("pick at least one source")
        if self.window_to < self.window_from:
            raise ValueError("window_to must be on or after window_from")
        return self


class EstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    farm_id: UUID
    window_from: date
    window_to: date
    imagery: bool = True
    weather: bool = True
    thermal: bool = True


class EstimateResponse(BaseModel):
    days: int
    blocks: int
    # Provider fetches the run will dispatch, in whatever shape: block AOIs,
    # plus one per whole-farm subscription on a farm that has cut over.
    subscriptions: int
    # How many of those are whole-farm fetches. Non-zero changes what the run
    # does, not just its size, so the console reports it separately.
    farm_aoi_subscriptions: int
    estimated_scenes: int
    estimated_units: int
    # False would mean "this is a real quota reading". It never is today —
    # CDSE consumption is not metered anywhere in the app — so the UI must
    # present the number as an approximation.
    units_estimated: bool
    weather_hours: int
    # Lets the console warn before submitting that a source has nothing
    # configured to fetch from. One weather fetch per provider the farm
    # resolves to, so this is the length of `weather_providers`.
    weather_subscriptions: int
    weather_providers: list[str]
    # Thermal, counted on its own cadence. Landsat 8+9 nominal revisit is
    # 8 days against Sentinel-2's 5, and Planetary Computer serves it free —
    # so `estimated_thermal_units` is 0 and staying 0 is the point.
    thermal_subscriptions: int
    estimated_thermal_scenes: int
    estimated_thermal_units: int


class RunRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    tenant_name: str | None
    farm_id: UUID
    farm_name: str | None
    kind: str
    sources: dict[str, Any]
    window_from: date
    window_to: date
    status: str
    error: str | None
    progress: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_by_email: str | None


# --- endpoints -------------------------------------------------------------


@router.get("/tenants", response_model=list[TenantOption])
async def list_tenants(
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_tenants()


@router.get("/tenants/{tenant_id}/farms", response_model=list[FarmOption])
async def list_farms(
    tenant_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    schema = await _schema_for(service, tenant_id)
    return await service.list_farms(schema)


@router.post("/tenants/{tenant_id}:estimate", response_model=EstimateResponse)
async def estimate(
    tenant_id: UUID,
    body: EstimateRequest,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> dict[str, Any]:
    del context
    schema = await _schema_for(service, tenant_id)
    return await service.estimate(
        tenant_schema=schema,
        farm_id=body.farm_id,
        window_from=body.window_from,
        window_to=body.window_to,
        imagery=body.imagery,
        weather=body.weather,
        thermal=body.thermal,
    )


@router.post(
    "/tenants/{tenant_id}/runs", response_model=RunRow, status_code=status.HTTP_201_CREATED
)
async def create_run(
    tenant_id: UUID,
    body: RunRequest,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> dict[str, Any]:
    tenant = await _tenant(service, tenant_id)
    try:
        return await service.create_run(
            tenant_id=tenant_id,
            tenant_schema=tenant["schema_name"],
            tenant_name=tenant["name"],
            farm_id=body.farm_id,
            window_from=body.window_from,
            window_to=body.window_to,
            imagery=body.imagery,
            weather=body.weather,
            kind=body.kind,
            actor_id=getattr(context, "user_id", None),
            actor_email=getattr(context, "email", None),
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "farm not found in this tenant") from exc
    except NoIntegrationConfigError as exc:
        # 422, not 409: the request is well-formed but the farm is not
        # configured for what it asks. Name the sources so the operator
        # knows to go set up subscriptions rather than retrying.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"This farm has no active {' or '.join(exc.missing)} subscriptions, "
            "so there is nothing to fetch. Configure them on the farm first.",
        ) from exc
    except BackfillConflictError as exc:
        # One run per farm: idempotency makes a concurrent run safe but not
        # free — it would re-fetch scenes the first run is already pulling.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A backfill run is already in progress for this farm "
            f"(run {exc.existing['id']}). Wait for it to finish.",
        ) from exc


@router.get("/runs", response_model=list[RunRow])
async def list_runs(
    tenant_id: UUID | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_runs(tenant_id=tenant_id, status=run_status, limit=limit)


@router.get("/runs/{run_id}", response_model=RunRow)
async def get_run(
    run_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> dict[str, Any]:
    del context
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.post("/runs/{run_id}:cancel", response_model=RunRow)
async def cancel_run(
    run_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: BackfillService = Depends(_service),
) -> dict[str, Any]:
    """Release a run that is stuck queued/running so its farm is free again.

    One run per farm is enforced by a partial unique index, so a run that
    never settles blocks that farm for good. Progress reporting is
    best-effort and a worker can die mid-task, so there has to be an
    operator escape hatch that is not "edit the table by hand".
    """
    row = await service.cancel_run(run_id=run_id, actor_email=getattr(context, "email", None))
    if row is not None:
        return row
    # Distinguish "no such run" from "already finished" — retrying helps in
    # neither case, but they mean very different things to the operator.
    if await service.get_run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    raise HTTPException(
        status.HTTP_409_CONFLICT, "This run has already finished; there is nothing to cancel."
    )


# --- helpers ---------------------------------------------------------------


async def _tenant(service: BackfillService, tenant_id: UUID) -> dict[str, Any]:
    for t in await service.list_tenants():
        if t["id"] == tenant_id:
            return t
    raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found or inactive")


async def _schema_for(service: BackfillService, tenant_id: UUID) -> str:
    return str((await _tenant(service, tenant_id))["schema_name"])
