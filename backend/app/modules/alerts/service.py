"""Alerts service — alert lifecycle only (Stage 2 of rules sunset).

After PR-F retired the Beat sweep and Stage 2 dropped the rule tables,
this service has one job: drive an alert through its open → ack →
resolved (or snoozed → open) state machine with audit + event
publishes. Inserting new alerts is now the recommendations engine's
job (PR-E's ``_open_alert_from_tree`` calls
``AlertsRepository.insert_alert`` directly).

The ``public_session`` parameter on the constructor is kept for
backwards compatibility with existing call sites; nothing inside the
service touches it after Stage 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.alerts.errors import (
    AlertNotFoundError,
    InvalidAlertTransitionError,
)
from app.modules.alerts.events import (
    AlertAcknowledgedV1,
    AlertResolvedV1,
)
from app.modules.alerts.repository import AlertsRepository
from app.modules.audit import AuditService, get_audit_service
from app.shared.eventbus import EventBus, get_default_bus


class AlertsService(Protocol):
    """Public contract — alert reads + lifecycle transitions only."""

    async def list_alerts(
        self,
        *,
        block_id: UUID | None = None,
        status_filter: tuple[str, ...] = (),
        severity_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]: ...

    async def transition_alert(
        self,
        *,
        alert_id: UUID,
        action: str,
        snooze_until: datetime | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...


class AlertsServiceImpl:
    """Tenant-session-scoped concrete service."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        public_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._tenant = tenant_session
        self._public = public_session
        self._repo = AlertsRepository(tenant_session=tenant_session, public_session=public_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

    # ---- Reads --------------------------------------------------------

    async def list_alerts(
        self,
        *,
        block_id: UUID | None = None,
        status_filter: tuple[str, ...] = (),
        severity_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_alerts(
            block_id=block_id,
            status_filter=status_filter,
            severity_filter=severity_filter,
            limit=limit,
        )

    # ---- Transitions --------------------------------------------------

    async def transition_alert(
        self,
        *,
        alert_id: UUID,
        action: str,
        snooze_until: datetime | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Run the action through the alert state machine.

        Allowed transitions:

          * ``acknowledge`` from ``open`` or ``snoozed`` → ``acknowledged``
          * ``resolve`` from any active state → ``resolved``
          * ``snooze`` from ``open`` or ``acknowledged`` → ``snoozed``
            (requires ``snooze_until``)

        Anything else raises ``InvalidAlertTransitionError`` (HTTP 409).
        """
        before = await self._repo.get_alert(alert_id=alert_id)
        if before is None:
            raise AlertNotFoundError(alert_id)
        current = before["status"]

        if action == "acknowledge":
            if current not in ("open", "snoozed"):
                raise InvalidAlertTransitionError(current_status=current, action=action)
            new_status = "acknowledged"
        elif action == "resolve":
            if current == "resolved":
                raise InvalidAlertTransitionError(current_status=current, action=action)
            new_status = "resolved"
        elif action == "snooze":
            if current not in ("open", "acknowledged"):
                raise InvalidAlertTransitionError(current_status=current, action=action)
            if snooze_until is None:
                raise InvalidAlertTransitionError(
                    current_status=current, action="snooze (missing snooze_until)"
                )
            new_status = "snoozed"
        else:
            raise InvalidAlertTransitionError(current_status=current, action=action)

        await self._repo.transition_alert(
            alert_id=alert_id,
            new_status=new_status,
            actor_user_id=actor_user_id,
            snoozed_until=snooze_until,
        )
        after = await self._repo.get_alert(alert_id=alert_id)
        if after is None:
            raise AlertNotFoundError(alert_id)

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type=f"alerts.alert_{new_status}",
            actor_user_id=actor_user_id,
            subject_kind="alert",
            subject_id=alert_id,
            farm_id=None,
            details={
                "block_id": str(before["block_id"]),
                "rule_code": before["rule_code"],
                "previous_status": current,
            },
        )

        block_id = before["block_id"]
        rule_code = before["rule_code"]
        if new_status == "acknowledged":
            self._bus.publish(
                AlertAcknowledgedV1(
                    alert_id=alert_id,
                    block_id=block_id,
                    rule_code=rule_code,
                    actor_user_id=actor_user_id,
                )
            )
        elif new_status == "resolved":
            self._bus.publish(
                AlertResolvedV1(
                    alert_id=alert_id,
                    block_id=block_id,
                    rule_code=rule_code,
                    actor_user_id=actor_user_id,
                )
            )
        return after


def get_alerts_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> AlertsServiceImpl:
    return AlertsServiceImpl(tenant_session=tenant_session, public_session=public_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: AlertsServiceImpl) -> AlertsService:
    return impl
