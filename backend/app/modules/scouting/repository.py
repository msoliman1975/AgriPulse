"""Async DB access for scouting. Internal to the module.

Both tables are tenant-scoped, so the caller binds the session to the right
schema via `SET LOCAL search_path` before calling in — the same contract every
other tenant module uses.

Reads go through raw SQL rather than the ORM for one reason: `pin_point` is a
PostGIS geometry and has to be rendered as GeoJSON on the way out, the same way
`signal_observations.location_point` is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Every column the API returns. `pin_point` is rendered, not selected raw.
_VISIT_COLUMNS = """
    id, farm_id, block_id, cell_id, origin,
    recommendation_id, alert_id, schedule_id,
    title, instruction, reason_snapshot,
    CASE WHEN pin_point IS NULL THEN NULL
         ELSE ST_AsGeoJSON(pin_point)::jsonb END AS pin_point,
    severity, priority, due_by, status, outcome,
    assigned_to, assigned_by, assigned_at, accepted_at, started_at,
    completed_at, completed_by, decline_reason,
    template_id, observation_group_id, summary_note,
    created_at, updated_at
"""


class ScoutingRepository:
    """Internal repository — the service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Visits ------------------------------------------------------------

    async def list_visits(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        assigned_to: UUID | None = None,
        statuses: tuple[str, ...] = (),
        claimable: bool = False,
        limit: int = 200,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        binds: list[Any] = []
        if farm_id is not None:
            clauses.append("farm_id = :farm_id")
            params["farm_id"] = farm_id
            binds.append(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        if block_id is not None:
            clauses.append("block_id = :block_id")
            params["block_id"] = block_id
            binds.append(bindparam("block_id", type_=PG_UUID(as_uuid=True)))
        if assigned_to is not None:
            clauses.append("assigned_to = :assigned_to")
            params["assigned_to"] = assigned_to
            binds.append(bindparam("assigned_to", type_=PG_UUID(as_uuid=True)))
        if claimable:
            # Work nobody has taken. Kept as its own bucket so a scout never
            # assumes a colleague already has it.
            clauses.append("assigned_to IS NULL AND status = 'queued'")
        if statuses:
            clauses.append("status = ANY(:statuses)")
            params["statuses"] = list(statuses)

        # Overdue first, then by deadline: a warning due in two hours outranks
        # a critical due tomorrow, and severity alone would invert that.
        sql = (
            f"SELECT {_VISIT_COLUMNS} FROM scouting_visits "  # noqa: S608
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY (due_by IS NULL), due_by ASC, "
            "  CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END "
            "LIMIT :limit"
        )
        stmt = text(sql)
        if binds:
            stmt = stmt.bindparams(*binds)
        rows = (await self._session.execute(stmt, params)).mappings().all()
        return tuple(dict(r) for r in rows)

    async def get_visit(self, *, visit_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        f"SELECT {_VISIT_COLUMNS} FROM scouting_visits "  # noqa: S608
                        "WHERE id = :id AND deleted_at IS NULL"
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": visit_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def find_by_idempotency_key(self, *, key: str) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        f"SELECT {_VISIT_COLUMNS} FROM scouting_visits "  # noqa: S608
                        "WHERE idempotency_key = :key"
                    ),
                    {"key": key},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def insert_visit(self, *, values: dict[str, Any]) -> dict[str, Any]:
        """Insert a visit. `lat`/`lon`, when present, become `pin_point`."""
        lat = values.pop("lat", None)
        lon = values.pop("lon", None)
        cols = list(values.keys())
        placeholders = [f":{c}" for c in cols]
        if lat is not None and lon is not None:
            cols.append("pin_point")
            placeholders.append("ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)")
            values["lat"] = lat
            values["lon"] = lon
        uuid_binds = [
            bindparam(c, type_=PG_UUID(as_uuid=True))
            for c in cols
            if c.endswith("_id") or c in {"assigned_to", "assigned_by", "created_by"}
        ]
        stmt = text(
            f"INSERT INTO scouting_visits ({', '.join(cols)}) "  # noqa: S608 - static column list
            f"VALUES ({', '.join(placeholders)}) RETURNING id"
        )
        if uuid_binds:
            stmt = stmt.bindparams(*uuid_binds)
        new_id = (await self._session.execute(stmt, values)).scalar_one()
        await self._session.flush()
        out = await self.get_visit(visit_id=new_id)
        if out is None:  # pragma: no cover - insert just succeeded
            raise RuntimeError("Visit insert succeeded but row is missing")
        return out

    async def apply_transition(
        self,
        *,
        visit_id: UUID,
        sets: dict[str, Any],
        expected_statuses: tuple[str, ...],
    ) -> dict[str, Any] | None:
        """Move a visit, but only from a state we expect.

        The status guard lives in the UPDATE rather than in a read-then-write so
        two scouts tapping "I'll take it" at the same moment cannot both win —
        the second one's rowcount is 0 and the service raises 409.
        """
        assignments = ", ".join(f"{k} = :{k}" for k in sets)
        params: dict[str, Any] = {**sets, "id": visit_id, "expected": list(expected_statuses)}
        result = await self._session.execute(
            text(
                f"UPDATE scouting_visits SET {assignments} "  # noqa: S608 - keys are service-controlled
                "WHERE id = :id AND deleted_at IS NULL AND status = ANY(:expected)"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            params,
        )
        if not (getattr(result, "rowcount", 0) or 0):
            return None
        return await self.get_visit(visit_id=visit_id)

    async def sweep_overdue(self, *, now: datetime) -> int:
        """Flag visits past their deadline.

        `expired` is a flag, not a closure — the row stays actionable and keeps
        its place at the top of the list. Auto-closing overdue work would make
        a neglected farm look exactly like a healthy one.
        """
        result = await self._session.execute(
            text(
                "UPDATE scouting_visits SET status = 'expired', updated_at = now() "
                "WHERE deleted_at IS NULL AND due_by IS NOT NULL AND due_by < :now "
                "AND status IN ('queued', 'assigned', 'accepted', 'in_progress')"
            ),
            {"now": now},
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ---- Routing rules -----------------------------------------------------

    async def list_rules(self, *, farm_id: UUID | None = None) -> tuple[dict[str, Any], ...]:
        clauses = ["deleted_at IS NULL"]
        params: dict[str, Any] = {}
        if farm_id is not None:
            # Tenant-wide rules (farm_id IS NULL) apply to this farm too, so
            # they belong in the same list a supervisor is editing.
            clauses.append("(farm_id = :farm_id OR farm_id IS NULL)")
            params["farm_id"] = farm_id
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM scouting_routing_rules "  # noqa: S608 - static clauses
                        f"WHERE {' AND '.join(clauses)} "
                        "ORDER BY farm_id NULLS LAST, block_id NULLS LAST, origin NULLS LAST"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def resolve_rule(
        self, *, farm_id: UUID, block_id: UUID, origin: str
    ) -> dict[str, Any] | None:
        """Most-specific-first: block → farm → tenant-wide.

        An origin-specific rule beats an origin-agnostic one at the same scope,
        so a farm can route `alert` automatically while still triaging
        `routine`.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT * FROM scouting_routing_rules
                         WHERE deleted_at IS NULL AND is_active
                           AND (block_id = :block_id OR block_id IS NULL)
                           AND (farm_id = :farm_id OR farm_id IS NULL)
                           AND (origin = :origin OR origin IS NULL)
                         ORDER BY (block_id IS NULL), (farm_id IS NULL), (origin IS NULL)
                         LIMIT 1
                        """
                    ).bindparams(
                        bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"farm_id": farm_id, "block_id": block_id, "origin": origin},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def upsert_rule(self, *, values: dict[str, Any]) -> dict[str, Any]:
        cols = list(values.keys())
        row = (
            (
                await self._session.execute(
                    text(
                        f"INSERT INTO scouting_routing_rules ({', '.join(cols)}) "  # noqa: S608
                        f"VALUES ({', '.join(':' + c for c in cols)}) "
                        "ON CONFLICT (farm_id, block_id, origin) "
                        "WHERE deleted_at IS NULL DO UPDATE SET "
                        + ", ".join(
                            f"{c} = EXCLUDED.{c}"
                            for c in cols
                            if c not in {"farm_id", "block_id", "origin"}
                        )
                        + ", updated_at = now() RETURNING *"
                    ),
                    values,
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
