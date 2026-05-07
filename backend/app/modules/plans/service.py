"""Plans service — public Protocol + concrete impl + factory.

Two layers:

  * Plan-level CRUD: create, read, list, update metadata, archive.
  * Activity-level CRUD + state machine:
    ``scheduled → in_progress → completed | skipped``.
    ``state`` actions on ``ActivityUpdateRequest`` drive the transitions
    (``start`` / ``complete`` / ``skip``); metadata edits are independent.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from datetime import date as date_type
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.plans.errors import (
    ActivityNotFoundError,
    InvalidActivityTransitionError,
    PlanNotFoundError,
)
from app.modules.plans.events import (
    PlanActivityCompletedV1,
    PlanActivityScheduledV1,
    PlanActivitySkippedV1,
    VegetationPlanCreatedV1,
)
from app.modules.plans.repository import PlansRepository
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


class PlansService(Protocol):
    """Public contract."""

    async def create_plan(
        self,
        *,
        farm_id: UUID,
        season_label: str,
        season_year: int,
        name: str | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def list_plans(
        self,
        *,
        farm_id: UUID,
        season_year: int | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]: ...

    async def get_plan(self, *, plan_id: UUID) -> dict[str, Any]: ...

    async def update_plan(
        self,
        *,
        plan_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def archive_plan(
        self,
        *,
        plan_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

    async def create_activity(
        self,
        *,
        plan_id: UUID,
        block_id: UUID,
        activity_type: str,
        scheduled_date: date_type,
        duration_days: int,
        start_time: time | None,
        product_name: str | None,
        dosage: str | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def list_activities(self, *, plan_id: UUID) -> tuple[dict[str, Any], ...]: ...

    async def update_activity(
        self,
        *,
        activity_id: UUID,
        metadata_changes: dict[str, Any],
        state_action: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def list_calendar(
        self,
        *,
        farm_id: UUID,
        from_date: date_type,
        to_date: date_type,
    ) -> tuple[dict[str, Any], ...]: ...


class PlansServiceImpl:
    """Concrete service. Tenant-session scoped."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._session = tenant_session
        self._repo = PlansRepository(tenant_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

    # ---- Plans --------------------------------------------------------

    async def create_plan(
        self,
        *,
        farm_id: UUID,
        season_label: str,
        season_year: int,
        name: str | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        plan_id = uuid7()
        plan = await self._repo.insert_plan(
            plan_id=plan_id,
            farm_id=farm_id,
            season_label=season_label,
            season_year=season_year,
            name=name,
            notes=notes,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.plan_created",
            actor_user_id=actor_user_id,
            subject_kind="vegetation_plan",
            subject_id=plan_id,
            farm_id=farm_id,
            details={"season_label": season_label, "season_year": season_year},
        )
        self._bus.publish(
            VegetationPlanCreatedV1(
                plan_id=plan_id,
                farm_id=farm_id,
                season_label=season_label,
                actor_user_id=actor_user_id,
            )
        )
        return plan

    async def list_plans(
        self,
        *,
        farm_id: UUID,
        season_year: int | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_plans(
            farm_id=farm_id,
            season_year=season_year,
            include_archived=include_archived,
        )

    async def get_plan(self, *, plan_id: UUID) -> dict[str, Any]:
        plan = await self._repo.get_plan(plan_id=plan_id)
        if plan is None:
            raise PlanNotFoundError(plan_id)
        return plan

    async def update_plan(
        self,
        *,
        plan_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        before = await self._repo.get_plan(plan_id=plan_id)
        if before is None:
            raise PlanNotFoundError(plan_id)
        after = await self._repo.update_plan(
            plan_id=plan_id, changes=changes, actor_user_id=actor_user_id
        )
        if after is None:
            raise PlanNotFoundError(plan_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.plan_updated",
            actor_user_id=actor_user_id,
            subject_kind="vegetation_plan",
            subject_id=plan_id,
            farm_id=before["farm_id"],
            details={"changed_fields": sorted(changes.keys())},
        )
        return after

    async def archive_plan(
        self,
        *,
        plan_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        before = await self._repo.get_plan(plan_id=plan_id)
        if before is None:
            raise PlanNotFoundError(plan_id)
        await self._repo.archive_plan(plan_id=plan_id, actor_user_id=actor_user_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.plan_archived",
            actor_user_id=actor_user_id,
            subject_kind="vegetation_plan",
            subject_id=plan_id,
            farm_id=before["farm_id"],
            details={},
        )

    # ---- Activities ---------------------------------------------------

    async def create_activity(
        self,
        *,
        plan_id: UUID,
        block_id: UUID,
        activity_type: str,
        scheduled_date: date_type,
        duration_days: int,
        start_time: time | None,
        product_name: str | None,
        dosage: str | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        # Confirm parent plan exists in this tenant — surfaces 404
        # cleanly if a stale plan_id leaks past the router.
        plan = await self._repo.get_plan(plan_id=plan_id)
        if plan is None:
            raise PlanNotFoundError(plan_id)
        activity_id = uuid7()
        activity = await self._repo.insert_activity(
            activity_id=activity_id,
            plan_id=plan_id,
            block_id=block_id,
            activity_type=activity_type,
            scheduled_date=scheduled_date,
            duration_days=duration_days,
            start_time=start_time,
            product_name=product_name,
            dosage=dosage,
            notes=notes,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.activity_scheduled",
            actor_user_id=actor_user_id,
            subject_kind="plan_activity",
            subject_id=activity_id,
            farm_id=plan["farm_id"],
            details={
                "plan_id": str(plan_id),
                "block_id": str(block_id),
                "activity_type": activity_type,
                "scheduled_date": scheduled_date.isoformat(),
            },
        )
        self._bus.publish(
            PlanActivityScheduledV1(
                activity_id=activity_id,
                plan_id=plan_id,
                block_id=block_id,
                activity_type=activity_type,
                scheduled_date=scheduled_date,
                actor_user_id=actor_user_id,
            )
        )
        return activity

    async def list_activities(self, *, plan_id: UUID) -> tuple[dict[str, Any], ...]:
        if await self._repo.get_plan(plan_id=plan_id) is None:
            raise PlanNotFoundError(plan_id)
        return await self._repo.list_activities(plan_id=plan_id)

    async def update_activity(
        self,
        *,
        activity_id: UUID,
        metadata_changes: dict[str, Any],
        state_action: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        before = await self._repo.get_activity(activity_id=activity_id)
        if before is None:
            raise ActivityNotFoundError(activity_id)

        changes = dict(metadata_changes)
        new_status: str | None = None
        if state_action is not None:
            current = before["status"]
            if state_action == "start":
                if current != "scheduled":
                    raise InvalidActivityTransitionError(current_status=current, action="start")
                new_status = "in_progress"
            elif state_action == "complete":
                if current not in ("scheduled", "in_progress"):
                    raise InvalidActivityTransitionError(current_status=current, action="complete")
                new_status = "completed"
                changes["completed_at"] = datetime.now(UTC)
                changes["completed_by"] = actor_user_id
            elif state_action == "skip":
                if current not in ("scheduled", "in_progress"):
                    raise InvalidActivityTransitionError(current_status=current, action="skip")
                new_status = "skipped"
            else:
                raise InvalidActivityTransitionError(current_status=current, action=state_action)
            changes["status"] = new_status

        after = await self._repo.update_activity(
            activity_id=activity_id, changes=changes, actor_user_id=actor_user_id
        )
        if after is None:
            raise ActivityNotFoundError(activity_id)

        plan = await self._repo.get_plan(plan_id=before["plan_id"])
        farm_id = plan["farm_id"] if plan is not None else None
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type=(
                f"plans.activity_{new_status}"
                if new_status is not None
                else "plans.activity_updated"
            ),
            actor_user_id=actor_user_id,
            subject_kind="plan_activity",
            subject_id=activity_id,
            farm_id=farm_id,
            details={
                "plan_id": str(before["plan_id"]),
                "block_id": str(before["block_id"]),
                "previous_status": before["status"],
                "changed_fields": sorted(changes.keys()),
            },
        )
        if new_status == "completed":
            self._bus.publish(
                PlanActivityCompletedV1(
                    activity_id=activity_id,
                    plan_id=before["plan_id"],
                    block_id=before["block_id"],
                    actor_user_id=actor_user_id,
                )
            )
        elif new_status == "skipped":
            self._bus.publish(
                PlanActivitySkippedV1(
                    activity_id=activity_id,
                    plan_id=before["plan_id"],
                    block_id=before["block_id"],
                    actor_user_id=actor_user_id,
                )
            )
        return after

    async def list_calendar(
        self,
        *,
        farm_id: UUID,
        from_date: date_type,
        to_date: date_type,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_calendar(farm_id=farm_id, from_date=from_date, to_date=to_date)


def get_plans_service(*, tenant_session: AsyncSession) -> PlansServiceImpl:
    return PlansServiceImpl(tenant_session=tenant_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: PlansServiceImpl) -> PlansService:
    return impl
