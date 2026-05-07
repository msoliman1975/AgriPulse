"""Domain errors for the alerts module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://missionagre.io/problems/alerts"


class AlertNotFoundError(APIError):
    def __init__(self, alert_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Alert not found",
            detail=f"No alert with id {alert_id} in this tenant.",
            type_=f"{_TYPE_BASE}/alert-not-found",
            extras={"alert_id": str(alert_id)},
        )


class RuleNotFoundError(APIError):
    def __init__(self, rule_code: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Rule not found",
            detail=f"No active default rule with code {rule_code!r}.",
            type_=f"{_TYPE_BASE}/rule-not-found",
            extras={"rule_code": rule_code},
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
