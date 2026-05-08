"""Alerts service — public Protocol + concrete impl + factory.

Three responsibilities:

  * **Engine driver**: ``evaluate_block`` loads the merged rule set,
    snapshots block signals, and inserts alerts via the repository.
  * **State transitions**: ``transition_alert`` moves an alert through
    the open → ack → resolved (or snoozed → open) state machine, with
    audit + event publishes.
  * **Catalog reads**: surface the merged-with-overrides view of the
    rule library to the API and the alerts UI.

The Beat task in ``tasks.py`` is the only caller for tenant-wide
sweeps; everything else (admin endpoints, on-demand evaluations) goes
through this service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.alerts.engine import (
    BlockSignals,
    Rule,
    evaluate_rule,
    merge_rule,
)
from app.modules.alerts.errors import (
    AlertNotFoundError,
    InvalidAlertTransitionError,
    RuleNotFoundError,
)
from app.modules.alerts.events import (
    AlertAcknowledgedV1,
    AlertOpenedV1,
    AlertResolvedV1,
)
from app.modules.alerts.repository import AlertsRepository
from app.modules.audit import AuditService, get_audit_service
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


class AlertsService(Protocol):
    """Public contract."""

    async def evaluate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, int]: ...

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

    async def list_default_rules(self) -> tuple[dict[str, Any], ...]: ...

    async def list_overrides(self) -> tuple[dict[str, Any], ...]: ...

    async def upsert_override(
        self,
        *,
        rule_code: str,
        modified_conditions: dict[str, Any] | None,
        modified_actions: dict[str, Any] | None,
        modified_severity: str | None,
        is_disabled: bool,
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

    # ---- Engine driver ------------------------------------------------

    async def evaluate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, int]:
        """Run every active rule against ``block_id``; insert alerts.

        Returns a small summary so admin/debug callers can see what
        the evaluation did. The Beat task aggregates these per-tenant.
        """
        defaults = await self._repo.list_default_rules(status_filter="active")
        overrides = {o["rule_code"]: o for o in await self._repo.list_overrides()}
        latest = await self._repo.get_latest_aggregate_per_index(block_id=block_id)
        crop_category = await self._repo.get_block_crop_category(block_id=block_id)
        farm_id = await self._repo.get_block_farm_id(block_id=block_id)
        signals = BlockSignals(
            block_id=str(block_id),
            crop_category=crop_category,
            latest_index_aggregates=latest,
        )

        rules_evaluated = 0
        rules_skipped_disabled = 0
        alerts_opened = 0
        for default in defaults:
            override = overrides.get(default["code"])
            merged: Rule | None = merge_rule(default=default, override=override)
            if merged is None:
                rules_skipped_disabled += 1
                continue
            rules_evaluated += 1
            candidate = evaluate_rule(merged, signals)
            if candidate is None:
                continue

            alert_id = uuid7()
            inserted = await self._repo.insert_alert(
                alert_id=alert_id,
                block_id=block_id,
                rule_code=candidate.rule_code,
                severity=candidate.severity,
                diagnosis_en=candidate.diagnosis_en,
                diagnosis_ar=candidate.diagnosis_ar,
                prescription_en=candidate.prescription_en,
                prescription_ar=candidate.prescription_ar,
                prescription_activity_id=None,
                signal_snapshot=candidate.signal_snapshot,
                actor_user_id=actor_user_id,
            )
            if not inserted:
                # An open alert for this (block, rule) already exists.
                # Re-evaluation is intentionally idempotent — the open
                # alert remains the canonical "still firing".
                continue
            alerts_opened += 1
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type="alerts.alert_opened",
                actor_user_id=actor_user_id,
                actor_kind="system" if actor_user_id is None else "user",
                subject_kind="alert",
                subject_id=alert_id,
                farm_id=None,
                details={
                    "block_id": str(block_id),
                    "rule_code": candidate.rule_code,
                    "severity": candidate.severity,
                },
            )
            self._bus.publish(
                AlertOpenedV1(
                    alert_id=alert_id,
                    block_id=block_id,
                    rule_code=candidate.rule_code,
                    severity=candidate.severity,
                    created_at=datetime.now(UTC),
                    tenant_schema=tenant_schema,
                    farm_id=farm_id,
                    diagnosis_en=candidate.diagnosis_en,
                    diagnosis_ar=candidate.diagnosis_ar,
                    prescription_en=candidate.prescription_en,
                    prescription_ar=candidate.prescription_ar,
                    signal_snapshot=candidate.signal_snapshot,
                )
            )

        return {
            "rules_evaluated": rules_evaluated,
            "rules_skipped_disabled": rules_skipped_disabled,
            "alerts_opened": alerts_opened,
        }

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

    async def list_default_rules(self) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_default_rules(status_filter="active")

    async def list_overrides(self) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_overrides()

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

    # ---- Override management ------------------------------------------

    async def upsert_override(
        self,
        *,
        rule_code: str,
        modified_conditions: dict[str, Any] | None,
        modified_actions: dict[str, Any] | None,
        modified_severity: str | None,
        is_disabled: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        # Existence-check the rule_code so a typo surfaces as 404
        # rather than leaving the override sitting unused forever.
        if await self._repo.get_default_rule(rule_code=rule_code) is None:
            raise RuleNotFoundError(rule_code)
        out = await self._repo.upsert_override(
            rule_code=rule_code,
            modified_conditions=modified_conditions,
            modified_actions=modified_actions,
            modified_severity=modified_severity,
            is_disabled=is_disabled,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="alerts.rule_override_upserted",
            actor_user_id=actor_user_id,
            subject_kind="rule_override",
            subject_id=out["id"],
            farm_id=None,
            details={
                "rule_code": rule_code,
                "is_disabled": is_disabled,
                "has_conditions_override": modified_conditions is not None,
                "has_actions_override": modified_actions is not None,
                "modified_severity": modified_severity,
            },
        )
        return out


def get_alerts_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> AlertsServiceImpl:
    return AlertsServiceImpl(tenant_session=tenant_session, public_session=public_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: AlertsServiceImpl) -> AlertsService:
    return impl
