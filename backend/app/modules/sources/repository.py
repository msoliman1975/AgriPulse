"""SQL for the sources library. Public schema only; no tenant data."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

_SOURCE_COLUMNS = (
    "s.id, s.kind, s.citation, s.title, s.authors, s.year, s.publisher, s.doi, "
    "s.url, s.language, s.notes, s.is_active, s.created_at, s.updated_at"
)
_EDITABLE = (
    "kind",
    "citation",
    "title",
    "authors",
    "year",
    "publisher",
    "doi",
    "url",
    "language",
    "notes",
    "is_active",
)


class SourcesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_sources(
        self,
        *,
        q: str | None,
        document_code: str | None,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if not include_inactive:
            clauses.append("s.is_active")
        if q:
            clauses.append(
                "(s.citation ILIKE :q OR coalesce(s.title, '') ILIKE :q "
                "OR coalesce(s.authors, '') ILIKE :q OR coalesce(s.doi, '') ILIKE :q)"
            )
            params["q"] = f"%{q}%"
        if document_code:
            clauses.append(
                "EXISTS (SELECT 1 FROM public.source_aliases a "
                "WHERE a.source_id = s.id AND a.document_code = :doc)"
            )
            params["doc"] = document_code
        rows = await self._s.execute(
            text(
                f"""
                SELECT {_SOURCE_COLUMNS},
                       (SELECT count(*) FROM public.source_links l
                         WHERE l.source_id = s.id) AS link_count,
                       coalesce((SELECT json_agg(json_build_object(
                                    'document_code', a.document_code,
                                    'ref_number', a.ref_number)
                                  ORDER BY a.document_code, a.ref_number)
                                  FROM public.source_aliases a
                                 WHERE a.source_id = s.id), '[]') AS aliases
                  FROM public.sources s
                 WHERE {' AND '.join(clauses)}
                 ORDER BY s.year DESC NULLS LAST, s.citation
                 LIMIT :limit OFFSET :offset
                """  # noqa: S608 - fixed columns and clauses; values are bound
            ),
            params,
        )
        return [dict(r._mapping) for r in rows]

    async def get_source(self, source_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(
                    f"SELECT {_SOURCE_COLUMNS} FROM public.sources s WHERE s.id = :id"  # noqa: S608
                ),
                {"id": source_id},
            )
        ).first()
        return dict(row._mapping) if row else None

    async def list_aliases(self, source_id: UUID) -> list[dict[str, Any]]:
        rows = await self._s.execute(
            text(
                "SELECT document_code, document_title, ref_number FROM public.source_aliases "
                "WHERE source_id = :id ORDER BY document_code, ref_number"
            ),
            {"id": source_id},
        )
        return [dict(r._mapping) for r in rows]

    async def list_documents(self) -> list[dict[str, Any]]:
        rows = await self._s.execute(
            text(
                "SELECT document_code, max(document_title) AS document_title, "
                "count(*) AS entries FROM public.source_aliases "
                "GROUP BY document_code ORDER BY document_code"
            )
        )
        return [dict(r._mapping) for r in rows]

    async def resolve_alias(self, document_code: str, ref_number: int) -> UUID | None:
        return (
            await self._s.execute(
                text(
                    "SELECT source_id FROM public.source_aliases "
                    "WHERE document_code = :doc AND ref_number = :num"
                ),
                {"doc": document_code, "num": ref_number},
            )
        ).scalar_one_or_none()

    async def create_source(self, fields: dict[str, Any], actor: UUID | None) -> UUID:
        cols = [k for k in _EDITABLE if k in fields]
        names = ", ".join(cols)
        values = ", ".join(":" + c for c in cols)
        sql = f"INSERT INTO public.sources ({names}, created_by, updated_by) VALUES ({values}, :actor, :actor) RETURNING id"  # noqa: S608 - fixed column names; values bound
        return (
            await self._s.execute(text(sql), {**{c: fields[c] for c in cols}, "actor": actor})
        ).scalar_one()

    async def update_source(
        self, source_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> bool:
        cols = [k for k in _EDITABLE if k in fields]
        if not cols:
            return await self.get_source(source_id) is not None
        assignments = ", ".join(f"{c} = :{c}" for c in cols)
        sql = f"UPDATE public.sources SET {assignments}, updated_by = :actor WHERE id = :id"  # noqa: S608 - fixed column names; values bound
        result = await self._s.execute(
            text(sql), {**{c: fields[c] for c in cols}, "actor": actor, "id": source_id}
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def doi_taken(self, doi: str, exclude_id: UUID | None = None) -> bool:
        return (
            await self._s.execute(
                text(
                    "SELECT 1 FROM public.sources WHERE lower(doi) = lower(:doi) "
                    "AND (CAST(:ex AS uuid) IS NULL OR id <> CAST(:ex AS uuid))"
                ),
                {"doi": doi, "ex": exclude_id},
            )
        ).first() is not None

    async def list_links(
        self,
        *,
        source_id: UUID | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: dict[str, Any] = {}
        if source_id is not None:
            clauses.append("l.source_id = :sid")
            params["sid"] = source_id
        if entity_type is not None:
            clauses.append("l.entity_type = :et")
            params["et"] = entity_type
        if entity_key is not None:
            clauses.append("l.entity_key = :ek")
            params["ek"] = entity_key
        rows = await self._s.execute(
            text(
                f"""
                SELECT l.id, l.source_id, l.entity_type, l.entity_key, l.detail,
                       l.confidence, l.note, l.created_at,
                       s.citation, s.url, s.doi, s.year, s.kind
                  FROM public.source_links l
                  JOIN public.sources s ON s.id = l.source_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY l.entity_type, l.entity_key, l.detail, s.citation
                """
            ),
            params,
        )
        return [dict(r._mapping) for r in rows]

    async def upsert_link(
        self, source_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> UUID:
        return (
            await self._s.execute(
                text(
                    """
                    INSERT INTO public.source_links
                        (source_id, entity_type, entity_key, detail, confidence, note, created_by)
                    VALUES (:sid, :entity_type, :entity_key, :detail, :confidence, :note, :actor)
                    ON CONFLICT (source_id, entity_type, entity_key, detail)
                    DO UPDATE SET confidence = EXCLUDED.confidence, note = EXCLUDED.note
                    RETURNING id
                    """
                ),
                {"sid": source_id, "actor": actor, **fields},
            )
        ).scalar_one()

    async def delete_link(self, link_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(
                    "DELETE FROM public.source_links WHERE id = :id "
                    "RETURNING id, source_id, entity_type, entity_key, detail"
                ),
                {"id": link_id},
            )
        ).first()
        return dict(row._mapping) if row else None
