"""SQL for harvest records (tenant schema)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared import clock

_UUID = PG_UUID(as_uuid=True)

_COLUMNS = """
    id, farm_id, block_id, block_crop_id, season_label, pick_no, label, label_ar,
    harvested_on, weight_kg, price_per_kg, currency, notes_internal,
    created_by, updated_by, created_at, updated_at
"""

#: Columns an update may set. The router validates values; this is the
#: second guard on which names reach the SQL.
WRITABLE = (
    "harvested_on",
    "weight_kg",
    "price_per_kg",
    "pick_no",
    "label",
    "label_ar",
    "notes_internal",
)


class HarvestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rows(
        self, sql: str, params: dict[str, Any], uuid_params: tuple[str, ...] = ()
    ) -> list[dict[str, Any]]:
        stmt = text(sql)
        if uuid_params:
            stmt = stmt.bindparams(*(bindparam(p, type_=_UUID) for p in uuid_params))
        result = await self._session.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    async def farm_for_block(self, block_id: UUID) -> UUID | None:
        rows = await self._rows(
            "SELECT farm_id FROM blocks WHERE id = :b AND deleted_at IS NULL",
            {"b": block_id},
            ("b",),
        )
        return rows[0]["farm_id"] if rows else None

    async def tenant_currency(self, tenant_id: UUID) -> str | None:
        rows = await self._rows(
            "SELECT default_currency FROM public.tenants WHERE id = :t", {"t": tenant_id}, ("t",)
        )
        return str(rows[0]["default_currency"]).strip() if rows else None

    async def block_crop_on(self, *, block_id: UUID, on: date) -> dict[str, Any] | None:
        """The crop assignment whose half-open validity range contains ``on``."""
        rows = await self._rows(
            """
            SELECT id, season_label FROM block_crops
             WHERE block_id = :b AND deleted_at IS NULL
               AND effective_from <= :on
               AND (effective_to IS NULL OR effective_to > :on)
             ORDER BY effective_from DESC LIMIT 1
            """,
            {"b": block_id, "on": on},
            ("b",),
        )
        return rows[0] if rows else None

    async def block_crop(self, *, block_id: UUID, block_crop_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            "SELECT id, season_label FROM block_crops "
            "WHERE id = :bc AND block_id = :b AND deleted_at IS NULL",
            {"bc": block_crop_id, "b": block_id},
            ("bc", "b"),
        )
        return rows[0] if rows else None

    async def next_pick_no(self, *, block_id: UUID, season_label: str) -> int:
        rows = await self._rows(
            "SELECT COALESCE(max(pick_no), 0) + 1 AS n FROM harvest_lots "
            "WHERE block_id = :b AND season_label = :s AND deleted_at IS NULL",
            {"b": block_id, "s": season_label},
            ("b",),
        )
        n: int = rows[0]["n"]
        return n

    async def pick_taken(
        self, *, block_id: UUID, season_label: str, pick_no: int, exclude_id: UUID | None
    ) -> bool:
        rows = await self._rows(
            """
            SELECT 1 FROM harvest_lots
             WHERE block_id = :b AND season_label = :s AND pick_no = :p
               AND deleted_at IS NULL
               AND (CAST(:x AS uuid) IS NULL OR id <> :x)
            """,
            {"b": block_id, "s": season_label, "p": pick_no, "x": exclude_id},
            ("b", "x"),
        )
        return bool(rows)

    async def list_for_block(self, block_id: UUID) -> list[dict[str, Any]]:
        return await self._rows(
            f"SELECT {_COLUMNS} FROM harvest_lots "  # noqa: S608 - fixed column list
            "WHERE block_id = :b AND deleted_at IS NULL "
            "ORDER BY harvested_on DESC, pick_no DESC",
            {"b": block_id},
            ("b",),
        )

    async def list_between(
        self, *, block_id: UUID, from_date: date, to_date: date | None
    ) -> list[dict[str, Any]]:
        """Live picks on the block harvested in [from_date, to_date] (open end when None)."""
        return await self._rows(
            f"SELECT {_COLUMNS} FROM harvest_lots "  # noqa: S608 - fixed column list
            "WHERE block_id = :b AND deleted_at IS NULL "
            "AND harvested_on >= :f "
            "AND (CAST(:t AS date) IS NULL OR harvested_on <= CAST(:t AS date)) "
            "ORDER BY harvested_on, pick_no",
            {"b": block_id, "f": from_date, "t": to_date},
            ("b",),
        )

    async def get(self, lot_id: UUID) -> dict[str, Any] | None:
        rows = await self._rows(
            f"SELECT {_COLUMNS} FROM harvest_lots "  # noqa: S608 - fixed column list
            "WHERE id = :id AND deleted_at IS NULL",
            {"id": lot_id},
            ("id",),
        )
        return rows[0] if rows else None

    async def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row)
        rows = await self._rows(
            f"INSERT INTO harvest_lots ({', '.join(cols)}) "  # noqa: S608 - keys are ours
            f"VALUES ({', '.join(':' + c for c in cols)}) RETURNING {_COLUMNS}",
            row,
            tuple(c for c in cols if c in ("farm_id", "block_id", "block_crop_id", "created_by")),
        )
        return rows[0]

    async def update(
        self, lot_id: UUID, changes: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any] | None:
        fields = {k: v for k, v in changes.items() if k in WRITABLE}
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        rows = await self._rows(
            f"UPDATE harvest_lots SET {sets + ', ' if sets else ''}"  # noqa: S608 - WRITABLE
            "updated_by = :actor WHERE id = :id AND deleted_at IS NULL "
            f"RETURNING {_COLUMNS}",
            {**fields, "actor": actor, "id": lot_id},
            ("actor", "id"),
        )
        return rows[0] if rows else None

    async def soft_delete(self, lot_id: UUID, actor: UUID | None) -> bool:
        rows = await self._rows(
            "UPDATE harvest_lots SET deleted_at = :now, updated_by = :actor "
            "WHERE id = :id AND deleted_at IS NULL RETURNING id",
            {"now": clock.now(), "actor": actor, "id": lot_id},
            ("actor", "id"),
        )
        return bool(rows)
