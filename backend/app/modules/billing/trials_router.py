"""The platform trial review queue.

Mounted at /api/v1/platform/trials. This is where a trial tenant is
actually decided: `POST /{id}/approve` is the only route in the service
that leads to a tenant schema being created.

The list route returns the capacity numbers alongside the rows, in one
call. Splitting them would let a screen render a queue with no idea whether
there is room to approve anything on it, which is the one thing the screen
exists to prevent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.audit import get_audit_service
from app.modules.billing.errors import (
    CapReachedError,
    InvalidTransitionError,
    SignupNotFoundError,
)
from app.modules.billing.service import TrialService, is_free_mail
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/platform/trials", tags=["platform-trials"])

_ReadTrials = Depends(requires_capability("platform.trial.read"))
_ManageTrials = Depends(requires_capability("platform.trial.manage"))


class TrialSignupRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    full_name: str
    email: str
    email_domain: str
    organisation: str
    country: str | None
    phone: str | None
    created_at: datetime | None
    verified_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by: UUID | None
    decision_reason: str | None
    cap_override: bool
    tenant_id: UUID | None
    provisioning_attempts: int
    last_error: str | None
    #: Flags an admin needs to judge a row without opening anything else.
    is_free_mail: bool = False
    waiting_hours: float | None = None


class CapacityResponse(BaseModel):
    """The numbers above the queue. Every one of them answers "is there
    room for another tenant right now".
    """

    approved_today: int
    approved_this_week: int
    cap_per_day: int
    cap_per_week: int
    day_resets_at: str
    week_resets_at: str
    can_approve: bool
    queue_depth: int
    oldest_wait_hours: float | None
    live_trials: int
    expired_trials: int
    converted_trials: int
    trial_farms: int
    trial_area_feddan: int


class TrialQueueResponse(BaseModel):
    capacity: CapacityResponse
    signups: list[TrialSignupRow]


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_reason: str | None = Field(
        default=None,
        min_length=8,
        max_length=500,
        description=(
            "Required only to approve past a cap. Written to the audit log "
            "with both counts and the actor."
        ),
    )


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=4,
        max_length=500,
        description="Shown to the person who asked. Write it for them to read.",
    )


async def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> TrialService:
    return TrialService(public_session=session, audit=get_audit_service())


@router.get("", response_model=TrialQueueResponse, summary="The trial review queue.")
async def list_trials(
    include_recent: bool = Query(
        default=False,
        description="Include decided rows, newest first, instead of only the open queue.",
    ),
    context: RequestContext = _ReadTrials,
    service: TrialService = Depends(_service),
) -> TrialQueueResponse:
    del context
    capacity = await service.capacity()
    signups = await service.list_queue(include_recent=include_recent)
    return TrialQueueResponse(
        capacity=CapacityResponse(**capacity),
        signups=[_row(s) for s in signups],
    )


@router.post(
    "/{signup_id}/approve",
    response_model=TrialSignupRow,
    summary="Approve a trial request and start provisioning.",
)
async def approve(
    signup_id: UUID,
    payload: ApproveRequest,
    context: RequestContext = _ManageTrials,
    service: TrialService = Depends(_service),
) -> TrialSignupRow:
    try:
        signup = await service.approve(
            signup_id=signup_id,
            actor_user_id=context.user_id,
            override_reason=payload.override_reason,
        )
    except SignupNotFoundError as exc:
        raise _not_found(signup_id) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc
    except CapReachedError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Provisioning cap reached",
            detail=(
                f"The {exc.scope} cap of {exc.cap} is used ({exc.used}). "
                "Approve past it by giving a reason."
            ),
            type_="https://agripulse.cloud/problems/trial-cap-reached",
            extras={
                "scope": exc.scope,
                "used": exc.used,
                "cap": exc.cap,
                "resets_at": exc.resets_at,
            },
        ) from exc

    # Enqueued after the state change, not before: a task that starts before
    # the row says `approved` would find nothing to do.
    _enqueue_provisioning(signup.id)
    return _row(signup)


@router.post(
    "/{signup_id}/pause",
    response_model=TrialSignupRow,
    summary="Hold a trial request on capacity. It stays in the queue.",
)
async def pause(
    signup_id: UUID,
    payload: PauseRequest,
    context: RequestContext = _ManageTrials,
    service: TrialService = Depends(_service),
) -> TrialSignupRow:
    try:
        signup = await service.pause(
            signup_id=signup_id,
            actor_user_id=context.user_id,
            reason=payload.reason,
        )
    except SignupNotFoundError as exc:
        raise _not_found(signup_id) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc
    return _row(signup)


@router.post(
    "/{signup_id}/reject",
    response_model=TrialSignupRow,
    summary="Reject a trial request. The reason is sent to the person who asked.",
)
async def reject(
    signup_id: UUID,
    payload: RejectRequest,
    context: RequestContext = _ManageTrials,
    service: TrialService = Depends(_service),
) -> TrialSignupRow:
    try:
        signup = await service.reject(
            signup_id=signup_id,
            actor_user_id=context.user_id,
            reason=payload.reason,
        )
    except SignupNotFoundError as exc:
        raise _not_found(signup_id) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc
    return _row(signup)


def _row(signup: Any) -> TrialSignupRow:
    row = TrialSignupRow.model_validate(signup)
    row.is_free_mail = is_free_mail(signup.email_domain)
    if signup.created_at is not None and signup.status in ("awaiting_approval", "paused"):
        row.waiting_hours = round(
            (datetime.now(signup.created_at.tzinfo) - signup.created_at).total_seconds() / 3600.0,
            1,
        )
    return row


def _not_found(signup_id: UUID) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Trial signup not found",
        detail=f"No trial signup with id {signup_id}.",
        type_="https://agripulse.cloud/problems/trial-signup-not-found",
    )


def _conflict(exc: InvalidTransitionError) -> APIError:
    return APIError(
        status_code=status.HTTP_409_CONFLICT,
        title="Action not available in this state",
        detail=str(exc),
        type_="https://agripulse.cloud/problems/trial-invalid-transition",
        extras={"current_status": exc.current, "action": exc.action},
    )


def _enqueue_provisioning(signup_id: UUID) -> None:
    """Hand the row to the worker.

    Imported inside the function so the API process does not pull Celery in
    at import time, and so a broker that is briefly unreachable fails this
    one call rather than the module import. The approval is already
    committed either way — a stuck row shows on this screen as
    `approved` with no tenant, which is exactly what an operator needs to
    see.
    """
    from app.modules.billing.tasks import provision_trial

    provision_trial.delay(str(signup_id))
