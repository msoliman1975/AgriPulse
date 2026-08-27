"""Domain errors for the irrigation module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems/irrigation"


class IrrigationScheduleNotFoundError(APIError):
    def __init__(self, schedule_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Irrigation schedule not found",
            detail=f"No irrigation schedule with id {schedule_id} in this tenant.",
            type_=f"{_TYPE_BASE}/schedule-not-found",
            extras={"schedule_id": str(schedule_id)},
        )


class IrrigationTargetNotFoundError(APIError):
    """404 for a block or schedule the caller may not reach.

    Deliberately the same response whether the row is absent or simply on a
    farm the caller holds no scope on. A 403 would confirm that the id exists,
    which is how a caller enumerates the blocks of farms they cannot see. The
    block routes in `farms/router` answer the same way for the same reason.
    """

    def __init__(self, kind: str, target_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title=f"{kind.capitalize()} not found",
            detail=f"No {kind} with id {target_id} in this tenant.",
            type_=f"{_TYPE_BASE}/{kind}-not-found",
            extras={f"{kind}_id": str(target_id)},
        )


class InvalidIrrigationTransitionError(APIError):
    """409 â€” caller asked to apply / skip a schedule whose state doesn't
    allow it (e.g. applying an already-skipped row)."""

    def __init__(self, *, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Invalid irrigation state transition",
            detail=(f"Cannot {action} a schedule whose current status is {current_status!r}."),
            type_=f"{_TYPE_BASE}/invalid-transition",
            extras={"current_status": current_status, "action": action},
        )
