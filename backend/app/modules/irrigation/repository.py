"""Async DB access for the irrigation module. Internal."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.irrigation.errors import (
    InvalidIrrigationTransitionError,
)
from app.modules.irrigation.models import IrrigationSchedule


class IrrigationRepository:
    """Internal repository — service is the only consumer."""

    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        self._public = public_session

    # ---- Reads of upstream data feeding the engine --------------------

    async def get_block_context(self, *, block_id: UUID) -> dict[str, Any] | None:
        """Pull farm_id + the block's current crop assignment + crop
        catalog merge for the engine. Returns None when the block has
        no current crop — the caller skips it."""
        row = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT b.id AS block_id, b.farm_id,
                           b.irrigation_system,
                           bc.id AS block_crop_id,
                           bc.crop_id, bc.crop_variety_id, bc.growth_stage
                    FROM blocks b
                    LEFT JOIN block_crops bc
                      ON bc.block_id = b.id
                     AND bc.is_current = TRUE
                     AND bc.deleted_at IS NULL
                    WHERE b.id = :block_id
                      AND b.deleted_at IS NULL
                    """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        out = dict(row)
        if out.get("crop_id") is None:
            return out  # caller will skip; no crop assigned
        crop_row = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT id, code, phenology_stages
                    FROM public.crops
                    WHERE id = :id AND is_active = TRUE
                    """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": out["crop_id"]},
                )
            )
            .mappings()
            .one_or_none()
        )
        out["crop_phenology_stages"] = (
            crop_row["phenology_stages"] if crop_row is not None else None
        )
        out["crop_code"] = crop_row["code"] if crop_row is not None else None

        out["variety_phenology_override"] = None
        if out.get("crop_variety_id") is not None:
            v_row = (
                (
                    await self._public.execute(
                        text(
                            """
                        SELECT phenology_stages_override
                        FROM public.crop_varieties
                        WHERE id = :id AND is_active = TRUE
                        """
                        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                        {"id": out["crop_variety_id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if v_row is not None:
                out["variety_phenology_override"] = v_row["phenology_stages_override"]
        return out

    async def get_recent_weather(
        self,
        *,
        farm_id: UUID,
        target_date: date_type,
        precip_window_days: int = 2,
    ) -> dict[str, Decimal]:
        """ET₀ for the target day + summed precipitation in
        ``[target_date - precip_window_days, target_date]`` (inclusive).
        Both are in millimetres; missing rows return zero so the engine
        runs on partial data."""
        et0_row = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT COALESCE(et0_mm_daily, 0) AS et0
                    FROM weather_derived_daily
                    WHERE farm_id = :farm_id AND date = :d
                    """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {"farm_id": farm_id, "d": target_date},
                )
            )
            .mappings()
            .one_or_none()
        )
        et0 = Decimal(str(et0_row["et0"])) if et0_row else Decimal(0)

        precip_row = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT COALESCE(SUM(precip_mm_daily), 0) AS precip
                    FROM weather_derived_daily
                    WHERE farm_id = :farm_id
                      AND date >= :since
                      AND date <= :d
                    """
                    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                    {
                        "farm_id": farm_id,
                        "since": target_date - timedelta(days=precip_window_days),
                        "d": target_date,
                    },
                )
            )
            .mappings()
            .one()
        )
        precip = Decimal(str(precip_row["precip"]))
        return {"et0_mm_today": et0, "recent_precip_mm": precip}

    # ---- Schedule writes ---------------------------------------------

    async def insert_schedule(
        self,
        *,
        schedule_id: UUID,
        block_id: UUID,
        scheduled_for: date_type,
        recommended_mm: Decimal,
        kc_used: Decimal | None,
        et0_mm_used: Decimal | None,
        recent_precip_mm: Decimal | None,
        growth_stage_context: str | None,
        actor_user_id: UUID | None,
    ) -> bool:
        """Insert a new pending recommendation. Returns False when the
        partial UNIQUE on ``(block_id, scheduled_for) WHERE
        status='pending'`` blocks it — re-runs of the daily Beat sweep
        are no-ops on already-pending rows."""
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO irrigation_schedules (
                        id, block_id, scheduled_for, recommended_mm,
                        kc_used, et0_mm_used, recent_precip_mm,
                        growth_stage_context, status,
                        created_by, updated_by
                    ) VALUES (
                        :id, :block_id, :scheduled_for, :recommended_mm,
                        :kc_used, :et0_mm_used, :recent_precip_mm,
                        :stage_ctx, 'pending',
                        :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": schedule_id,
                    "block_id": block_id,
                    "scheduled_for": scheduled_for,
                    "recommended_mm": recommended_mm,
                    "kc_used": kc_used,
                    "et0_mm_used": et0_mm_used,
                    "recent_precip_mm": recent_precip_mm,
                    "stage_ctx": growth_stage_context,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if "uq_irrigation_schedules_block_date_pending" in str(exc):
                return False
            raise
        await self._tenant.flush()
        return True

    async def get_schedule(self, *, schedule_id: UUID) -> dict[str, Any] | None:
        stmt = select(IrrigationSchedule).where(
            IrrigationSchedule.id == schedule_id,
            IrrigationSchedule.deleted_at.is_(None),
        )
        row = (await self._tenant.execute(stmt)).scalars().one_or_none()
        return _schedule_to_dict(row) if row is not None else None

    async def list_for_farm(
        self,
        *,
        farm_id: UUID,
        from_date: date_type | None,
        to_date: date_type | None,
        status_filter: tuple[str, ...] = (),
        limit: int = 200,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["b.farm_id = :farm_id", "i.deleted_at IS NULL"]
        params: dict[str, Any] = {"farm_id": farm_id, "limit": limit}
        if from_date is not None:
            clauses.append("i.scheduled_for >= :from_date")
            params["from_date"] = from_date
        if to_date is not None:
            clauses.append("i.scheduled_for < :to_date")
            params["to_date"] = to_date
        if status_filter:
            clauses.append("i.status = ANY(:statuses)")
            params["statuses"] = list(status_filter)
        # Static SQL literals only — `clauses` are picked from a closed
        # set above, no caller input is interpolated. Bind parameters
        # carry the values.
        where_sql = " AND ".join(clauses)
        sql = (
            "SELECT i.id, i.block_id, i.scheduled_for, i.recommended_mm, "
            "       i.kc_used, i.et0_mm_used, i.recent_precip_mm, "
            "       i.growth_stage_context, i.soil_moisture_pct, i.status, "
            "       i.applied_at, i.applied_by, i.applied_volume_mm, "
            "       i.notes, i.created_at, i.updated_at "
            "FROM irrigation_schedules i "
            "JOIN blocks b ON b.id = i.block_id "
            "WHERE " + where_sql + " "
            "ORDER BY i.scheduled_for DESC, i.id DESC "
            "LIMIT :limit"
        )
        stmt = text(sql).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return tuple(dict(r) for r in rows)

    async def transition_schedule(
        self,
        *,
        schedule_id: UUID,
        action: str,
        applied_volume_mm: Decimal | None,
        notes: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Apply or skip a pending schedule. Returns the updated row.

        Raises `InvalidIrrigationTransitionError` if the row isn't
        pending. Applied rows record the actual delivered volume.
        """
        before = await self.get_schedule(schedule_id=schedule_id)
        if before is None:
            from app.modules.irrigation.errors import (
                IrrigationScheduleNotFoundError,
            )

            raise IrrigationScheduleNotFoundError(schedule_id)
        if before["status"] != "pending":
            raise InvalidIrrigationTransitionError(current_status=before["status"], action=action)

        if action == "apply":
            new_status = "applied"
            values: dict[str, Any] = {
                "status": new_status,
                "applied_at": datetime.now(_utc()),
                "applied_by": actor_user_id,
                "applied_volume_mm": applied_volume_mm,
                "updated_by": actor_user_id,
            }
        elif action == "skip":
            new_status = "skipped"
            values = {
                "status": new_status,
                "updated_by": actor_user_id,
            }
        else:
            raise InvalidIrrigationTransitionError(current_status=before["status"], action=action)
        if notes is not None:
            values["notes"] = notes

        await self._tenant.execute(
            update(IrrigationSchedule).where(IrrigationSchedule.id == schedule_id).values(**values)
        )
        after = await self.get_schedule(schedule_id=schedule_id)
        if after is None:
            from app.modules.irrigation.errors import (
                IrrigationScheduleNotFoundError,
            )

            raise IrrigationScheduleNotFoundError(schedule_id)
        return after

    async def list_active_block_ids(self) -> tuple[UUID, ...]:
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM blocks "
                    "WHERE deleted_at IS NULL "
                    "AND status NOT IN ('archived', 'abandoned')"
                )
            )
        ).all()
        return tuple(r.id for r in rows)


def _utc() -> Any:
    from datetime import UTC

    return UTC


def _schedule_to_dict(row: IrrigationSchedule) -> dict[str, Any]:
    return {
        "id": row.id,
        "block_id": row.block_id,
        "scheduled_for": row.scheduled_for,
        "recommended_mm": row.recommended_mm,
        "kc_used": row.kc_used,
        "et0_mm_used": row.et0_mm_used,
        "recent_precip_mm": row.recent_precip_mm,
        "growth_stage_context": row.growth_stage_context,
        "soil_moisture_pct": row.soil_moisture_pct,
        "status": row.status,
        "applied_at": row.applied_at,
        "applied_by": row.applied_by,
        "applied_volume_mm": row.applied_volume_mm,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
