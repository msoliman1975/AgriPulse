"""Scouting API — dispatch, the visit lifecycle, and routing rules.

Every route is gated on a **farm-scoped** capability via `farm_id_param`, the
pattern PR #270 established so a farm-scoped-only user (which is exactly what a
Scout is) can reach its own farm's data. There is no mobile-specific
authorization path here, and there should never be one: the phone is gated by
the same middleware as the web app.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scouting.assignees import list_farm_assignees
from app.modules.scouting.schemas import (
    AssigneeResponse,
    RoutingRuleResponse,
    RoutingRuleWriteRequest,
    ScoutingVisitResponse,
    VisitAssignRequest,
    VisitDeclineRequest,
    VisitDispatchRequest,
    VisitSelfInitiatedRequest,
    VisitSubmitRequest,
)
from app.modules.scouting.service import ScoutingService, get_scouting_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["scouting"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    context: RequestContext = Depends(get_current_context),
) -> ScoutingService:
    # The schema rides along so assignment events can be scoped without the
    # service re-deriving it from the connection.
    return get_scouting_service(tenant_session=tenant_session, tenant_schema=context.tenant_schema)


@router.get(
    "/scouting/visits",
    response_model=list[ScoutingVisitResponse],
    summary="List scouting visits on a farm.",
)
async def list_visits(
    farm_id: UUID = Query(description="Farm to list visits for."),
    mine: bool = Query(default=False, description="Only visits assigned to the caller."),
    claimable: bool = Query(default=False, description="Only unassigned, queued visits."),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.read", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> list[dict[str, Any]]:
    return list(
        await service.list_visits(
            farm_id=farm_id,
            assigned_to=context.user_id if mine else None,
            claimable=claimable,
            statuses=tuple(status_filter or ()),
        )
    )


@router.get(
    "/scouting/assignees",
    response_model=list[AssigneeResponse],
    summary="People on this farm who can be sent on a visit.",
)
async def list_assignees(
    farm_id: UUID = Query(description="Farm to list possible assignees for."),
    # `scouting.dispatch` and not `user.read`: this answers "who can I send",
    # which is part of dispatching, and gating it on tenant-wide directory
    # access is what put the picker out of reach of a farm-scoped supervisor.
    context: RequestContext = Depends(
        requires_capability("scouting.dispatch", farm_id_param="farm_id")
    ),
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    return await list_farm_assignees(
        public_session=public_session,
        tenant_session=tenant_session,
        farm_id=farm_id,
    )


@router.get(
    "/scouting/visits/{visit_id}",
    response_model=ScoutingVisitResponse,
    summary="A single visit, self-contained enough to render offline.",
)
async def get_visit(
    visit_id: UUID,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.read", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del context, farm_id
    return await service.get_visit(visit_id=visit_id)


@router.post(
    "/scouting/visits/{visit_id}:claim",
    response_model=ScoutingVisitResponse,
    summary="Claim an unassigned visit (409 if someone else got there first).",
)
async def claim_visit(
    visit_id: UUID,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.claim", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.claim(visit_id=visit_id, actor_user_id=context.user_id)


@router.post(
    "/scouting/visits/{visit_id}:accept",
    response_model=ScoutingVisitResponse,
    summary="Accept a visit assigned to you.",
)
async def accept_visit(
    visit_id: UUID,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.claim", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.accept(visit_id=visit_id, actor_user_id=context.user_id)


@router.post(
    "/scouting/visits/{visit_id}:decline",
    response_model=ScoutingVisitResponse,
    summary="Decline a visit; it returns to the queue with your reason.",
)
async def decline_visit(
    visit_id: UUID,
    payload: VisitDeclineRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.claim", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.decline(
        visit_id=visit_id, reason=payload.reason, actor_user_id=context.user_id
    )


@router.post(
    "/scouting/visits/{visit_id}:start",
    response_model=ScoutingVisitResponse,
    summary="Mark arrival on the block. Idempotent.",
)
async def start_visit(
    visit_id: UUID,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.claim", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.start(visit_id=visit_id, actor_user_id=context.user_id)


@router.post(
    "/scouting/visits/{visit_id}:submit",
    response_model=ScoutingVisitResponse,
    summary="Close a visit with an outcome. Replaying an idempotency key is safe.",
)
async def submit_visit(
    visit_id: UUID,
    payload: VisitSubmitRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.complete", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.submit(visit_id=visit_id, payload=payload, actor_user_id=context.user_id)


@router.post(
    "/scouting/visits",
    response_model=ScoutingVisitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a self-initiated visit — the scout was already there.",
)
async def create_self_initiated(
    payload: VisitSelfInitiatedRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.complete", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    return await service.create_self_initiated(
        farm_id=farm_id, payload=payload, actor_user_id=context.user_id
    )


# ---------- Supervisor ------------------------------------------------------


@router.post(
    "/scouting/visits:dispatch",
    response_model=ScoutingVisitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise an ad-hoc visit from the map, with your own instructions.",
)
async def dispatch_visit(
    payload: VisitDispatchRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.dispatch", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    return await service.dispatch_ad_hoc(
        farm_id=farm_id, payload=payload, actor_user_id=context.user_id
    )


@router.post(
    "/scouting/visits/{visit_id}:assign",
    response_model=ScoutingVisitResponse,
    summary="Assign or reassign a visit.",
)
async def assign_visit(
    visit_id: UUID,
    payload: VisitAssignRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.assign", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.assign(
        visit_id=visit_id,
        assignee_user_id=payload.assignee_user_id,
        actor_user_id=context.user_id,
    )


@router.post(
    "/scouting/visits/{visit_id}:cancel",
    response_model=ScoutingVisitResponse,
    summary="Withdraw a visit.",
)
async def cancel_visit(
    visit_id: UUID,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.visit.assign", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.cancel(visit_id=visit_id, actor_user_id=context.user_id)


# ---------- Routing rules ---------------------------------------------------


@router.get(
    "/scouting/routing-rules",
    response_model=list[RoutingRuleResponse],
    summary="Routing rules that apply to a farm (including tenant-wide ones).",
)
async def list_rules(
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.rule.manage", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return list(await service.list_rules(farm_id=farm_id))


@router.put(
    "/scouting/routing-rules",
    response_model=RoutingRuleResponse,
    summary="Create or replace the routing rule for a scope.",
)
async def upsert_rule(
    payload: RoutingRuleWriteRequest,
    farm_id: UUID = Query(),
    context: RequestContext = Depends(
        requires_capability("scouting.rule.manage", farm_id_param="farm_id")
    ),
    service: ScoutingService = Depends(_service),
) -> dict[str, Any]:
    del farm_id
    return await service.upsert_rule(payload=payload, actor_user_id=context.user_id)
