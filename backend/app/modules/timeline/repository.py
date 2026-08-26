"""Reads for the farm timeline. Internal to the module.

Raw SQL rather than the ORM, for the same reason field_flags and scouting
use it: three of these tables hold PostGIS geometry that has to leave as
GeoJSON, and one (signal_observations) is a hypertable whose identity is
(time, id).

Two rules every query here follows, both of them scar tissue:

* Every bind is a real ``UUID`` / ``datetime`` object, declared with a
  typed ``bindparam``. A ``CAST(:x AS uuid)`` against a string bind has
  taken this platform down more than once.
* The calendar day is ``(col AT TIME ZONE 'UTC')::date``, never a bare
  cast. ``::date`` on a timestamptz follows the session TimeZone, so two
  pods with different settings would bucket the same row on different
  days.

Scope note: ``alerts`` carries no ``farm_id``, so its farm is resolved
through ``blocks``. That is the farm-path read this codebase has been
bitten by — on a farm cut over to farm-AOI fetching the block table stops
gaining rows. It is still correct here: the timeline asks "what happened
on the blocks this farm has", and a block that is gone has no events to
replay.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import DateTime

# Per-kind row cap. Seven kinds times 2000 is the worst case one response
# can carry; a 90-day window on the reference farm returns ~1200 rows in
# total. Hitting the cap sets ``truncated`` — the screen says so rather
# than rendering a partial day as if it were the whole day.
ROW_CAP = 2000


def _binds() -> list[Any]:
    return [
        bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
        bindparam("from_ts", type_=DateTime(timezone=True)),
        bindparam("to_ts", type_=DateTime(timezone=True)),
    ]


def _day(col: str) -> str:
    """The UTC calendar day of a timestamptz column, as ``day``."""
    return f"({col} AT TIME ZONE 'UTC')::date AS day"


class TimelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _run(self, sql: str, params: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        stmt = text(sql).bindparams(*_binds())
        rows = (await self._session.execute(stmt, params)).mappings()
        return tuple(dict(r) for r in rows)

    # ---- Flags raised by a scout -------------------------------------------

    async def flags(self, **p: Any) -> tuple[dict[str, Any], ...]:
        sql = f"""
            SELECT f.id::text AS id, f.created_at AS at, {_day("f.created_at")},
                   f.block_id, b.name AS block_name, b.code AS block_code,
                   f.severity, f.note, f.status,
                   CASE WHEN f.point IS NULL THEN NULL
                        ELSE ST_AsGeoJSON(f.point)::jsonb END AS point
            FROM field_flags f
            JOIN blocks b ON b.id = f.block_id
            WHERE f.farm_id = :farm_id
              AND f.created_at >= :from_ts AND f.created_at < :to_ts
              AND (:block_id IS NULL OR f.block_id = :block_id)
            ORDER BY f.created_at
            LIMIT {ROW_CAP}
        """  # every value is a bind; only the row cap is inlined.
        return await self._run(sql, p)

    # ---- Custom signals recorded -------------------------------------------

    async def signals(self, **p: Any) -> tuple[dict[str, Any], ...]:
        # signal_definitions is a PUBLIC table (two-tier catalog) and the
        # session search_path is "tenant_x, public". Qualified anyway, so a
        # tenant table of the same name could never shadow it.
        #
        # The value is coalesced across the value columns in the order a
        # definition's value_kind would pick, so the rail shows the reading
        # rather than only "an observation happened".
        sql = f"""
            SELECT o.id::text AS id, o.time AS at, {_day("o.time")},
                   o.block_id, b.name AS block_name, b.code AS block_code,
                   d.code AS code, d.name AS definition_name, d.unit AS unit,
                   COALESCE(
                       o.value_categorical,
                       o.value_event,
                       o.value_numeric::text,
                       CASE WHEN o.value_boolean IS NULL THEN NULL
                            WHEN o.value_boolean THEN 'true' ELSE 'false' END
                   ) AS value_text,
                   o.notes,
                   CASE WHEN o.location_point IS NULL THEN NULL
                        ELSE ST_AsGeoJSON(o.location_point)::jsonb END AS point
            FROM signal_observations o
            LEFT JOIN blocks b ON b.id = o.block_id
            LEFT JOIN public.signal_definitions d ON d.id = o.signal_definition_id
            WHERE o.farm_id = :farm_id
              AND o.time >= :from_ts AND o.time < :to_ts
              AND (:block_id IS NULL OR o.block_id = :block_id)
            ORDER BY o.time
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Plan activities marked completed ----------------------------------

    async def activities(self, **p: Any) -> tuple[dict[str, Any], ...]:
        # Bucketed on completed_at, not scheduled_date. The replay records
        # what happened, and an activity scheduled for Tuesday and done on
        # Friday belongs on Friday. status = 'completed' alone is not
        # enough: some rows carry the status with a NULL timestamp, and
        # those have no day to sit on.
        sql = f"""
            SELECT a.id::text AS id, a.completed_at AS at, {_day("a.completed_at")},
                   a.block_id, b.name AS block_name, b.code AS block_code,
                   a.activity_type AS code, a.product_name, a.dosage, a.notes,
                   a.anchored_stage_code
            FROM plan_activities a
            JOIN blocks b ON b.id = a.block_id
            WHERE a.farm_id = :farm_id
              AND a.status = 'completed'
              AND a.completed_at IS NOT NULL
              AND a.completed_at >= :from_ts AND a.completed_at < :to_ts
              AND (:block_id IS NULL OR a.block_id = :block_id)
            ORDER BY a.completed_at
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Scouting visits (the observation) ---------------------------------

    async def visits(self, **p: Any) -> tuple[dict[str, Any], ...]:
        sql = f"""
            SELECT v.id::text AS id, v.completed_at AS at, {_day("v.completed_at")},
                   v.block_id, b.name AS block_name, b.code AS block_code,
                   v.title, v.summary_note, v.severity, v.outcome,
                   v.origin AS code,
                   CASE WHEN v.pin_point IS NULL THEN NULL
                        ELSE ST_AsGeoJSON(v.pin_point)::jsonb END AS point
            FROM scouting_visits v
            JOIN blocks b ON b.id = v.block_id
            WHERE v.farm_id = :farm_id
              AND v.completed_at IS NOT NULL
              AND v.completed_at >= :from_ts AND v.completed_at < :to_ts
              AND (:block_id IS NULL OR v.block_id = :block_id)
            ORDER BY v.completed_at
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Alerts ------------------------------------------------------------

    async def alerts(self, **p: Any) -> tuple[dict[str, Any], ...]:
        sql = f"""
            SELECT a.id::text AS id, a.created_at AS at, {_day("a.created_at")},
                   a.block_id, b.name AS block_name, b.code AS block_code,
                   a.rule_code, a.action_type AS code, a.severity,
                   a.diagnosis_en, a.diagnosis_ar
            FROM alerts a
            JOIN blocks b ON b.id = a.block_id
            WHERE b.farm_id = :farm_id
              AND a.created_at >= :from_ts AND a.created_at < :to_ts
              AND (:block_id IS NULL OR a.block_id = :block_id)
            ORDER BY a.created_at
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Recommendations ---------------------------------------------------

    async def recommendations(self, **p: Any) -> tuple[dict[str, Any], ...]:
        sql = f"""
            SELECT r.id::text AS id, r.created_at AS at, {_day("r.created_at")},
                   r.block_id, b.name AS block_name, b.code AS block_code,
                   r.action_type AS code, r.severity, r.text_en, r.text_ar,
                   r.tree_code
            FROM recommendations r
            JOIN blocks b ON b.id = r.block_id
            WHERE r.farm_id = :farm_id
              AND r.created_at >= :from_ts AND r.created_at < :to_ts
              AND (:block_id IS NULL OR r.block_id = :block_id)
            ORDER BY r.created_at
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Phenology stage transitions (block scope only) --------------------

    async def stages(self, **p: Any) -> tuple[dict[str, Any], ...]:
        # Only ever called with a block_id. growth_stage_logs has no
        # farm_id and, more to the point, a farm-wide stage row would be
        # untrue about every block running a different plan.
        sql = f"""
            SELECT g.id::text AS id, g.transition_date AS at,
                   {_day("g.transition_date")},
                   g.block_id, b.name AS block_name, b.code AS block_code,
                   g.stage AS code, g.source, g.notes
            FROM growth_stage_logs g
            JOIN blocks b ON b.id = g.block_id
            WHERE b.farm_id = :farm_id
              AND g.block_id = :block_id
              AND g.transition_date >= :from_ts AND g.transition_date < :to_ts
            ORDER BY g.transition_date
            LIMIT {ROW_CAP}
        """
        return await self._run(sql, p)

    # ---- Existence check ---------------------------------------------------

    async def block_belongs_to_farm(self, *, farm_id: UUID, block_id: UUID) -> bool:
        """Whether the block is on the farm the URL names.

        The capability check gates on ``farm_id``, so without this a block
        id from another farm would be read through a farm the caller does
        have — the same hole ``update_farm_subscription`` closes by hand.
        """
        stmt = text("SELECT 1 FROM blocks WHERE id = :block_id AND farm_id = :farm_id").bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
        )
        row = (
            await self._session.execute(stmt, {"block_id": block_id, "farm_id": farm_id})
        ).first()
        return row is not None


def get_timeline_repository(session: AsyncSession) -> TimelineRepository:
    return TimelineRepository(session)
