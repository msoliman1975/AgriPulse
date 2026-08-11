"""Async DB access for the resources module. Internal to the module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resources.errors import (
    DuplicateResourceNameError,
    InvalidResourceShapeError,
)
from app.modules.resources.models import ActivityResource, Resource, ResourceFarm


class ResourcesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Resources ----------------------------------------------------

    async def insert(
        self,
        *,
        resource_id: UUID,
        kind: str,
        name: str,
        role: str | None,
        equipment_type: str | None,
        phone: str | None,
        membership_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        resource = Resource(
            id=resource_id,
            kind=kind,
            name=name,
            role=role,
            equipment_type=equipment_type,
            phone=phone,
            membership_id=membership_id,
            archived_at=None,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(resource)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = str(exc.orig) if exc.orig else str(exc)
            if "uq_resources_kind_active_name" in msg:
                raise DuplicateResourceNameError(name=name, kind=kind) from exc
            if "ck_resources" in msg:
                raise InvalidResourceShapeError(
                    detail="Resource shape violates DB constraint."
                ) from exc
            raise
        return _to_dict(resource)

    async def get(self, *, resource_id: UUID) -> dict[str, Any] | None:
        stmt = select(Resource).where(Resource.id == resource_id, Resource.deleted_at.is_(None))
        row = (await self._session.execute(stmt)).scalars().one_or_none()
        return _to_dict(row) if row else None

    async def list(
        self,
        *,
        farm_id: UUID | None = None,
        kind: str | None = None,
        include_archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """Roster rows. ``farm_id=None`` is the tenant-wide view.

        Availability is read through ``resource_farms``: since 0071 there is
        no ``resources.farm_id`` to read, and one row can serve many farms.
        """
        # Annotated rather than inferred: the list would otherwise take its
        # type from the first element (a BinaryExpression) and reject the
        # `IN (subquery)` below, which is a plain ColumnElement.
        clauses: list[ColumnElement[bool]] = [Resource.deleted_at.is_(None)]
        if farm_id is not None:
            clauses.append(
                Resource.id.in_(
                    select(ResourceFarm.resource_id).where(ResourceFarm.farm_id == farm_id)
                )
            )
        if kind is not None:
            clauses.append(Resource.kind == kind)
        if not include_archived:
            clauses.append(Resource.archived_at.is_(None))
        stmt = select(Resource).where(*clauses).order_by(Resource.kind, Resource.name)
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_to_dict(r) for r in rows)

    # ---- Availability (W2-A) -------------------------------------------

    async def farm_ids_for(self, *, resource_id: UUID) -> tuple[UUID, ...]:
        rows = (
            await self._session.execute(
                select(ResourceFarm.farm_id)
                .where(ResourceFarm.resource_id == resource_id)
                .order_by(ResourceFarm.created_at, ResourceFarm.farm_id)
            )
        ).scalars()
        return tuple(rows.all())

    async def farm_ids_for_many(
        self, *, resource_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[UUID, ...]]:
        """Batched, so listing a roster does not fan out one query per row."""
        if not resource_ids:
            return {}
        rows = (
            await self._session.execute(
                select(ResourceFarm.resource_id, ResourceFarm.farm_id)
                .where(ResourceFarm.resource_id.in_(list(resource_ids)))
                .order_by(ResourceFarm.created_at, ResourceFarm.farm_id)
            )
        ).all()
        out: dict[UUID, list[UUID]] = {}
        for resource_id, farm_id in rows:
            out.setdefault(resource_id, []).append(farm_id)
        return {k: tuple(v) for k, v in out.items()}

    async def is_available_on(self, *, resource_id: UUID, farm_id: UUID) -> bool:
        row = (
            await self._session.execute(
                select(ResourceFarm.resource_id).where(
                    ResourceFarm.resource_id == resource_id,
                    ResourceFarm.farm_id == farm_id,
                )
            )
        ).first()
        return row is not None

    async def add_farm(self, *, resource_id: UUID, farm_id: UUID) -> None:
        await self._session.execute(
            pg_insert(ResourceFarm)
            .values(resource_id=resource_id, farm_id=farm_id)
            .on_conflict_do_nothing()
        )

    async def set_farms(self, *, resource_id: UUID, farm_ids: Sequence[UUID]) -> None:
        """Replace the availability set.

        Deletes then inserts rather than diffing: the set is small, and the
        `created_at` of a link that was already there carries no meaning worth
        preserving — only membership does.
        """
        await self._session.execute(
            delete(ResourceFarm).where(ResourceFarm.resource_id == resource_id)
        )
        for farm_id in dict.fromkeys(farm_ids):
            await self._session.execute(
                pg_insert(ResourceFarm)
                .values(resource_id=resource_id, farm_id=farm_id)
                .on_conflict_do_nothing()
            )

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
            if "uq_resources_kind_active_name" in msg:
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
        "kind": row.kind,
        "name": row.name,
        "role": row.role,
        "equipment_type": row.equipment_type,
        "phone": row.phone,
        "membership_id": row.membership_id,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
