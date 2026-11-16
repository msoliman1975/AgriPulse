"""SQL for crop images. The columns live on the public crop catalogue."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.storage import CropImageKind

# Whole statements per kind, so no table name is ever spliced into SQL.
_GET: dict[CropImageKind, str] = {
    "crops": "SELECT id, image_s3_key FROM public.crops WHERE id = :id",
    "varieties": "SELECT id, image_s3_key FROM public.crop_varieties WHERE id = :id",
}
# updated_at is kept by each table's trigger.
_SET: dict[CropImageKind, str] = {
    "crops": "UPDATE public.crops SET image_s3_key = :key WHERE id = :id",
    "varieties": "UPDATE public.crop_varieties SET image_s3_key = :key WHERE id = :id",
}


class CropImagesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_owner(self, kind: CropImageKind, owner_id: UUID) -> dict[str, Any] | None:
        """``{id, image_s3_key}`` for a crop or variety, or None when it does not exist."""
        row = (await self._session.execute(text(_GET[kind]), {"id": owner_id})).first()
        return dict(row._mapping) if row is not None else None

    async def set_key(self, kind: CropImageKind, owner_id: UUID, key: str | None) -> None:
        await self._session.execute(text(_SET[kind]), {"id": owner_id, "key": key})
