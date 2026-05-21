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

    async def get_activity(
        self, *, activity_id: UUID
    ) -> dict[str, Any] | None: ...

    async def create_flat_activity(
        self,
        *,
        farm_id: UUID,
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
        recommendation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def get_board(
        self,
        *,
        farm_id: UUID,
        week_start: date_type,
        weeks: int,
    ) -> dict[str, Any]: ...

    async def update_activity(
        self,
        *,
        activity_id: UUID,
        metadata_changes: dict[str, Any],
        state_action: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def delete_activity(
        self,
        *,
        activity_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

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
            farm_id=plan["farm_id"],
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

    async def create_flat_activity(
        self,
        *,
        farm_id: UUID,
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
        recommendation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Board-flow activity creation — no enclosing vegetation_plan.

        Used by `POST /api/v1/farms/{farm_id}/activities` and (via
        recommendation_id) by the rec-drag schedule flow in PR-5.
        """
        activity_id = uuid7()
        activity = await self._repo.insert_activity(
            activity_id=activity_id,
            plan_id=None,
            farm_id=farm_id,
            block_id=block_id,
            activity_type=activity_type,
            scheduled_date=scheduled_date,
            duration_days=duration_days,
            start_time=start_time,
            product_name=product_name,
            dosage=dosage,
            notes=notes,
            actor_user_id=actor_user_id,
            recommendation_id=recommendation_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.activity_scheduled",
            actor_user_id=actor_user_id,
            subject_kind="plan_activity",
            subject_id=activity_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "activity_type": activity_type,
                "scheduled_date": scheduled_date.isoformat(),
                "via": "board",
            },
        )
        self._bus.publish(
            PlanActivityScheduledV1(
                activity_id=activity_id,
                plan_id=None,
                block_id=block_id,
                activity_type=activity_type,
                scheduled_date=scheduled_date,
                actor_user_id=actor_user_id,
            )
        )
        return activity

    async def bulk_create_flat_activities(
        self,
        *,
        farm_id: UUID,
        cells: tuple[tuple[UUID, date_type], ...],
        activity_type: str,
        duration_days: int,
        start_time: time | None,
        notes: str | None,
        skip_existing: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Create one activity per (block_id, scheduled_date) pair.

        Returns ``{created: [...activities], skipped: [...{block_id, date}]}``.
        When ``skip_existing`` is True, any (block, date, activity_type)
        triple that already exists (excluding deleted_at-not-null rows)
        is skipped. Failures in the middle do not abort earlier
        successes — each row is its own savepoint.
        """
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for block_id, scheduled_date in cells:
            if skip_existing and await self._repo.activity_exists_on(
                block_id=block_id,
                scheduled_date=scheduled_date,
                activity_type=activity_type,
            ):
                skipped.append(
                    {
                        "block_id": str(block_id),
                        "scheduled_date": scheduled_date.isoformat(),
                        "reason": "duplicate",
                    }
                )
                continue
            row = await self.create_flat_activity(
                farm_id=farm_id,
                block_id=block_id,
                activity_type=activity_type,
                scheduled_date=scheduled_date,
                duration_days=duration_days,
                start_time=start_time,
                product_name=None,
                dosage=None,
                notes=notes,
                actor_user_id=actor_user_id,
                tenant_schema=tenant_schema,
            )
            created.append(row)
        return {"created": created, "skipped": skipped}

    async def get_board(
        self,
        *,
        farm_id: UUID,
        week_start: date_type,
        weeks: int,
    ) -> dict[str, Any]:
        """Return the board grid: blocks + activities (with resources)
        for a date window of ``weeks`` 7-day weeks starting on
        ``week_start``.
        """
        from datetime import timedelta

        to_date = week_start + timedelta(days=7 * weeks)
        blocks = await self._repo.list_active_blocks(farm_id=farm_id)
        activities = await self._repo.list_board_activities(
            farm_id=farm_id, from_date=week_start, to_date=to_date
        )
        return {
            "farm_id": str(farm_id),
            "week_start": week_start.isoformat(),
            "weeks": weeks,
            "blocks": blocks,
            "activities": activities,
        }

    async def get_activity(
        self, *, activity_id: UUID
    ) -> dict[str, Any] | None:
        """Fetch a single activity row by id, or None if missing.

        Used by adjacent modules (resources, recommendations) to gate
        on the activity's `farm_id` before performing per-farm RBAC
        checks. Does not raise — returns None so the caller can pick
        the right error type.
        """
        return await self._repo.get_activity(activity_id=activity_id)

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

    async def delete_activity(
        self,
        *,
        activity_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        """Soft-delete an activity. Idempotent on already-deleted rows
        (caller sees a 404 in that case via `get_activity` returning None).
        Audit trail records the actor + the prior status."""
        before = await self._repo.get_activity(activity_id=activity_id)
        if before is None:
            raise ActivityNotFoundError(activity_id)
        deleted = await self._repo.soft_delete_activity(
            activity_id=activity_id, actor_user_id=actor_user_id
        )
        if not deleted:
            # Lost the race — another caller deleted it between get + update.
            raise ActivityNotFoundError(activity_id)
        plan = (
            await self._repo.get_plan(plan_id=before["plan_id"])
            if before["plan_id"] is not None
            else None
        )
        farm_id = plan["farm_id"] if plan is not None else before.get("farm_id")
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plans.activity_deleted",
            actor_user_id=actor_user_id,
            subject_kind="plan_activity",
            subject_id=activity_id,
            farm_id=farm_id,
            details={
                "plan_id": str(before["plan_id"]) if before["plan_id"] else None,
                "block_id": str(before["block_id"]),
                "previous_status": before["status"],
                "activity_type": before["activity_type"],
            },
        )

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
