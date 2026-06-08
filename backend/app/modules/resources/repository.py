"""Async DB access for the resources module. Internal to the module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resources.errors import (
    DuplicateResourceNameError,
    InvalidResourceShapeError,
)
from app.modules.resources.models import ActivityResource, Resource


class ResourcesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Resources ----------------------------------------------------

    async def insert(
        self,
        *,
        resource_id: UUID,
        farm_id: UUID,
        kind: str,
        name: str,
        role: str | None,
        equipment_type: str | None,
        phone: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        resource = Resource(
            id=resource_id,
            farm_id=farm_id,
            kind=kind,
            name=name,
            role=role,
            equipment_type=equipment_type,
            phone=phone,
            archived_at=None,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(resource)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = str(exc.orig) if exc.orig else str(exc)
            if "uq_resources_farm_kind_active_name" in msg:
                raise DuplicateResourceNameError(name=name, kind=kind) from exc
            if "ck_resources" in msg:
                raise InvalidResourceShapeError(
                    detail="Resource shape violates DB constraint."
                ) from exc
            raise
        return _to_dict(resource)

    async def get(self, *, resource_id: UUID, farm_id: UUID | None = None) -> dict[str, Any] | None:
        clauses = [Resource.id == resource_id, Resource.deleted_at.is_(None)]
        if farm_id is not None:
            clauses.append(Resource.farm_id == farm_id)
        stmt = select(Resource).where(*clauses)
        row = (await self._session.execute(stmt)).scalars().one_or_none()
        return _to_dict(row) if row else None

    async def list(
        self,
        *,
        farm_id: UUID,
        kind: str | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        clauses = [Resource.farm_id == farm_id, Resource.deleted_at.is_(None)]
        if kind is not None:
            clauses.append(Resource.kind == kind)
        if not include_archived:
            clauses.append(Resource.archived_at.is_(None))
        stmt = select(Resource).where(*clauses).order_by(Resource.kind, Resource.name)
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_to_dict(r) for r in rows)

    async def update_fields(
        self,
        *,
        resource_id: UUID,
        changes: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        if not changes:
            return await self.get(resource_id=resource_id)
        stmt = (
            update(Resource)
            .where(Resource.id == resource_id, Resource.deleted_at.is_(None))
            .values(**changes, updated_by=actor_user_id)
            .returning(Resource)
        )
        try:
            row = (await self._session.execute(stmt)).scalars().one_or_none()
        except IntegrityError as exc:
            msg = str(exc.orig) if exc.orig else str(exc)
            if "uq_resources_farm_kind_active_name" in msg:
                raise DuplicateResourceNameError(
                    name=str(changes.get("name", "")), kind="resource"
                ) from exc
            if "ck_resources" in msg:
                raise InvalidResourceShapeError(
                    detail="Resource shape violates DB constraint."
                ) from exc
            raise
        return _to_dict(row) if row else None

    # ---- Assignments --------------------------------------------------

    async def attach(
        self,
        *,
        activity_id: UUID,
        resource_id: UUID,
        actor_user_id: UUID | None,
    ) -> None:
        existing = await self._session.get(
            ActivityResource, {"activity_id": activity_id, "resource_id": resource_id}
        )
        if existing is not None:
            return
        self._session.add(
            ActivityResource(
                activity_id=activity_id,
                resource_id=resource_id,
                created_at=datetime.now(UTC),
                created_by=actor_user_id,
            )
        )
        await self._session.flush()

    async def detach(self, *, activity_id: UUID, resource_id: UUID) -> bool:
        existing = await self._session.get(
            ActivityResource, {"activity_id": activity_id, "resource_id": resource_id}
        )
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    async def list_for_activity(self, *, activity_id: UUID) -> tuple[dict[str, Any], ...]:
        stmt = (
            select(Resource)
            .join(ActivityResource, ActivityResource.resource_id == Resource.id)
            .where(
                ActivityResource.activity_id == activity_id,
                Resource.deleted_at.is_(None),
            )
            .order_by(Resource.kind, Resource.name)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_to_dict(r) for r in rows)


def _to_dict(row: Resource | None) -> dict[str, Any]:
    if row is None:
        return {}  # caller is responsible for None checks; this branch unused
    return {
        "id": row.id,
        "farm_id": row.farm_id,
        "kind": row.kind,
        "name": row.name,
        "role": row.role,
        "equipment_type": row.equipment_type,
        "phone": row.phone,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
