"""Async DB access for the signals module. Internal to the module.

All three tables are tenant-scoped; the caller binds the session to
the right schema via `SET LOCAL search_path` before calling in.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.signals.errors import SignalCodeAlreadyExistsError
from app.modules.signals.models import (
    SignalAssignment,
    SignalDefinition,
)


class SignalsRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Definitions --------------------------------------------------

    async def list_definitions(
        self, *, include_inactive: bool = False
    ) -> tuple[dict[str, Any], ...]:
        clauses = [SignalDefinition.deleted_at.is_(None)]
        if not include_inactive:
            clauses.append(SignalDefinition.is_active.is_(True))
        stmt = (
            select(SignalDefinition)
            .where(*clauses)
            .order_by(SignalDefinition.code.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_definition_to_dict(r) for r in rows)

    async def get_definition(
        self, *, definition_id: UUID | None = None, code: str | None = None
    ) -> dict[str, Any] | None:
        clauses = [SignalDefinition.deleted_at.is_(None)]
        if definition_id is not None:
            clauses.append(SignalDefinition.id == definition_id)
        elif code is not None:
            clauses.append(SignalDefinition.code == code)
        else:
            raise ValueError("must provide definition_id or code")
        row = (
            await self._session.execute(select(SignalDefinition).where(*clauses))
        ).scalars().one_or_none()
        return _definition_to_dict(row) if row is not None else None

    async def insert_definition(
        self,
        *,
        definition_id: UUID,
        code: str,
        name: str,
        description: str | None,
        value_kind: str,
        unit: str | None,
        categorical_values: list[str] | None,
        value_min: Decimal | None,
        value_max: Decimal | None,
        attachment_allowed: bool,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO signal_definitions (
                        id, code, name, description, value_kind, unit,
                        categorical_values, value_min, value_max,
                        attachment_allowed, is_active,
                        created_by, updated_by
                    ) VALUES (
                        :id, :code, :name, :description, :value_kind, :unit,
                        :categorical_values, :value_min, :value_max,
                        :attachment_allowed, TRUE,
                        :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": definition_id,
                    "code": code,
                    "name": name,
                    "description": description,
                    "value_kind": value_kind,
                    "unit": unit,
                    "categorical_values": categorical_values,
                    "value_min": value_min,
                    "value_max": value_max,
                    "attachment_allowed": attachment_allowed,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if "uq_signal_definitions_code_active" in str(exc):
                raise SignalCodeAlreadyExistsError(code) from exc
            raise
        await self._session.flush()
        out = await self.get_definition(definition_id=definition_id)
        if out is None:
            raise RuntimeError("Definition insert succeeded but row is missing")
        return out

    async def update_definition(
        self,
        *,
        definition_id: UUID,
        updates: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        if not updates:
            return await self.get_definition(definition_id=definition_id)
        # Static set of allowed columns — no caller-supplied identifiers.
        allowed = {
            "name",
            "description",
            "unit",
            "categorical_values",
            "value_min",
            "value_max",
            "attachment_allowed",
            "is_active",
        }
        sets: list[str] = []
        params: dict[str, Any] = {"id": definition_id, "actor": actor_user_id}
        for col, value in updates.items():
            if col not in allowed:
                continue
            sets.append(f"{col} = :{col}")
            params[col] = value
        if not sets:
            return await self.get_definition(definition_id=definition_id)
        sets.extend(["updated_at = now()", "updated_by = :actor"])
        await self._session.execute(
            text(
                f"UPDATE signal_definitions SET {', '.join(sets)} "  # noqa: S608
                "WHERE id = :id AND deleted_at IS NULL"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )
        return await self.get_definition(definition_id=definition_id)

    async def soft_delete_definition(
        self, *, definition_id: UUID, actor_user_id: UUID | None
    ) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE signal_definitions "
                "SET deleted_at = now(), updated_by = :actor, updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": definition_id, "actor": actor_user_id},
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    # ---- Assignments --------------------------------------------------

    async def list_assignments(
        self, *, definition_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        stmt = (
            select(SignalAssignment)
            .where(
                SignalAssignment.signal_definition_id == definition_id,
                SignalAssignment.deleted_at.is_(None),
            )
            .order_by(SignalAssignment.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_assignment_to_dict(r) for r in rows)

    async def insert_assignment(
        self,
        *,
        assignment_id: UUID,
        definition_id: UUID,
        farm_id: UUID | None,
        block_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        await self._session.execute(
            text(
                """
                INSERT INTO signal_assignments (
                    id, signal_definition_id, farm_id, block_id,
                    is_active, created_by, updated_by
                ) VALUES (
                    :id, :def_id, :farm_id, :block_id,
                    TRUE, :actor, :actor
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("def_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": assignment_id,
                "def_id": definition_id,
                "farm_id": farm_id,
                "block_id": block_id,
                "actor": actor_user_id,
            },
        )
        await self._session.flush()
        row = (
            await self._session.execute(
                select(SignalAssignment).where(SignalAssignment.id == assignment_id)
            )
        ).scalars().one()
        return _assignment_to_dict(row)

    async def soft_delete_assignment(
        self, *, assignment_id: UUID, actor_user_id: UUID | None
    ) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE signal_assignments "
                "SET deleted_at = now(), updated_by = :actor, updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": assignment_id, "actor": actor_user_id},
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    # ---- Observations -------------------------------------------------

    async def insert_observation(
        self,
        *,
        observation_id: UUID,
        time: datetime,
        signal_definition_id: UUID,
        farm_id: UUID,
        block_id: UUID | None,
        value_numeric: Decimal | None,
        value_categorical: str | None,
        value_event: str | None,
        value_boolean: bool | None,
        value_geopoint_wkt: str | None,
        attachment_s3_key: str | None,
        notes: str | None,
        recorded_by: UUID,
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO signal_observations (
                    time, id, signal_definition_id, farm_id, block_id,
                    value_numeric, value_categorical, value_event, value_boolean,
                    value_geopoint, attachment_s3_key, notes, recorded_by
                ) VALUES (
                    :time, :id, :def_id, :farm_id, :block_id,
                    :value_numeric, :value_categorical, :value_event, :value_boolean,
                    CASE WHEN :geopoint IS NULL THEN NULL
                         ELSE ST_GeomFromText(:geopoint, 4326) END,
                    :attachment_s3_key, :notes, :recorded_by
                )
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("def_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("recorded_by", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "time": time,
                "id": observation_id,
                "def_id": signal_definition_id,
                "farm_id": farm_id,
                "block_id": block_id,
                "value_numeric": value_numeric,
                "value_categorical": value_categorical,
                "value_event": value_event,
                "value_boolean": value_boolean,
                "geopoint": value_geopoint_wkt,
                "attachment_s3_key": attachment_s3_key,
                "notes": notes,
                "recorded_by": recorded_by,
            },
        )

    async def list_observations(
        self,
        *,
        signal_definition_id: UUID | None = None,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if signal_definition_id is not None:
            clauses.append("o.signal_definition_id = :def_id")
            params["def_id"] = signal_definition_id
        if farm_id is not None:
            clauses.append("o.farm_id = :farm_id")
            params["farm_id"] = farm_id
        if block_id is not None:
            clauses.append("o.block_id = :block_id")
            params["block_id"] = block_id
        if since is not None:
            clauses.append("o.time >= :since")
            params["since"] = since
        if until is not None:
            clauses.append("o.time < :until")
            params["until"] = until
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT o.id, o.time, o.signal_definition_id, "
            "       d.code AS signal_code, "
            "       o.farm_id, o.block_id, "
            "       o.value_numeric, o.value_categorical, o.value_event, o.value_boolean, "
            "       CASE WHEN o.value_geopoint IS NULL THEN NULL "
            "            ELSE ST_AsGeoJSON(o.value_geopoint)::jsonb END AS value_geopoint_geojson, "
            "       o.attachment_s3_key, o.notes, o.recorded_by, o.inserted_at "
            "FROM signal_observations o "
            "JOIN signal_definitions d ON d.id = o.signal_definition_id "
            f"{where_sql} "
            "ORDER BY o.time DESC LIMIT :limit"
        )
        rows = (await self._session.execute(text(sql), params)).mappings().all()
        return tuple(dict(r) for r in rows)

    # ---- Cross-module reader for the conditions snapshot --------------

    async def get_latest_observation_per_signal_for_block(
        self, *, block_id: UUID, farm_id: UUID
    ) -> dict[str, dict[str, Any]]:
        """Latest observation for every signal that applies to ``block_id``.

        A signal applies when an active assignment row matches the
        block, the farm (block-agnostic), or is tenant-wide
        (farm_id and block_id both NULL). The query joins to
        ``signal_definitions`` to expose ``code`` as the dict key so
        callers can look up by stable identifier.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    WITH applicable AS (
                        SELECT DISTINCT d.id, d.code
                        FROM signal_definitions d
                        JOIN signal_assignments a ON a.signal_definition_id = d.id
                        WHERE d.deleted_at IS NULL
                          AND d.is_active = TRUE
                          AND a.deleted_at IS NULL
                          AND a.is_active = TRUE
                          AND (
                                (a.farm_id IS NULL AND a.block_id IS NULL)
                             OR (a.block_id = :block_id)
                             OR (a.farm_id = :farm_id AND a.block_id IS NULL)
                          )
                    ),
                    latest AS (
                        SELECT DISTINCT ON (o.signal_definition_id)
                               o.signal_definition_id, o.time,
                               o.value_numeric, o.value_categorical,
                               o.value_event, o.value_boolean
                        FROM signal_observations o
                        WHERE o.signal_definition_id IN (SELECT id FROM applicable)
                          AND (o.block_id = :block_id OR o.block_id IS NULL)
                          AND o.farm_id = :farm_id
                        ORDER BY o.signal_definition_id, o.time DESC
                    )
                    SELECT a.code, l.time, l.value_numeric, l.value_categorical,
                           l.value_event, l.value_boolean
                    FROM applicable a
                    LEFT JOIN latest l ON l.signal_definition_id = a.id
                    """
                ).bindparams(
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                ),
                {"block_id": block_id, "farm_id": farm_id},
            )
        ).mappings().all()
        return {
            row["code"]: {
                "time": row["time"],
                "value_numeric": row["value_numeric"],
                "value_categorical": row["value_categorical"],
                "value_event": row["value_event"],
                "value_boolean": row["value_boolean"],
            }
            for row in rows
            if row["time"] is not None
        }


def _definition_to_dict(row: SignalDefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "value_kind": row.value_kind,
        "unit": row.unit,
        "categorical_values": (
            list(row.categorical_values) if row.categorical_values is not None else None
        ),
        "value_min": row.value_min,
        "value_max": row.value_max,
        "attachment_allowed": row.attachment_allowed,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _assignment_to_dict(row: SignalAssignment) -> dict[str, Any]:
    return {
        "id": row.id,
        "signal_definition_id": row.signal_definition_id,
        "farm_id": row.farm_id,
        "block_id": row.block_id,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# Hint to silence "imported but unused" — JSON helper kept for future
# value-event rich payloads that may need round-tripping.
_ = json
