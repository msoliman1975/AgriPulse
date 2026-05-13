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
