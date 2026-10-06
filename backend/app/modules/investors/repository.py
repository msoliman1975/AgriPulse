"""Async DB access for investors, holdings, and ownership. Internal.

All three tables are tenant-scoped; the caller's session already has
``search_path`` set to the tenant schema.

Raw SQL rather than the ORM, as in field_flags and scouting: holdings are
PostGIS polygons that leave as GeoJSON, and the share is a PostGIS area
ratio. Every bind is a real UUID or date object, never a string cast in SQL.

"Today" is ``public.app_now()::date`` everywhere, so a demo-history replay
sees the ownership that was current on its replayed day.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.investors.errors import (
    BlockHasHoldingsError,
    HoldingOutsideBlockError,
    HoldingOverlapError,
    InvestorConflictError,
    OwnershipConflictError,
)

_UUID = PG_UUID(as_uuid=True)
_TODAY = "(public.app_now())::date"

# Writable investor columns. The router validates values; this list is the
# second guard on which columns an UPDATE may name.
INVESTOR_WRITABLE = (
    "investor_type",
    "full_name",
    "full_name_ar",
    "contact_person",
    "email",
    "phone",
    "national_id_type",
    "national_id_last4",
    "nationality",
    "country",
    "city",
    "preferred_language",
    "relationship_manager_id",
    "notes_internal",
    "status",
    "archived_at",
    "user_id",
    "invited_at",
    "last_app_seen_at",
)
HOLDING_WRITABLE = ("name", "name_ar", "tree_count", "status", "notes_internal", "archived_at")

_CURRENT_OWNERSHIP = f"""
    o.deleted_at IS NULL
    AND o.start_date <= {_TODAY}
    AND (o.end_date IS NULL OR o.end_date >= {_TODAY})
"""

_INVESTOR_COLUMNS = """
    i.id, i.code, i.investor_type, i.full_name, i.full_name_ar,
    i.contact_person, i.email, i.phone, i.national_id_type,
    i.national_id_last4, i.nationality, i.country, i.city,
    i.preferred_language, i.user_id, i.status, i.relationship_manager_id,
    i.notes_internal, i.invited_at, i.last_app_seen_at, i.archived_at,
    i.created_at, i.updated_at,
    coalesce(cur.n, 0) AS current_holdings_count,
    coalesce(cur.area, 0) AS current_area_m2
"""

_INVESTOR_FROM = f"""
    investors i
    LEFT JOIN LATERAL (
        SELECT count(*)::int AS n, sum(h.area_m2) AS area
          FROM holding_ownerships o
          JOIN holdings h ON h.id = o.holding_id AND h.deleted_at IS NULL
         WHERE o.investor_id = i.id AND {_CURRENT_OWNERSHIP}
    ) cur ON true
"""

_HOLDING_COLUMNS = """
    h.id, h.code, b.farm_id, f.name AS farm_name, f.name_ar AS farm_name_ar,
    h.block_id, b.code AS block_code, b.name AS block_name,
    b.name_ar AS block_name_ar,
    h.name, h.name_ar, ST_AsGeoJSON(h.boundary)::jsonb AS boundary,
    h.area_m2,
    round(ST_Area(b.boundary_utm)::numeric, 2) AS block_area_m2,
    round(h.area_m2 * 100 / NULLIF(ST_Area(b.boundary_utm)::numeric, 0), 2) AS share_pct,
    h.tree_count, h.status, h.notes_internal, h.archived_at,
    h.created_at, h.updated_at,
    cur.id AS current_ownership_id, cur.investor_id AS current_investor_id,
    cur.start_date AS current_since,
    ci.code AS current_investor_code, ci.full_name AS current_investor_name,
    ci.full_name_ar AS current_investor_name_ar
"""

_HOLDING_FROM = f"""
    holdings h
    JOIN blocks b ON b.id = h.block_id
    JOIN farms f ON f.id = b.farm_id
    LEFT JOIN LATERAL (
        SELECT o.id, o.investor_id, o.start_date
          FROM holding_ownerships o
         WHERE o.holding_id = h.id AND {_CURRENT_OWNERSHIP}
         ORDER BY o.start_date DESC
         LIMIT 1
    ) cur ON true
    LEFT JOIN investors ci ON ci.id = cur.investor_id
"""

_OWNERSHIP_COLUMNS = f"""
    o.id, o.holding_id, h.code AS holding_code, h.name AS holding_name,
    h.name_ar AS holding_name_ar, b.farm_id, f.name AS farm_name,
    f.name_ar AS farm_name_ar, h.block_id, b.code AS block_code,
    o.investor_id, i.code AS investor_code, i.full_name AS investor_name,
    i.full_name_ar AS investor_name_ar,
    o.start_date, o.end_date, o.acquired_by, o.ended_by, o.contract_ref,
    CASE
      WHEN o.end_date IS NOT NULL AND o.end_date < {_TODAY} THEN 'past'
      WHEN o.start_date > {_TODAY} THEN 'future'
      ELSE 'current'
    END AS period,
    h.area_m2, o.created_at
"""

_OWNERSHIP_FROM = """
    holding_ownerships o
    JOIN holdings h ON h.id = o.holding_id
    JOIN blocks b ON b.id = h.block_id
    JOIN farms f ON f.id = b.farm_id
    JOIN investors i ON i.id = o.investor_id
"""


def _map_db_error(exc: DBAPIError) -> None:
    """Turn a known constraint or trigger failure into a domain error.

    Returns normally when the failure is not one of ours, so the caller
    re-raises the original.
    """
    msg = str(exc.orig) if exc.orig is not None else str(exc)
    if "holding_outside_block" in msg:
        raise HoldingOutsideBlockError() from exc
    if "holding_overlaps_holding" in msg:
        raise HoldingOverlapError() from exc
    if "block_boundary_cuts_holding" in msg:
        raise BlockHasHoldingsError(
            "The new block boundary leaves a holding outside the block.",
            holding_codes=[],
        ) from exc
    if "ex_holding_ownerships_no_overlap" in msg:
        raise OwnershipConflictError("These dates overlap another owner of this holding.") from exc
    if "uq_investors_email_live" in msg:
        raise InvestorConflictError("Another investor already uses this email.") from exc
    if "uq_investors_code_live" in msg:
        raise InvestorConflictError("Another investor already uses this code.") from exc


class InvestorsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rows(
        self, sql: str, params: dict[str, Any], uuid_params: tuple[str, ...] = ()
    ) -> list[dict[str, Any]]:
        stmt = text(sql)
        if uuid_params:
            stmt = stmt.bindparams(*(bindparam(p, type_=_UUID) for p in uuid_params))
        result = await self._session.execute(stmt, params)
        return [dict(r) for r in result.mappings()]

    async def _write(
        self, sql: str, params: dict[str, Any], uuid_params: tuple[str, ...] = ()
    ) -> None:
        """Run an INSERT or UPDATE. No write here uses RETURNING, so no rows
        are read: reading a closed result raises ResourceClosedError."""
        stmt = text(sql)
        if uuid_params:
            stmt = stmt.bindparams(*(bindparam(p, type_=_UUID) for p in uuid_params))
        try:
            await self._session.execute(stmt, params)
        except DBAPIError as exc:
            _map_db_error(exc)
            raise

    # ---- Codes ------------------------------------------------------------

    async def next_code(self, *, table: str, prefix: str) -> str:
        """Next free ``PREFIX-NNNN``. Serialised by a transaction lock."""
        assert table in ("investors", "holdings")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"{table}_code"},
        )
        row = (
            await self._session.execute(
                text(
                    f"SELECT max(substring(code FROM '^{prefix}-([0-9]+)$')::int) AS n "
                    f"FROM {table}"
                )
            )
        ).first()
        n = (row[0] if row and row[0] is not None else 0) + 1
        return f"{prefix}-{n:04d}"

    async def holding_code_taken(self, *, code: str) -> bool:
        rows = await self._rows(
            "SELECT 1 FROM holdings WHERE code = :code AND deleted_at IS NULL", {"code": code}
        )
        return bool(rows)

    # ---- Investors --------------------------------------------------------

    async def list_investors(
        self, *, status: str | None, query: str | None, include_archived: bool
    ) -> list[dict[str, Any]]:
        clauses = ["i.deleted_at IS NULL"]
        params: dict[str, Any] = {}
        if not include_archived:
            clauses.append("i.archived_at IS NULL")
        if status is not None:
            clauses.append("i.status = :status")
            params["status"] = status
        if query:
            clauses.append(
                "(i.full_name ILIKE :q OR i.full_name_ar ILIKE :q "
                "OR i.email ILIKE :q OR i.code ILIKE :q)"
            )
            params["q"] = f"%{query}%"
        sql = (
            f"SELECT {_INVESTOR_COLUMNS} FROM {_INVESTOR_FROM} "
            f"WHERE {' AND '.join(clauses)} ORDER BY i.code"
        )
        return await self._rows(sql, params)

    async def get_investor(self, *, investor_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            f"SELECT {_INVESTOR_COLUMNS} FROM {_INVESTOR_FROM} "
            "WHERE i.id = :id AND i.deleted_at IS NULL",
            {"id": investor_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def insert_investor(
        self, *, investor_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> None:
        columns = ["id", "created_by", "updated_by", *fields.keys()]
        values = [f":{c}" for c in columns]
        await self._write(
            f"INSERT INTO investors ({', '.join(columns)}) " f"VALUES ({', '.join(values)})",
            {"id": investor_id, "created_by": actor_user_id, "updated_by": actor_user_id, **fields},
            tuple(
                c
                for c in ("id", "created_by", "updated_by", "relationship_manager_id")
                if c in columns
            ),
        )

    async def update_investor(
        self, *, investor_id: UUID, changes: dict[str, Any], actor_user_id: UUID | None
    ) -> None:
        if not changes:
            return
        bad = set(changes) - set(INVESTOR_WRITABLE)
        if bad:
            raise ValueError(f"not writable: {sorted(bad)}")
        sets = [f"{c} = :{c}" for c in changes]
        sets.append("updated_by = :actor")
        uuid_params = ["id", "actor"]
        for col in ("relationship_manager_id", "user_id"):
            if col in changes:
                uuid_params.append(col)
        await self._write(
            f"UPDATE investors SET {', '.join(sets)} WHERE id = :id",
            {"id": investor_id, "actor": actor_user_id, **changes},
            tuple(uuid_params),
        )

    async def investor_has_open_ownership(self, *, investor_id: UUID) -> bool:
        rows = await self._rows(
            "SELECT 1 FROM holding_ownerships o "
            f"WHERE o.investor_id = :id AND o.deleted_at IS NULL "
            f"AND (o.end_date IS NULL OR o.end_date >= {_TODAY}) LIMIT 1",
            {"id": investor_id},
            ("id",),
        )
        return bool(rows)

    # ---- Blocks (read-only view of the farms module's table) ---------------

    async def get_block(self, *, block_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            """
            SELECT b.id, b.farm_id, b.code, b.name, b.name_ar,
                   (b.active_to IS NULL OR b.active_to > (public.app_now())::date) AS is_active,
                   b.deleted_at, b.unit_type,
                   ST_AsGeoJSON(b.boundary)::jsonb AS boundary,
                   round(ST_Area(b.boundary_utm)::numeric, 2) AS area_m2,
                   EXISTS (
                     SELECT 1 FROM blocks c
                      WHERE c.parent_unit_id = b.id AND c.deleted_at IS NULL
                   ) AS has_children
              FROM blocks b
             WHERE b.id = :id
            """,
            {"id": block_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def holdings_outside(self, *, block_id: UUID, boundary_ewkt: str) -> list[str]:
        """Codes of live holdings that a proposed block boundary would cut (R6)."""
        rows = await self._rows(
            """
            WITH nb AS (
              SELECT ST_Transform(ST_GeomFromEWKT(:boundary), ST_SRID(b.boundary_utm)) AS g,
                     ST_SRID(b.boundary_utm) AS srid
                FROM blocks b WHERE b.id = :id
            )
            SELECT h.code
              FROM holdings h, nb
             WHERE h.block_id = :id
               AND h.deleted_at IS NULL
               AND h.archived_at IS NULL
               AND NOT ST_CoveredBy(ST_Transform(h.boundary, nb.srid), ST_Buffer(nb.g, 0.5))
             ORDER BY h.code
            """,
            {"id": block_id, "boundary": boundary_ewkt},
            ("id",),
        )
        return [r["code"] for r in rows]

    async def owned_holding_codes(self, *, block_ids: list[UUID]) -> list[str]:
        """Codes of live holdings in these blocks with a current or future owner (R7)."""
        if not block_ids:
            return []
        stmt = text(
            f"""
            SELECT DISTINCT h.code
              FROM holdings h
              JOIN holding_ownerships o ON o.holding_id = h.id
             WHERE h.block_id = ANY(:ids)
               AND h.deleted_at IS NULL
               AND o.deleted_at IS NULL
               AND (o.end_date IS NULL OR o.end_date >= {_TODAY})
             ORDER BY h.code
            """
        ).bindparams(bindparam("ids", type_=ARRAY(_UUID)))
        result = await self._session.execute(stmt, {"ids": list(block_ids)})
        return [r["code"] for r in result.mappings()]

    async def geometry_problem(self, *, boundary_ewkt: str) -> str | None:
        """PostGIS's own validity check (R3). None when the shape is valid."""
        rows = await self._rows(
            "SELECT ST_IsValid(g) AS ok, ST_IsValidReason(g) AS reason "
            "FROM (SELECT ST_GeomFromEWKT(:b) AS g) s",
            {"b": boundary_ewkt},
        )
        if not rows or rows[0]["ok"]:
            return None
        return str(rows[0]["reason"])

    # ---- Holdings ---------------------------------------------------------

    async def list_holdings(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        investor_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["h.deleted_at IS NULL"]
        params: dict[str, Any] = {}
        uuid_params: list[str] = []
        if farm_id is not None:
            clauses.append("b.farm_id = :farm_id")
            params["farm_id"] = farm_id
            uuid_params.append("farm_id")
        if block_id is not None:
            clauses.append("h.block_id = :block_id")
            params["block_id"] = block_id
            uuid_params.append("block_id")
        if investor_id is not None:
            clauses.append("cur.investor_id = :investor_id")
            params["investor_id"] = investor_id
            uuid_params.append("investor_id")
        if not include_archived:
            clauses.append("h.archived_at IS NULL")
        sql = (
            f"SELECT {_HOLDING_COLUMNS} FROM {_HOLDING_FROM} "
            f"WHERE {' AND '.join(clauses)} ORDER BY b.code, h.code"
        )
        return await self._rows(sql, params, tuple(uuid_params))

    async def get_holding(self, *, holding_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            f"SELECT {_HOLDING_COLUMNS} FROM {_HOLDING_FROM} "
            "WHERE h.id = :id AND h.deleted_at IS NULL",
            {"id": holding_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def insert_holding(
        self,
        *,
        holding_id: UUID,
        code: str,
        block_id: UUID,
        name: str,
        name_ar: str | None,
        boundary_ewkt: str,
        tree_count: int | None,
        status: str,
        notes_internal: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        # area_m2 = 1 is a placeholder: the BEFORE trigger measures the polygon
        # in the block's UTM zone and overwrites it before any CHECK runs.
        await self._write(
            """
            INSERT INTO holdings (
              id, code, block_id, name, name_ar, boundary, area_m2, tree_count,
              status, notes_internal, created_by, updated_by
            ) VALUES (
              :id, :code, :block_id, :name, :name_ar, ST_GeomFromEWKT(:boundary), 1,
              :tree_count, :status, :notes_internal, :actor, :actor
            )
            """,
            {
                "id": holding_id,
                "code": code,
                "block_id": block_id,
                "name": name,
                "name_ar": name_ar,
                "boundary": boundary_ewkt,
                "tree_count": tree_count,
                "status": status,
                "notes_internal": notes_internal,
                "actor": actor_user_id,
            },
            ("id", "block_id", "actor"),
        )

    async def update_holding(
        self,
        *,
        holding_id: UUID,
        changes: dict[str, Any],
        boundary_ewkt: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        bad = set(changes) - set(HOLDING_WRITABLE)
        if bad:
            raise ValueError(f"not writable: {sorted(bad)}")
        sets = [f"{c} = :{c}" for c in changes]
        params: dict[str, Any] = {"id": holding_id, "actor": actor_user_id, **changes}
        if boundary_ewkt is not None:
            sets.append("boundary = ST_GeomFromEWKT(:boundary)")
            params["boundary"] = boundary_ewkt
        if not sets:
            return
        sets.append("updated_by = :actor")
        await self._write(
            f"UPDATE holdings SET {', '.join(sets)} WHERE id = :id",
            params,
            ("id", "actor"),
        )

    async def holding_has_open_ownership(self, *, holding_id: UUID) -> bool:
        rows = await self._rows(
            "SELECT 1 FROM holding_ownerships o "
            "WHERE o.holding_id = :id AND o.deleted_at IS NULL "
            f"AND (o.end_date IS NULL OR o.end_date >= {_TODAY}) LIMIT 1",
            {"id": holding_id},
            ("id",),
        )
        return bool(rows)

    # ---- Ownership --------------------------------------------------------

    async def list_ownerships(
        self, *, holding_id: UUID | None = None, investor_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["o.deleted_at IS NULL", "h.deleted_at IS NULL"]
        params: dict[str, Any] = {}
        uuid_params: list[str] = []
        if holding_id is not None:
            clauses.append("o.holding_id = :holding_id")
            params["holding_id"] = holding_id
            uuid_params.append("holding_id")
        if investor_id is not None:
            clauses.append("o.investor_id = :investor_id")
            params["investor_id"] = investor_id
            uuid_params.append("investor_id")
        sql = (
            f"SELECT {_OWNERSHIP_COLUMNS} FROM {_OWNERSHIP_FROM} "
            f"WHERE {' AND '.join(clauses)} ORDER BY o.start_date DESC, o.created_at DESC"
        )
        return await self._rows(sql, params, tuple(uuid_params))

    async def get_ownership(self, *, ownership_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            f"SELECT {_OWNERSHIP_COLUMNS} FROM {_OWNERSHIP_FROM} "
            "WHERE o.id = :id AND o.deleted_at IS NULL",
            {"id": ownership_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def get_open_ended_ownership(self, *, holding_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            "SELECT o.id, o.investor_id, o.start_date FROM holding_ownerships o "
            "WHERE o.holding_id = :id AND o.deleted_at IS NULL AND o.end_date IS NULL",
            {"id": holding_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def insert_ownership(
        self,
        *,
        ownership_id: UUID,
        holding_id: UUID,
        investor_id: UUID,
        start_date: date,
        acquired_by: str,
        contract_ref: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        await self._write(
            """
            INSERT INTO holding_ownerships (
              id, holding_id, investor_id, start_date, acquired_by, contract_ref,
              created_by, updated_by
            ) VALUES (
              :id, :holding_id, :investor_id, :start_date, :acquired_by,
              :contract_ref, :actor, :actor
            )
            """,
            {
                "id": ownership_id,
                "holding_id": holding_id,
                "investor_id": investor_id,
                "start_date": start_date,
                "acquired_by": acquired_by,
                "contract_ref": contract_ref,
                "actor": actor_user_id,
            },
            ("id", "holding_id", "investor_id", "actor"),
        )

    async def end_ownership(
        self,
        *,
        ownership_id: UUID,
        end_date: date,
        ended_by: str,
        actor_user_id: UUID | None,
    ) -> None:
        await self._write(
            "UPDATE holding_ownerships SET end_date = :end_date, ended_by = :ended_by, "
            "updated_by = :actor WHERE id = :id",
            {
                "id": ownership_id,
                "end_date": end_date,
                "ended_by": ended_by,
                "actor": actor_user_id,
            },
            ("id", "actor"),
        )

    async def delete_ownership(self, *, ownership_id: UUID, actor_user_id: UUID | None) -> None:
        await self._write(
            "UPDATE holding_ownerships SET deleted_at = public.app_now(), "
            "updated_by = :actor WHERE id = :id",
            {"id": ownership_id, "actor": actor_user_id},
            ("id", "actor"),
        )

    # ---- Investments overview and farm map -------------------------------

    async def overview_farms(self) -> list[dict[str, Any]]:
        """One row per active farm: holdings by state and area sold vs not.

        "Not sold" is the area of the farm's active leaf blocks minus the area
        of holdings with a current owner, so unsold land with no holding drawn
        on it counts as not sold too.
        """
        return await self._rows(
            f"""
            SELECT f.id AS farm_id, f.name AS farm_name, f.name_ar AS farm_name_ar,
                   count(h.id)::int AS holdings,
                   count(h.id) FILTER (WHERE cur.id IS NOT NULL)::int AS sold,
                   count(h.id) FILTER (
                     WHERE cur.id IS NULL AND h.status = 'available')::int AS for_sale,
                   count(h.id) FILTER (
                     WHERE cur.id IS NULL AND h.status = 'draft')::int AS draft,
                   coalesce(sum(h.area_m2) FILTER (WHERE cur.id IS NOT NULL), 0)
                     AS area_sold_m2,
                   (SELECT coalesce(round(sum(ST_Area(b2.boundary_utm))::numeric, 2), 0)
                      FROM blocks b2
                     WHERE b2.farm_id = f.id
                       AND b2.deleted_at IS NULL
                       AND (b2.active_to IS NULL OR b2.active_to > {_TODAY})
                       AND NOT EXISTS (
                         SELECT 1 FROM blocks c
                          WHERE c.parent_unit_id = b2.id AND c.deleted_at IS NULL)
                   ) AS block_area_m2
              FROM farms f
              LEFT JOIN blocks b ON b.farm_id = f.id AND b.deleted_at IS NULL
              LEFT JOIN holdings h
                ON h.block_id = b.id AND h.deleted_at IS NULL AND h.archived_at IS NULL
              LEFT JOIN LATERAL (
                SELECT o.id FROM holding_ownerships o
                 WHERE o.holding_id = h.id AND {_CURRENT_OWNERSHIP}
                 LIMIT 1
              ) cur ON true
             WHERE f.deleted_at IS NULL
               AND (f.active_to IS NULL OR f.active_to > {_TODAY})
             GROUP BY f.id, f.name, f.name_ar
             ORDER BY f.name
            """,
            {},
        )

    async def count_live_investors(self) -> int:
        rows = await self._rows(
            "SELECT count(*)::int AS n FROM investors "
            "WHERE deleted_at IS NULL AND archived_at IS NULL",
            {},
        )
        return int(rows[0]["n"]) if rows else 0

    async def recent_ownerships(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Newest ownership entries, each with the owner it replaced, if any."""
        return await self._rows(
            """
            SELECT o.id, o.start_date, o.acquired_by, o.created_at,
                   h.id AS holding_id, h.code AS holding_code, b.farm_id,
                   i.id AS investor_id, i.code AS investor_code,
                   i.full_name AS investor_name, i.full_name_ar AS investor_name_ar,
                   prev.investor_code AS previous_investor_code,
                   prev.ended_by AS previous_ended_by
              FROM holding_ownerships o
              JOIN holdings h ON h.id = o.holding_id AND h.deleted_at IS NULL
              JOIN blocks b ON b.id = h.block_id
              JOIN investors i ON i.id = o.investor_id
              LEFT JOIN LATERAL (
                SELECT pi.code AS investor_code, p.ended_by
                  FROM holding_ownerships p
                  JOIN investors pi ON pi.id = p.investor_id
                 WHERE p.holding_id = o.holding_id
                   AND p.deleted_at IS NULL
                   AND p.end_date = o.start_date - 1
                 LIMIT 1
              ) prev ON true
             WHERE o.deleted_at IS NULL
             ORDER BY o.created_at DESC, o.id DESC
             LIMIT :limit
            """,
            {"limit": limit},
        )

    async def farm_blocks(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        """Active blocks of a farm, as the Holdings map draws them."""
        return await self._rows(
            f"""
            SELECT b.id, b.code, b.name, b.name_ar,
                   ST_AsGeoJSON(b.boundary)::jsonb AS boundary,
                   round(ST_Area(b.boundary_utm)::numeric, 2) AS area_m2,
                   NOT EXISTS (
                     SELECT 1 FROM blocks c
                      WHERE c.parent_unit_id = b.id AND c.deleted_at IS NULL
                   ) AS eligible
              FROM blocks b
             WHERE b.farm_id = :farm_id
               AND b.deleted_at IS NULL
               AND (b.active_to IS NULL OR b.active_to > {_TODAY})
             ORDER BY b.code
            """,
            {"farm_id": farm_id},
            ("farm_id",),
        )

    # ---- Investor app (read-only, the investor's own rows) ----------------

    async def get_investor_by_user(self, *, user_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            f"SELECT {_INVESTOR_COLUMNS} FROM {_INVESTOR_FROM} "
            "WHERE i.user_id = :uid AND i.deleted_at IS NULL "
            "ORDER BY i.created_at DESC LIMIT 1",
            {"uid": user_id},
            ("uid",),
        )
        return rows[0] if rows else None

    async def company_name(self) -> str | None:
        rows = await self._rows(
            "SELECT t.name FROM public.tenants t WHERE t.schema_name = current_schema()",
            {},
        )
        return str(rows[0]["name"]) if rows else None

    async def investor_app_holdings(
        self, *, investor_id: UUID, holding_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """The investor's ownerships with what the investor app may show.

        Deliberately narrow: no share, no other holdings, no notes, no
        contract numbers. The response schema is a second allowlist.
        """
        clauses = ["o.investor_id = :investor_id", "o.deleted_at IS NULL", "h.deleted_at IS NULL"]
        params: dict[str, Any] = {"investor_id": investor_id}
        uuid_params = ["investor_id"]
        if holding_id is not None:
            clauses.append("h.id = :holding_id")
            params["holding_id"] = holding_id
            uuid_params.append("holding_id")
        return await self._rows(
            f"""
            SELECT o.id AS ownership_id, o.start_date, o.end_date,
                   CASE
                     WHEN o.end_date IS NOT NULL AND o.end_date < {_TODAY} THEN 'past'
                     WHEN o.start_date > {_TODAY} THEN 'future'
                     ELSE 'current'
                   END AS period,
                   h.id AS holding_id, h.code, h.name, h.name_ar, h.area_m2, h.tree_count,
                   ST_AsGeoJSON(h.boundary)::jsonb AS boundary,
                   b.code AS block_code, b.name AS block_name, b.name_ar AS block_name_ar,
                   ST_AsGeoJSON(b.boundary)::jsonb AS block_boundary,
                   f.name AS farm_name, f.name_ar AS farm_name_ar,
                   crop.crop_name_en, crop.crop_name_ar,
                   crop.variety_name_en, crop.variety_name_ar, crop.planting_date
              FROM holding_ownerships o
              JOIN holdings h ON h.id = o.holding_id
              JOIN blocks b ON b.id = h.block_id
              JOIN farms f ON f.id = b.farm_id
              LEFT JOIN LATERAL (
                SELECT c.name_en AS crop_name_en, c.name_ar AS crop_name_ar,
                       v.name_en AS variety_name_en, v.name_ar AS variety_name_ar,
                       bc.planting_date
                  FROM block_crops bc
                  JOIN public.crops c ON c.id = bc.crop_id
                  LEFT JOIN public.crop_varieties v ON v.id = bc.crop_variety_id
                 WHERE bc.block_id = b.id
                   AND bc.deleted_at IS NULL
                   AND bc.effective_from <= {_TODAY}
                   AND (bc.effective_to IS NULL OR bc.effective_to > {_TODAY})
                 ORDER BY bc.effective_from DESC
                 LIMIT 1
              ) crop ON true
             WHERE {" AND ".join(clauses)}
             ORDER BY (o.end_date IS NULL) DESC, o.start_date DESC
            """,
            params,
            tuple(uuid_params),
        )
