"""Domain errors for the alerts module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://agripulse.cloud/problems/alerts"


class AlertNotFoundError(APIError):
    def __init__(self, alert_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Alert not found",
            detail=f"No alert with id {alert_id} in this tenant.",
            type_=f"{_TYPE_BASE}/alert-not-found",
            extras={"alert_id": str(alert_id)},
        )


class InvalidAlertTransitionError(APIError):
    """Caller asked to acknowledge / resolve / snooze an alert in a state
    that doesn't allow it (e.g. acknowledging a resolved alert)."""

    def __init__(self, *, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Invalid alert state transition",
            detail=(f"Cannot {action} an alert whose current status is {current_status!r}."),
            type_=f"{_TYPE_BASE}/invalid-transition",
            extras={"current_status": current_status, "action": action},
        )


class GroupMemberNotActionableError(APIError):
    """Caller addressed a per-cell member of a group instead of the group.

    Mirror of the recommendations error of the same name — the reasoning is
    identical and the two must stay in step, because the Action Center offers
    one set of buttons over both tables and cannot have one kind quietly accept
    what the other refuses.
    """

    def __init__(self, *, alert_id: UUID, parent_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Alert is part of a group",
            detail=(
                f"Alert {alert_id} is one cell of an aggregated item. "
                f"Act on the group ({parent_id}) instead."
            ),
            type_=f"{_TYPE_BASE}/group-member-not-actionable",
            extras={"alert_id": str(alert_id), "group_parent_id": str(parent_id)},
        )
