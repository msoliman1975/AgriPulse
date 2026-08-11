"""Resources service — Protocol + concrete impl + factory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resources.errors import (
    InvalidResourceShapeError,
    ResourceNotAvailableOnFarmError,
    ResourceNotFoundError,
)
from app.modules.resources.repository import ResourcesRepository
from app.shared.db.ids import uuid7


class ResourcesService(Protocol):
    async def create(
        self,
        *,
        farm_id: UUID,
        kind: str,
        name: str,
        role: str | None,
        equipment_type: str | None,
        phone: str | None,
        membership_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]: ...

    async def get(self, *, resource_id: UUID) -> dict[str, Any]: ...

    async def list(
        self,
        *,
        farm_id: UUID | None = None,
        kind: str | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]: ...

    async def update(
        self,
        *,
        resource_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]: ...

    async def attach(
        self,
        *,
        activity_id: UUID,
        resource_id: UUID,
        actor_user_id: UUID | None,
        farm_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def detach(self, *, activity_id: UUID, resource_id: UUID) -> bool: ...

    async def list_for_activity(self, *, activity_id: UUID) -> tuple[dict[str, Any], ...]: ...


class ResourcesServiceImpl:
    def __init__(self, *, repo: ResourcesRepository) -> None:
        self._repo = repo

    async def create(
        self,
        *,
        farm_id: UUID,
        kind: str,
        name: str,
        role: str | None,
        equipment_type: str | None,
        phone: str | None,
        membership_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        resource_id = uuid7()
        created = await self._repo.insert(
            resource_id=resource_id,
            # Dual-written until 0071 drops the column: the running image may
            # still be one that reads it, and a row it cannot see is worse
            # than a redundant value.
            farm_id=farm_id,
            kind=kind,
            name=name.strip(),
            role=role,
            equipment_type=equipment_type,
            phone=phone,
            membership_id=membership_id,
            actor_user_id=actor_user_id,
        )
        # The link is what availability actually means now. Without it the row
        # exists tenant-wide and shows up on no farm at all.
        await self._repo.add_farm(resource_id=resource_id, farm_id=farm_id)
        created["farm_ids"] = [farm_id]
        return created

    async def get(self, *, resource_id: UUID) -> dict[str, Any]:
        row = await self._repo.get(resource_id=resource_id)
        if row is None:
            raise ResourceNotFoundError(resource_id)
        return row

    async def list(
        self,
        *,
        farm_id: UUID | None = None,
        kind: str | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list(farm_id=farm_id, kind=kind, include_archived=include_archived)

    async def update(
        self,
        *,
        resource_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Pull the existing row to enforce kind-specific field rules.
        current = await self._repo.get(resource_id=resource_id)
        if current is None:
            raise ResourceNotFoundError(resource_id)

        # `archive=True/False` is a derived field — translate it into
        # archived_at = now() / NULL. PATCH semantics: omitted = leave
        # untouched.
        normalized: dict[str, Any] = {}
        archive = changes.pop("archive", None)
        if archive is True:
            normalized["archived_at"] = datetime.now(UTC)
        elif archive is False:
            normalized["archived_at"] = None
        # `phone` and `membership_id` are nullable links the caller may
        # explicitly clear, so a literal null must pass through (unlink);
        # every other field treats null as "leave untouched".
        normalized.update(
            {k: v for k, v in changes.items() if v is not None or k in ("phone", "membership_id")}
        )

        if current["kind"] == "worker":
            if normalized.get("equipment_type") is not None:
                raise InvalidResourceShapeError(detail="Workers cannot carry an equipment_type.")
        else:
            if normalized.get("role") is not None:
                raise InvalidResourceShapeError(detail="Equipment cannot carry a role.")
            if normalized.get("phone") is not None:
                raise InvalidResourceShapeError(detail="Equipment cannot carry a phone.")
            if normalized.get("membership_id") is not None:
                raise InvalidResourceShapeError(detail="Equipment cannot be linked to a member.")

        if "name" in normalized and isinstance(normalized["name"], str):
            normalized["name"] = normalized["name"].strip()

        updated = await self._repo.update_fields(
            resource_id=resource_id,
            changes=normalized,
            actor_user_id=actor_user_id,
        )
        if updated is None:
            raise ResourceNotFoundError(resource_id)
        return updated

    async def attach(
        self,
        *,
        activity_id: UUID,
        resource_id: UUID,
        actor_user_id: UUID | None,
        farm_id: UUID | None = None,
    ) -> dict[str, Any]:
        # Validate resource exists and is not archived.
        resource = await self._repo.get(resource_id=resource_id)
        if resource is None:
            raise ResourceNotFoundError(resource_id)
        if resource.get("archived_at") is not None:
            raise InvalidResourceShapeError(
                detail="Cannot assign an archived resource. Restore it first."
            )
        # The guard `farm_id` used to make unnecessary. While a resource was
        # farm-locked, assigning one to an activity on another farm was
        # structurally impossible; tenant-level, nothing stops it — and the
        # result is somebody scheduled on a farm they cannot open, which is
        # exactly the drift the availability set exists to prevent.
        if farm_id is not None and not await self._repo.is_available_on(
            resource_id=resource_id, farm_id=farm_id
        ):
            raise ResourceNotAvailableOnFarmError(resource_id=resource_id, farm_id=farm_id)
        await self._repo.attach(
            activity_id=activity_id,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
        )
        return resource

    async def detach(self, *, activity_id: UUID, resource_id: UUID) -> bool:
        return await self._repo.detach(activity_id=activity_id, resource_id=resource_id)

    async def list_for_activity(self, *, activity_id: UUID) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_for_activity(activity_id=activity_id)


def get_resources_service(tenant_session: AsyncSession) -> ResourcesServiceImpl:
    return ResourcesServiceImpl(repo=ResourcesRepository(tenant_session))
