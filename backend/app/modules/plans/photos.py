"""Photos on plan activities (investor app v2, build plan 3.3).

A field worker uploads straight to storage through a presigned PUT (the same
flow as field-flag photos), then sends the keys with the ``complete`` action;
the activity and its photos are written in one transaction. Staff can hide a
single photo from investors (decision D5: photos reach investors
automatically unless hidden).

Every key is checked before it is attached: it must sit under this tenant's,
farm's and activity's prefix and the object must exist. A key issued for
another activity, farm or tenant is refused, so the attach call cannot be
used to point an activity at someone else's file.

Public surface: `ActivityPhotosService`, its errors, `IMAGE_TYPES`.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared import clock
from app.shared.db.ids import uuid7
from app.shared.storage import StorageClient, StorageObjectMissingError, get_storage_client

#: Accepted uploads by content type, and the extension each is stored under.
IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTOS_PER_ACTIVITY = 10
#: Presigned GET lifetime for photos shown to staff.
VIEW_EXPIRES_SECONDS = 900

_log = get_logger(__name__)


class ActivityPhotoRejectedError(Exception):
    """Wrong type or size, a key not issued for this activity, or nothing uploaded."""


class ActivityPhotoNotFoundError(Exception):
    pass


def photo_prefix(*, tenant_id: UUID, farm_id: UUID, activity_id: UUID) -> str:
    return f"tenants/{tenant_id}/farms/{farm_id}/activity-photos/{activity_id}/"


class ActivityPhotosService:
    def __init__(self, session: AsyncSession, *, storage: StorageClient | None = None) -> None:
        self._session = session
        self._storage_override = storage

    @property
    def _storage(self) -> StorageClient:
        return self._storage_override or get_storage_client()

    # ---- Upload ------------------------------------------------------------

    def init_upload(
        self,
        *,
        tenant_id: UUID,
        farm_id: UUID,
        activity_id: UUID,
        content_type: str,
        content_length: int,
    ) -> dict[str, Any]:
        content_type = content_type.strip().lower()
        ext = IMAGE_TYPES.get(content_type)
        if ext is None:
            raise ActivityPhotoRejectedError(
                f"{content_type!r} is not accepted; use JPEG, PNG, WebP or HEIC."
            )
        if not 0 < content_length <= MAX_PHOTO_BYTES:
            raise ActivityPhotoRejectedError(f"A photo must be 1 to {MAX_PHOTO_BYTES} bytes.")
        key = (
            photo_prefix(tenant_id=tenant_id, farm_id=farm_id, activity_id=activity_id)
            + f"{uuid7()}.{ext}"
        )
        upload = self._storage.presign_upload(
            key=key, content_type=content_type, content_length=content_length
        )
        return {
            "s3_key": key,
            "upload_url": upload.url,
            "upload_headers": upload.headers,
            "expires_at": upload.expires_at,
        }

    async def attach(
        self,
        *,
        tenant_id: UUID,
        farm_id: UUID,
        activity_id: UUID,
        keys: list[str],
        actor_user_id: UUID | None,
    ) -> list[UUID]:
        """Record uploaded photos on the activity. Returns the new photo ids."""
        unique = list(dict.fromkeys(keys))
        if not unique:
            return []
        prefix = photo_prefix(tenant_id=tenant_id, farm_id=farm_id, activity_id=activity_id)
        for key in unique:
            name = key[len(prefix) :] if key.startswith(prefix) else ""
            if not name or "/" in name or ".." in name:
                raise ActivityPhotoRejectedError("A photo key was not issued for this activity.")
        existing = await self._count(activity_id)
        if existing + len(unique) > MAX_PHOTOS_PER_ACTIVITY:
            raise ActivityPhotoRejectedError(
                f"An activity can hold at most {MAX_PHOTOS_PER_ACTIVITY} photos."
            )
        for key in unique:
            try:
                head = await asyncio.to_thread(self._storage.head_object, key=key)
            except StorageObjectMissingError as exc:
                raise ActivityPhotoRejectedError("A photo was not uploaded.") from exc
            stored = str(head.get("ContentType") or "").lower()
            size = int(head.get("ContentLength") or 0)
            if stored not in IMAGE_TYPES or not 0 < size <= MAX_PHOTO_BYTES:
                raise ActivityPhotoRejectedError("An uploaded photo is not an accepted image.")
        ids = [uuid7() for _ in unique]
        await self._session.execute(
            text(
                """
                INSERT INTO plan_activity_photos (id, activity_id, s3_key, taken_at, created_by)
                SELECT u.id, :activity_id, u.key, :now, :actor
                  FROM unnest(CAST(:ids AS uuid[]), CAST(:keys AS text[])) AS u(id, key)
                ON CONFLICT (s3_key) DO NOTHING
                """
            ).bindparams(
                bindparam("activity_id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
                bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))),
                bindparam("keys", type_=ARRAY(Text())),
            ),
            {
                "activity_id": activity_id,
                "actor": actor_user_id,
                "ids": ids,
                "keys": unique,
                "now": clock.now(),
            },
        )
        return ids

    async def _count(self, activity_id: UUID) -> int:
        count: int = (
            await self._session.execute(
                text(
                    "SELECT count(*) FROM plan_activity_photos "
                    "WHERE activity_id = :a AND deleted_at IS NULL"
                ),
                {"a": activity_id},
            )
        ).scalar_one()
        return count

    # ---- Staff switch ------------------------------------------------------

    async def set_hidden(
        self, *, activity_id: UUID, photo_id: UUID, hidden: bool
    ) -> dict[str, Any]:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        UPDATE plan_activity_photos
                           SET hidden_from_investors = :hidden
                         WHERE id = :pid AND activity_id = :aid AND deleted_at IS NULL
                        RETURNING id, s3_key, taken_at, created_at, created_by,
                                  hidden_from_investors
                        """
                    ),
                    {"hidden": hidden, "pid": photo_id, "aid": activity_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ActivityPhotoNotFoundError(str(photo_id))
        return self._public(dict(row))

    # ---- Reads -------------------------------------------------------------

    async def photos_by_activity(
        self, activity_ids: list[UUID]
    ) -> dict[UUID, list[dict[str, Any]]]:
        """Every live photo of these activities, oldest first, with view links."""
        if not activity_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT id, activity_id, s3_key, taken_at, created_at, created_by,
                               hidden_from_investors
                          FROM plan_activity_photos
                         WHERE activity_id = ANY(:ids) AND deleted_at IS NULL
                         ORDER BY created_at, id
                        """
                    ).bindparams(bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
                    {"ids": list(set(activity_ids))},
                )
            )
            .mappings()
            .all()
        )
        out: dict[UUID, list[dict[str, Any]]] = {}
        for row in rows:
            out.setdefault(row["activity_id"], []).append(self._public(dict(row)))
        return out

    async def with_photos(self, activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The activities with a ``photos`` list each, in one query."""
        photos = await self.photos_by_activity([a["id"] for a in activities])
        return [{**a, "photos": photos.get(a["id"], [])} for a in activities]

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        """The row with a view link instead of its storage key."""
        key = row.pop("s3_key")
        row.pop("activity_id", None)
        try:
            row["url"] = self._storage.presign_download(
                key=key, expires_seconds=VIEW_EXPIRES_SECONDS
            ).url
        except Exception as exc:  # a broken link must not break the activity read
            _log.warning("activity_photo_link_failed", photo_id=str(row["id"]), error=str(exc))
            row["url"] = None
        return row
