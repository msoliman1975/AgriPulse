"""SQL for crop documents (D29). Public schema only; no tenant data."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "d.id, d.document_code, d.crop_path, d.title_en, d.title_ar, d.language, d.kind, "
    "d.edition, d.s3_key, d.original_filename, d.content_type, d.size_bytes, d.sha256, "
    "d.superseded_at, d.superseded_by, d.retired_at, d.created_at, d.updated_at, "
    "(d.superseded_at IS NULL AND d.retired_at IS NULL) AS is_current"
)

#: Columns PATCH may write. A key outside this set never reaches SQL.
EDITABLE = ("title_en", "title_ar", "language", "kind", "edition")


def path_chain(crop_path: str) -> list[str]:
    """``date_palm.medjool.x`` -> ``[date_palm, date_palm.medjool, date_palm.medjool.x]``.

    A document applies to a path when its own path is one of these: the
    path itself or an ancestor on a segment boundary, never a sibling.
    """
    segments = [s for s in crop_path.split(".") if s]
    return [".".join(segments[: i + 1]) for i in range(len(segments))]


class CropDocumentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def crop_path_exists(self, crop_path: str) -> bool:
        row = (
            await self._s.execute(
                text(
                    """
                    SELECT 1 FROM public.crops WHERE code = :p
                    UNION ALL SELECT 1 FROM public.crop_varieties WHERE path = :p
                    UNION ALL SELECT 1 FROM public.crop_variety_strains WHERE path = :p
                    LIMIT 1
                    """
                ),
                {"p": crop_path},
            )
        ).first()
        return row is not None

    async def get(self, document_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_COLUMNS} FROM public.crop_documents d WHERE d.id = :id"),
                {"id": document_id},
            )
        ).first()
        return dict(row._mapping) if row else None

    async def current_for(self, *, crop_path: str, document_code: str) -> dict[str, Any] | None:
        """The edition a new upload with this code would supersede, if any.

        Locked, so two concurrent uploads of a new edition serialise here
        instead of both trying to supersede the same row.
        """
        row = (
            await self._s.execute(
                text(
                    f"SELECT {_COLUMNS} FROM public.crop_documents d "
                    "WHERE d.crop_path = :p AND d.document_code = :c "
                    "AND d.superseded_at IS NULL FOR UPDATE"
                ),
                {"p": crop_path, "c": document_code},
            )
        ).first()
        return dict(row._mapping) if row else None

    async def supersede(self, *, document_id: UUID, by: UUID, actor: UUID | None) -> None:
        await self._s.execute(
            text(
                "UPDATE public.crop_documents "
                "SET superseded_at = public.app_now(), superseded_by = :by, updated_by = :actor "
                "WHERE id = :id AND superseded_at IS NULL"
            ),
            {"id": document_id, "by": by, "actor": actor},
        )

    async def insert(self, row: dict[str, Any], actor: UUID | None) -> None:
        await self._s.execute(
            text(
                """
                INSERT INTO public.crop_documents
                       (id, document_code, crop_path, title_en, title_ar, language, kind,
                        edition, s3_key, original_filename, content_type, size_bytes, sha256,
                        created_by, updated_by)
                VALUES (:id, :document_code, :crop_path, :title_en, :title_ar, :language, :kind,
                        :edition, :s3_key, :original_filename, :content_type, :size_bytes,
                        :sha256, :actor, :actor)
                """
            ),
            {**row, "actor": actor},
        )

    async def update(
        self, document_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any] | None:
        sets = [f"{k} = :{k}" for k in EDITABLE if k in fields]
        params: dict[str, Any] = {k: fields[k] for k in EDITABLE if k in fields}
        if "retired" in fields:
            sets.append(
                "retired_at = CASE WHEN CAST(:retired AS boolean) THEN coalesce(retired_at, public.app_now()) "
                "ELSE NULL END"
            )
            params["retired"] = bool(fields["retired"])
        sets.append("updated_by = :actor")
        params.update({"id": document_id, "actor": actor})
        result = await self._s.execute(
            text(f"UPDATE public.crop_documents SET {', '.join(sets)} WHERE id = :id RETURNING id"),
            params,
        )
        if result.first() is None:
            return None
        return await self.get(document_id)

    async def list_for_admin(self, crop_path: str) -> list[dict[str, Any]]:
        """Every edition on this path, plus the current ones it inherits."""
        rows = await self._s.execute(
            text(
                f"SELECT {_COLUMNS} FROM public.crop_documents d "
                "WHERE d.crop_path = :p "
                "   OR (d.crop_path = ANY(:ancestors) "
                "       AND d.superseded_at IS NULL AND d.retired_at IS NULL) "
                "ORDER BY length(d.crop_path), d.document_code, d.created_at DESC"
            ),
            {"p": crop_path, "ancestors": path_chain(crop_path)[:-1]},
        )
        return [dict(r._mapping) for r in rows]

    async def list_current_for_path(self, crop_path: str) -> list[dict[str, Any]]:
        """What a block on ``crop_path`` shows: current documents at or above it."""
        rows = await self._s.execute(
            text(
                f"SELECT {_COLUMNS} FROM public.crop_documents d "
                "WHERE d.crop_path = ANY(:chain) "
                "AND d.superseded_at IS NULL AND d.retired_at IS NULL "
                "ORDER BY length(d.crop_path) DESC, d.kind, d.title_en, d.language"
            ),
            {"chain": path_chain(crop_path)},
        )
        return [dict(r._mapping) for r in rows]
