"""Async DB access for the plans module. Internal to the module."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import and_, bindparam, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plans.errors import PlanCodeConflictError
from app.modules.plans.models import PlanActivity, VegetationPlan


class PlansRepository:
    """Internal repository — service is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Plans --------------------------------------------------------

    async def insert_plan(
        self,
        *,
        plan_id: UUID,
        farm_id: UUID,
        season_label: str,
        season_year: int,
        name: str | None,
        notes: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        plan = VegetationPlan(
            id=plan_id,
            farm_id=farm_id,
            season_label=season_label,
            season_year=season_year,
            name=name,
            notes=notes,
            status="draft",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(plan)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "uq_vegetation_plans_farm_season_active" in str(exc):
                raise PlanCodeConflictError(farm_id=farm_id, season_label=season_label) from exc
            raise
        return _plan_to_dict(plan)

    async def get_plan(self, *, plan_id: UUID) -> dict[str, Any] | None:
        stmt = select(VegetationPlan).where(
            VegetationPlan.id == plan_id, VegetationPlan.deleted_at.is_(None)
        )
        row = (await self._session.execute(stmt)).scalars().one_or_none()
        return _plan_to_dict(row) if row is not None else None

    async def list_plans(
        self,
        *,
        farm_id: UUID,
        season_year: int | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        clauses = [VegetationPlan.farm_id == farm_id]
        if season_year is not None:
            clauses.append(VegetationPlan.season_year == season_year)
        if not include_archived:
            # Default view hides archived (status='archived' + deleted_at set).
            # When include_archived=True the caller wants to see them, so we
            # don't filter deleted_at at all — archive sets both flags.
            clauses.append(VegetationPlan.deleted_at.is_(None))
            clauses.append(VegetationPlan.status != "archived")
        stmt = (
            select(VegetationPlan)
            .where(and_(*clauses))
            .order_by(
                VegetationPlan.season_year.desc(),
                VegetationPlan.season_label,
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_plan_to_dict(r) for r in rows)

    async def update_plan(
        self,
        *,
        plan_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        if not changes:
            return await self.get_plan(plan_id=plan_id)
        await self._session.execute(
            update(VegetationPlan)
            .where(VegetationPlan.id == plan_id)
            .values(**changes, updated_by=actor_user_id)
        )
        return await self.get_plan(plan_id=plan_id)

    async def archive_plan(self, *, plan_id: UUID, actor_user_id: UUID | None) -> None:
        await self._session.execute(
            update(VegetationPlan)
            .where(VegetationPlan.id == plan_id)
            .values(
                status="archived",
                deleted_at=text("now()"),
                updated_by=actor_user_id,
            )
        )

    # ---- Activities ---------------------------------------------------

    async def insert_activity(
        self,
        *,
        activity_id: UUID,
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
    ) -> dict[str, Any]:
        activity = PlanActivity(
            id=activity_id,
            plan_id=plan_id,
            block_id=block_id,
            activity_type=activity_type,
            scheduled_date=scheduled_date,
            duration_days=duration_days,
            start_time=start_time,
            product_name=product_name,
            dosage=dosage,
            notes=notes,
            status="scheduled",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(activity)
        await self._session.flush()
        return _activity_to_dict(activity)

    async def get_activity(self, *, activity_id: UUID) -> dict[str, Any] | None:
        stmt = select(PlanActivity).where(
            PlanActivity.id == activity_id, PlanActivity.deleted_at.is_(None)
        )
        row = (await self._session.execute(stmt)).scalars().one_or_none()
        return _activity_to_dict(row) if row is not None else None

    async def list_activities(self, *, plan_id: UUID) -> tuple[dict[str, Any], ...]:
        stmt = (
            select(PlanActivity)
            .where(PlanActivity.plan_id == plan_id, PlanActivity.deleted_at.is_(None))
            .order_by(PlanActivity.scheduled_date, PlanActivity.id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_activity_to_dict(r) for r in rows)

    async def update_activity(
        self,
        *,
        activity_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        if not changes:
            return await self.get_activity(activity_id=activity_id)
        await self._session.execute(
            update(PlanActivity)
            .where(PlanActivity.id == activity_id)
            .values(**changes, updated_by=actor_user_id)
        )
        return await self.get_activity(activity_id=activity_id)

    async def list_calendar(
        self,
        *,
        farm_id: UUID,
        from_date: date_type,
        to_date: date_type,
    ) -> tuple[dict[str, Any], ...]:
        """Activities scheduled in [from_date, to_date) for any plan
        belonging to the given farm. Used by the calendar endpoint.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT a.id, a.plan_id, a.block_id, a.activity_type,
                               a.scheduled_date, a.duration_days, a.start_time,
                               a.product_name, a.dosage,
                               a.notes, a.status, a.completed_at, a.completed_by,
                               a.created_at, a.updated_at
                        FROM plan_activities a
                        JOIN vegetation_plans p ON p.id = a.plan_id
                        WHERE p.farm_id = :farm_id
                          AND p.deleted_at IS NULL
                          AND a.deleted_at IS NULL
                          AND a.scheduled_date >= :from_date
                          AND a.scheduled_date < :to_date
                        ORDER BY a.scheduled_date, a.id
                        """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "from_date": from_date, "to_date": to_date},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)


def _plan_to_dict(row: VegetationPlan) -> dict[str, Any]:
    return {
        "id": row.id,
        "farm_id": row.farm_id,
        "season_label": row.season_label,
        "season_year": row.season_year,
        "name": row.name,
        "notes": row.notes,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _activity_to_dict(row: PlanActivity) -> dict[str, Any]:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "block_id": row.block_id,
        "activity_type": row.activity_type,
        "scheduled_date": row.scheduled_date,
        "duration_days": row.duration_days,
        "start_time": row.start_time,
        "product_name": row.product_name,
        "dosage": row.dosage,
        "notes": row.notes,
        "status": row.status,
        "completed_at": row.completed_at,
        "completed_by": row.completed_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# Suppress unused-import warning when these are referenced only in type
# hints for activity rows.
_ = (datetime, time)
