"""Scouting domain errors, mapped to Problem Details by the API error layer."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_BASE = "https://agripulse.cloud/problems"


class ScoutingVisitNotFoundError(APIError):
    def __init__(self, visit_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Scouting visit not found",
            detail=f"No scouting visit with id {visit_id}.",
            type_=f"{_BASE}/scouting-visit-not-found",
        )


class InvalidVisitTransitionError(APIError):
    """The requested move is not legal from the visit's current state.

    Carries both states because "409" alone tells a scout nothing, and the
    mobile client shows this text verbatim when a visit changed underneath it.
    """

    def __init__(self, *, current: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Visit cannot change state",
            detail=f"A visit that is '{current}' cannot be {action}.",
            type_=f"{_BASE}/invalid-visit-transition",
        )


class VisitAlreadyClaimedError(APIError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Visit already claimed",
            detail="Someone else claimed this visit first.",
            type_=f"{_BASE}/visit-already-claimed",
        )


class NotVisitAssigneeError(APIError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not your visit",
            detail="Only the assignee can act on this visit.",
            type_=f"{_BASE}/not-visit-assignee",
        )
