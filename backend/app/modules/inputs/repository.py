"""SQL for the inputs catalogue. Public schema; tenant rows carry tenant_id."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLS = (
    "i.id, i.tenant_id, i.code, i.name_en, i.name_ar, i.category, i.active_ingredient, "
    "i.methods, i.organic_status, i.organic_list, i.phi_days, i.rei_hours, i.crop_paths, "
    "i.notes, i.is_active, i.created_at, i.updated_at"
)
_EDITABLE = (
    "name_en",
    "name_ar",
    "category",
    "active_ingredient",
    "methods",
    "organic_status",
    "organic_list",
    "phi_days",
    "rei_hours",
    "crop_paths",
    "notes",
    "is_active",
)
_DOSE_COLS = "crop_path, value, value_min, value_max, unit, unit_note, context, reference"


class InputsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_inputs(
        self,
        *,
        tenant_id: UUID | None,
        crop_path: str | None,
        category: str | None,
        q: str | None,
        include_inactive: bool,
    ) -> list[dict[str, Any]]:
        clauses = ["(i.tenant_id IS NULL OR i.tenant_id = CAST(:tid AS uuid))"]
        params: dict[str, Any] = {"tid": tenant_id}
        if not include_inactive:
            clauses.append("i.is_active")
        if category:
            clauses.append("i.category = :cat")
            params["cat"] = category
        if q:
            clauses.append(
                "(i.name_en ILIKE :q OR coalesce(i.name_ar, '') ILIKE :q OR i.code ILIKE :q "
                "OR coalesce(i.active_ingredient, '') ILIKE :q)"
            )
            params["q"] = f"%{q}%"
        if crop_path:
            # An input scoped to a path applies to that path and everything
            # below it; an unscoped input applies to every crop (as signals, D21).
            clauses.append(
                "(cardinality(i.crop_paths) = 0 OR EXISTS (SELECT 1 FROM unnest(i.crop_paths) p "
                "WHERE :path = p OR :path LIKE p || '.%'))"
            )
            params["path"] = crop_path
        sql = f"SELECT {_COLS} FROM public.inputs i WHERE {' AND '.join(clauses)} ORDER BY i.category, i.name_en"  # noqa: S608 - fixed clauses; values bound
        rows = [dict(r._mapping) for r in await self._s.execute(text(sql), params)]
        await self._attach_doses(rows)
        return rows

    async def get_input(self, input_id: UUID) -> dict[str, Any] | None:
        sql = f"SELECT {_COLS} FROM public.inputs i WHERE i.id = :id"  # noqa: S608 - fixed columns
        row = (await self._s.execute(text(sql), {"id": input_id})).first()
        if row is None:
            return None
        out = [dict(row._mapping)]
        await self._attach_doses(out)
        return out[0]

    async def _attach_doses(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        sql = f"SELECT input_id, {_DOSE_COLS} FROM public.input_doses WHERE input_id = ANY(:ids) ORDER BY input_id, sort_order"  # noqa: S608 - fixed columns
        doses: dict[UUID, list[dict[str, Any]]] = {}
        for d in await self._s.execute(text(sql), {"ids": [r["id"] for r in rows]}):
            m = dict(d._mapping)
            doses.setdefault(m.pop("input_id"), []).append(m)
        for r in rows:
            r["doses"] = doses.get(r["id"], [])
            r["scope"] = "platform" if r["tenant_id"] is None else "tenant"

    async def code_taken(self, code: str, tenant_id: UUID | None) -> bool:
        return (
            await self._s.execute(
                text(
                    "SELECT 1 FROM public.inputs WHERE code = :code "
                    "AND tenant_id IS NOT DISTINCT FROM CAST(:tid AS uuid)"
                ),
                {"code": code, "tid": tenant_id},
            )
        ).first() is not None

    async def create(
        self, tenant_id: UUID | None, fields: dict[str, Any], actor: UUID | None
    ) -> UUID:
        cols = ["code", *[k for k in _EDITABLE if k in fields]]
        names = ", ".join(cols)
        values = ", ".join(":" + c for c in cols)
        sql = f"INSERT INTO public.inputs (tenant_id, {names}, created_by, updated_by) VALUES (:tid, {values}, :actor, :actor) RETURNING id"  # noqa: S608 - fixed column names; values bound
        return (
            await self._s.execute(
                text(sql), {**{c: fields[c] for c in cols}, "tid": tenant_id, "actor": actor}
            )
        ).scalar_one()

    async def update(self, input_id: UUID, fields: dict[str, Any], actor: UUID | None) -> None:
        cols = [k for k in _EDITABLE if k in fields]
        if not cols:
            return
        assignments = ", ".join(f"{c} = :{c}" for c in cols)
        sql = f"UPDATE public.inputs SET {assignments}, updated_by = :actor WHERE id = :id"  # noqa: S608 - fixed column names; values bound
        await self._s.execute(
            text(sql), {**{c: fields[c] for c in cols}, "actor": actor, "id": input_id}
        )

    async def replace_doses(self, input_id: UUID, doses: list[dict[str, Any]]) -> None:
        await self._s.execute(
            text("DELETE FROM public.input_doses WHERE input_id = :id"), {"id": input_id}
        )
        for order, dose in enumerate(doses):
            await self._s.execute(
                text(
                    f"INSERT INTO public.input_doses (input_id, {_DOSE_COLS}, sort_order) "  # noqa: S608 - fixed columns
                    "VALUES (:iid, :crop_path, :value, :value_min, :value_max, :unit, "
                    ":unit_note, :context, :reference, :o)"
                ),
                {**dose, "iid": input_id, "o": order},
            )
