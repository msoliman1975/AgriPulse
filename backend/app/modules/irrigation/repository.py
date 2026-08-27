"""Async DB access for the irrigation module. Internal."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, bindparam, select, text, update
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
                           bc.crop_id, bc.crop_variety_id,
                           bc.crop_variety_strain_id, bc.growth_stage
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

        out["strain_phenology_override"] = None
        if out.get("crop_variety_strain_id") is not None:
            s_row = (
                (
                    await self._public.execute(
                        text(
                            """
                        SELECT phenology_stages_override
                        FROM public.crop_variety_strains
                        WHERE id = :id AND is_active = TRUE
                        """
                        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                        {"id": out["crop_variety_strain_id"]},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if s_row is not None:
                out["strain_phenology_override"] = s_row["phenology_stages_override"]
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

    async def farm_for_block(self, *, block_id: UUID) -> UUID | None:
        """Which farm this block belongs to, for the per-farm capability check.

        Deliberately not `get_block_context`, which returns None for a block
        with no current crop assignment. Authorization must not depend on
        whether a crop happens to be planted: a block with no crop would come
        back unauthorized rather than empty.
        """
        return (
            await self._tenant.execute(
                text("SELECT farm_id FROM blocks WHERE id = :b AND deleted_at IS NULL").bindparams(
                    bindparam("b", type_=PG_UUID(as_uuid=True))
                ),
                {"b": block_id},
            )
        ).scalar_one_or_none()

    async def farm_for_schedule(self, *, schedule_id: UUID) -> UUID | None:
        """The farm behind a schedule id. Schedules are keyed on a block only."""
        return (
            await self._tenant.execute(
                text(
                    "SELECT b.farm_id FROM irrigation_schedules i "
                    "  JOIN blocks b ON b.id = i.block_id "
                    " WHERE i.id = :s AND i.deleted_at IS NULL AND b.deleted_at IS NULL"
                ).bindparams(bindparam("s", type_=PG_UUID(as_uuid=True))),
                {"s": schedule_id},
            )
        ).scalar_one_or_none()

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

    # ---- Daily water balance (gap-audit D7) ---------------------------
    #
    # Deliberately set-based rather than looping `get_block_context` per
    # block. That helper issues up to four queries for one block, which is
    # fine for a single on-demand recommendation and quietly quadratic for a
    # sweep over every block in a tenant — the shape that caused the map N+1
    # and pool-exhaustion incident. These run a fixed number of queries no
    # matter how many blocks a tenant has.

    async def load_water_balance_blocks(self, *, target_date: date_type) -> list[dict[str, Any]]:
        """Every active block with a current crop, plus that day's ET0/precip.

        Blocks with no current crop are excluded by the join: without a crop
        there is no Kc, and an ETc computed on the generic fallback for a
        block we know to be fallow would be a fabricated demand figure.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT b.id            AS block_id,
                           b.farm_id       AS farm_id,
                           bc.crop_id      AS crop_id,
                           bc.crop_variety_id,
                           bc.crop_variety_strain_id,
                           bc.growth_stage AS growth_stage,
                           wd.et0_mm_daily AS et0_mm,
                           wd.precip_mm_daily AS precip_mm,
                           COALESCE(irr.applied_mm, NULL) AS irrigation_mm
                      FROM blocks b
                      JOIN block_crops bc
                        ON bc.block_id = b.id
                       AND bc.is_current = TRUE
                       AND bc.deleted_at IS NULL
                      JOIN weather_derived_daily wd
                        ON wd.farm_id = b.farm_id
                       AND wd.date = :d
                      LEFT JOIN (
                            SELECT s.block_id, SUM(s.applied_volume_mm) AS applied_mm
                              FROM irrigation_schedules s
                             WHERE s.scheduled_for = :d
                               AND s.status = 'applied'
                               AND s.applied_volume_mm IS NOT NULL
                             GROUP BY s.block_id
                           ) irr ON irr.block_id = b.id
                     WHERE b.deleted_at IS NULL
                       -- `blocks` has no `status` column. Liveness is the
                       -- active window (tenant migration 0026, and the note
                       -- on farms.models.Block): this query used to say
                       -- `b.status NOT IN ('archived','abandoned')` and so
                       -- raised UndefinedColumn on every run, for every
                       -- tenant, silently.
                       AND b.active_from <= :d
                       AND (b.active_to IS NULL OR b.active_to > :d)
                       AND wd.et0_mm_daily IS NOT NULL
                    """
                    ),
                    {"d": target_date},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def load_phenology_by_crop_ids(
        self,
        *,
        crop_ids: set[UUID],
        variety_ids: set[UUID],
        strain_ids: set[UUID],
    ) -> dict[str, dict[UUID, Any]]:
        """Phenology docs for the catalog rows the sweep's blocks reference.

        Three queries for the whole tenant rather than three per block. Empty
        id sets skip their query entirely — `IN ()` is a syntax error, and a
        tenant growing one crop should not pay for the other two lookups.
        """
        out: dict[str, dict[UUID, Any]] = {"crop": {}, "variety": {}, "strain": {}}

        async def _load(key: str, table: str, column: str, ids: set[UUID]) -> None:
            if not ids:
                return
            rows = (
                (
                    await self._public.execute(
                        text(
                            f"SELECT id, {column} AS doc FROM public.{table} "  # noqa: S608
                            "WHERE id = ANY(:ids) AND is_active = TRUE"
                        ).bindparams(bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
                        {"ids": list(ids)},
                    )
                )
                .mappings()
                .all()
            )
            out[key] = {r["id"]: r["doc"] for r in rows}

        # `table`/`column` are module-local literals, never caller input, so
        # the f-string above cannot carry untrusted SQL.
        await _load("crop", "crops", "phenology_stages", crop_ids)
        await _load("variety", "crop_varieties", "phenology_stages_override", variety_ids)
        await _load("strain", "crop_variety_strains", "phenology_stages_override", strain_ids)
        return out

    async def upsert_water_balance_rows(self, rows: list[dict[str, Any]]) -> int:
        """Write one day's balances. Idempotent on (block_id, date).

        Recomputed wholesale rather than merged: a re-run after a late
        irrigation log should replace the row, not add to it.
        """
        if not rows:
            return 0
        await self._tenant.execute(
            text(
                """
                INSERT INTO block_water_balance_daily (
                    block_id, date, balance_mm, etc_mm, et0_mm,
                    kc_used, kc_source, growth_stage,
                    precip_mm, irrigation_mm, irrigation_logged, computed_at
                ) VALUES (
                    :block_id, :date, :balance_mm, :etc_mm, :et0_mm,
                    :kc_used, :kc_source, :growth_stage,
                    :precip_mm, :irrigation_mm, :irrigation_logged, now()
                )
                ON CONFLICT (block_id, date) DO UPDATE SET
                    balance_mm = EXCLUDED.balance_mm,
                    etc_mm = EXCLUDED.etc_mm,
                    et0_mm = EXCLUDED.et0_mm,
                    kc_used = EXCLUDED.kc_used,
                    kc_source = EXCLUDED.kc_source,
                    growth_stage = EXCLUDED.growth_stage,
                    precip_mm = EXCLUDED.precip_mm,
                    irrigation_mm = EXCLUDED.irrigation_mm,
                    irrigation_logged = EXCLUDED.irrigation_logged,
                    computed_at = now()
                """
            ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
            rows,
        )
        return len(rows)

    async def list_water_balance_for_block(
        self, *, block_id: UUID, from_date: date_type, to_date: date_type
    ) -> list[dict[str, Any]]:
        """One block's water-balance rows over a window, oldest first.

        Ascending so the caller can chart it without re-sorting; the dock reads
        the last element for "latest" rather than issuing a second query.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT date, balance_mm, etc_mm, et0_mm, kc_used, kc_source,
                           growth_stage, precip_mm, irrigation_mm, irrigation_logged
                      FROM block_water_balance_daily
                     WHERE block_id = :block_id
                       AND date BETWEEN :from_date AND :to_date
                     ORDER BY date
                    """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id, "from_date": from_date, "to_date": to_date},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def list_active_block_ids(self) -> tuple[UUID, ...]:
        """Blocks that are live today.

        `blocks` has no `status` column. Liveness is the active window
        (tenant migration 0026, and the note on `farms.models.Block`). This
        query used to say `status NOT IN ('archived','abandoned')`, so
        `irrigation.generate_for_tenant` raised UndefinedColumn on every run
        for every tenant. Its sibling in `water_balance_for_tenant` was
        fixed earlier and this one was missed; the predicate below matches
        `recommendations.repository.list_active_block_ids`.
        """
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM blocks "
                    "WHERE deleted_at IS NULL "
                    "  AND active_from <= current_date "
                    "  AND (active_to IS NULL OR active_to > current_date)"
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
