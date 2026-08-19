"""Field-flag rules: who may do what, and what a close must carry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.logging import get_logger
from app.modules.field_flags.events import FieldFlagRaisedV1
from app.modules.field_flags.repository import FieldFlagRepository
from app.shared.eventbus import get_default_bus
from app.shared.storage.client import PresignedUpload, StorageClient, get_storage_client


def _not_found(flag_id: UUID) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Field flag not found",
        detail=f"No field flag with id {flag_id}.",
        type_="https://agripulse.cloud/problems/field-flags/not-found",
        extras={"flag_id": str(flag_id)},
    )


def _conflict(detail: str) -> APIError:
    return APIError(
        status_code=status.HTTP_409_CONFLICT,
        title="Field flag state",
        detail=detail,
        type_="https://agripulse.cloud/problems/field-flags/conflict",
    )


class FieldFlagService:
    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        tenant_schema: str | None = None,
        storage: StorageClient | None = None,
    ) -> None:
        self._repo = FieldFlagRepository(tenant_session)
        self._tenant_schema = tenant_schema
        self._storage = storage or get_storage_client()
        self._log = get_logger(__name__)

    # ---- Reads -------------------------------------------------------------

    async def list_flags(
        self, *, farm_id: UUID, open_only: bool, pinned_only: bool
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_flags(
            farm_id=farm_id, open_only=open_only, pinned_only=pinned_only
        )
        names = await self._repo.resolve_names(
            user_ids=[r["raised_by"] for r in rows]
            + [r["closed_by"] for r in rows if r["closed_by"]]
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["block_name"] = r["block_name"] or r["block_code"]
            item["raised_by_name"] = names.get(r["raised_by"])
            item["closed_by_name"] = names.get(r["closed_by"]) if r["closed_by"] else None
            out.append(item)
        return out

    async def get_flag(self, *, flag_id: UUID, with_thread: bool = True) -> dict[str, Any]:
        row = await self._repo.get_flag(flag_id=flag_id)
        if row is None:
            raise _not_found(flag_id)
        item = dict(row)
        item["block_name"] = row["block_name"] or row["block_code"]
        names = await self._repo.resolve_names(
            user_ids=[row["raised_by"]] + ([row["closed_by"]] if row["closed_by"] else [])
        )
        item["raised_by_name"] = names.get(row["raised_by"])
        item["closed_by_name"] = names.get(row["closed_by"]) if row["closed_by"] else None
        if with_thread:
            item["comments"] = [dict(c) for c in await self._repo.list_comments(flag_id=flag_id)]
            item["photos"] = [
                {**p, "download_url": self._download_url(p["attachment_s3_key"])}
                for p in await self._repo.list_photos(flag_id=flag_id)
            ]
        return item

    def _download_url(self, key: str) -> str | None:
        """A presigned GET, minted per read.

        Returns None rather than raising when the object has gone: a flag
        whose photograph was purged is still a flag, and a broken thumbnail
        beats a 500 on the whole thread.
        """
        try:
            return self._storage.presign_download(key=key).url
        except Exception:
            self._log.warning("field_flag_photo_url_failed", key=key)
            return None

    # ---- Writes ------------------------------------------------------------

    async def raise_flag(
        self, *, farm_id: UUID, payload: Any, actor_user_id: UUID
    ) -> dict[str, Any]:
        days = await self._repo.pin_days_for_farm(farm_id=farm_id)
        # Stored on the row, not computed from the farm setting on read:
        # otherwise editing one number silently removes every existing pin
        # from the map with nothing connecting cause to effect.
        pin_until = datetime.now(UTC) + timedelta(days=days)
        flag_id = await self._repo.insert_flag(
            values={
                "farm_id": farm_id,
                "block_id": payload.block_id,
                "note": payload.note,
                "severity": payload.severity,
                "lat": payload.point.latitude if payload.point else None,
                "lon": payload.point.longitude if payload.point else None,
                "accuracy_m": payload.accuracy_m,
                "pin_until": pin_until,
                "raised_by": actor_user_id,
            }
        )
        await self._repo.insert_photos(flag_id=flag_id, keys=list(payload.attachment_s3_keys))
        flag = await self.get_flag(flag_id=flag_id)
        self._announce(flag=flag, actor_user_id=actor_user_id)
        return flag

    def _announce(self, *, flag: dict[str, Any], actor_user_id: UUID) -> None:
        """Only `critical` announces itself.

        The two lower severities wait to be found on the map, which is where a
        supervisor already looks. Announcing every flag would rebuild the
        bombardment the Action Center spent a release removing.

        Best-effort: a bus failure must not undo a flag the scout has already
        been told was raised.
        """
        if flag["severity"] != "critical":
            return
        try:
            get_default_bus().publish(
                FieldFlagRaisedV1(
                    flag_id=flag["id"],
                    farm_id=flag["farm_id"],
                    block_id=flag["block_id"],
                    severity=str(flag["severity"]),
                    title=str(flag["note"]).strip().split("\n")[0][:200],
                    raised_by_user_id=actor_user_id,
                    tenant_schema=self._tenant_schema,
                )
            )
        except Exception:
            self._log.exception("field_flag_announce_failed", flag_id=str(flag["id"]))

    async def comment(self, *, flag_id: UUID, body: str, actor_user_id: UUID) -> dict[str, Any]:
        await self._assert_exists(flag_id)
        await self._repo.insert_comment(flag_id=flag_id, body=body, author_id=actor_user_id)
        return await self.get_flag(flag_id=flag_id)

    async def close(
        self, *, flag_id: UUID, reason: str, comment: str, actor_user_id: UUID
    ) -> dict[str, Any]:
        flag = await self._assert_exists(flag_id)
        if flag["status"] == "closed":
            raise _conflict("This flag is already closed.")
        # Comment first: if the close fails, the reasoning is still on the
        # thread. The other order can close a flag with no explanation, which
        # is exactly what the reason requirement exists to prevent.
        await self._repo.insert_comment(
            flag_id=flag_id, body=comment, author_id=actor_user_id, kind="close"
        )
        await self._repo.close_flag(flag_id=flag_id, reason=reason, closed_by=actor_user_id)
        return await self.get_flag(flag_id=flag_id)

    async def reopen(self, *, flag_id: UUID, comment: str, actor_user_id: UUID) -> dict[str, Any]:
        flag = await self._assert_exists(flag_id)
        if flag["status"] == "open":
            raise _conflict("This flag is already open.")
        days = await self._repo.pin_days_for_farm(farm_id=flag["farm_id"])
        await self._repo.insert_comment(
            flag_id=flag_id, body=comment, author_id=actor_user_id, kind="reopen"
        )
        await self._repo.reopen_flag(
            flag_id=flag_id, pin_until=datetime.now(UTC) + timedelta(days=days)
        )
        return await self.get_flag(flag_id=flag_id)

    async def init_photo_upload(
        self,
        *,
        farm_id: UUID,
        tenant_id: UUID,
        content_type: str,
        content_length: int,
        filename: str,
    ) -> dict[str, Any]:
        """Presigned PUT for one photograph.

        Mirrors the signals attachment flow deliberately: the bytes go
        straight to object storage rather than through the API, so a photo on
        a field connection never occupies an API worker.
        """
        safe = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
        key = f"tenants/{tenant_id}/farms/{farm_id}/field-flags/{uuid4()}/{safe}"
        upload: PresignedUpload = self._storage.presign_upload(
            key=key, content_type=content_type, content_length=content_length
        )
        return {
            "attachment_s3_key": key,
            "upload_url": upload.url,
            "upload_headers": upload.headers,
            "expires_at": upload.expires_at,
        }

    async def _assert_exists(self, flag_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_flag(flag_id=flag_id)
        if row is None:
            raise _not_found(flag_id)
        return dict(row)


def get_field_flag_service(
    *, tenant_session: AsyncSession, tenant_schema: str | None = None
) -> FieldFlagService:
    return FieldFlagService(tenant_session=tenant_session, tenant_schema=tenant_schema)
