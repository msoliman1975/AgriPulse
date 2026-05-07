"""Domain errors for the plans module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://missionagre.io/problems/plans"


class PlanNotFoundError(APIError):
    def __init__(self, plan_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Plan not found",
            detail=f"No plan with id {plan_id} in this tenant.",
            type_=f"{_TYPE_BASE}/plan-not-found",
            extras={"plan_id": str(plan_id)},
        )


class ActivityNotFoundError(APIError):
    def __init__(self, activity_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Plan activity not found",
            detail=f"No plan activity with id {activity_id} in this tenant.",
            type_=f"{_TYPE_BASE}/activity-not-found",
            extras={"activity_id": str(activity_id)},
        )


class PlanCodeConflictError(APIError):
    """409 when (farm_id, season_label) already has a plan."""

    def __init__(self, *, farm_id: UUID, season_label: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Plan already exists for this season",
            detail=(f"Farm {farm_id} already has a plan for season {season_label!r}."),
            type_=f"{_TYPE_BASE}/plan-conflict",
            extras={"farm_id": str(farm_id), "season_label": season_label},
        )


class InvalidActivityTransitionError(APIError):
    """409 when an activity is asked to transition out of a state that
    doesn't allow it (e.g. completing an already-skipped activity)."""

    def __init__(self, *, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Invalid activity state transition",
            detail=(f"Cannot {action} an activity whose current status is {current_status!r}."),
            type_=f"{_TYPE_BASE}/invalid-activity-transition",
            extras={"current_status": current_status, "action": action},
        )
