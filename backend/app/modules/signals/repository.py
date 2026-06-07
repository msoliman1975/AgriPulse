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

from sqlalchemy import ColumnElement, String, bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.signals.errors import (
    SignalCodeAlreadyExistsError,
    SignalLocationOutsideBlockError,
    SignalTemplateCodeAlreadyExistsError,
)
from app.modules.signals.models import (
    SignalAssignment,
    SignalDefinition,
    SignalTemplate,
    SignalTemplateDefinition,
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
        stmt = select(SignalDefinition).where(*clauses).order_by(SignalDefinition.code.asc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_definition_to_dict(r) for r in rows)

    async def get_definition(
        self, *, definition_id: UUID | None = None, code: str | None = None
    ) -> dict[str, Any] | None:
        clauses: list[ColumnElement[bool]] = [SignalDefinition.deleted_at.is_(None)]
        if definition_id is not None:
            clauses.append(SignalDefinition.id == definition_id)
        elif code is not None:
            clauses.append(SignalDefinition.code == code)
        else:
            raise ValueError("must provide definition_id or code")
        row = (
            (await self._session.execute(select(SignalDefinition).where(*clauses)))
            .scalars()
            .one_or_none()
        )
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
        aggregation: str = "latest",
        aggregation_window_days: int | None = None,
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
                        aggregation, aggregation_window_days,
                        created_by, updated_by
                    ) VALUES (
                        :id, :code, :name, :description, :value_kind, :unit,
                        :categorical_values, :value_min, :value_max,
                        :attachment_allowed, TRUE,
                        :aggregation, :aggregation_window_days,
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
                    "aggregation": aggregation,
                    "aggregation_window_days": aggregation_window_days,
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
            # CS-1 D3 — clients can change the rule + window on existing
            # definitions; service layer is responsible for coercing
            # non-numeric value_kinds to 'latest' before calling in.
            "aggregation",
            "aggregation_window_days",
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
                f"UPDATE signal_definitions SET {', '.join(sets)} "
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

    async def list_assignments(self, *, definition_id: UUID) -> tuple[dict[str, Any], ...]:
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
            (
                await self._session.execute(
                    select(SignalAssignment).where(SignalAssignment.id == assignment_id)
                )
            )
            .scalars()
            .one()
        )
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

    # ---- Templates (CS-2/3) -------------------------------------------
    #
    # Templates group N SignalDefinitions for entry UX (D1). Member
    # uniqueness within a template is DB-enforced via the two unique
    # constraints in migration 0029 (one on template_id+definition_id,
    # one on template_id+position). The service layer pre-checks both
    # so we can raise a tidy 400 instead of relying on IntegrityError
    # text matching for two different constraints.

    async def list_templates(self, *, include_inactive: bool = False) -> tuple[dict[str, Any], ...]:
        clauses = [SignalTemplate.deleted_at.is_(None)]
        if not include_inactive:
            clauses.append(SignalTemplate.is_active.is_(True))
        stmt = select(SignalTemplate).where(*clauses).order_by(SignalTemplate.code.asc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_template_to_dict(r) for r in rows)

    async def get_template(self, *, template_id: UUID) -> dict[str, Any] | None:
        stmt = select(SignalTemplate).where(
            SignalTemplate.id == template_id,
            SignalTemplate.deleted_at.is_(None),
        )
        row = (await self._session.execute(stmt)).scalars().one_or_none()
        return _template_to_dict(row) if row is not None else None

    async def get_template_members(self, *, template_id: UUID) -> tuple[dict[str, Any], ...]:
        """Returns members ordered by `position` ascending."""
        stmt = (
            select(SignalTemplateDefinition)
            .where(SignalTemplateDefinition.template_id == template_id)
            .order_by(SignalTemplateDefinition.position.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(_template_member_to_dict(r) for r in rows)

    async def insert_template(
        self,
        *,
        template_id: UUID,
        code: str,
        name: str,
        description: str | None,
        members: tuple[tuple[UUID, int, bool], ...],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Atomic: insert the template row then its N members.

        Caller wraps in their own transaction. On code collision we
        raise SignalTemplateCodeAlreadyExistsError; member-side
        violations are pre-checked by the service layer (see class
        docstring), so an IntegrityError here is unexpected.
        """
        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO signal_templates (
                        id, code, name, description,
                        is_active, created_by, updated_by
                    ) VALUES (
                        :id, :code, :name, :description,
                        TRUE, :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": template_id,
                    "code": code,
                    "name": name,
                    "description": description,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if "uq_signal_templates_code_alive" in str(exc):
                raise SignalTemplateCodeAlreadyExistsError(code) from exc
            raise
        await self._insert_template_members(template_id=template_id, members=members)
        await self._session.flush()
        out = await self.get_template(template_id=template_id)
        if out is None:
            raise RuntimeError("Template insert succeeded but row is missing")
        return out

    async def update_template(
        self,
        *,
        template_id: UUID,
        updates: dict[str, Any],
        members: tuple[tuple[UUID, int, bool], ...] | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        """Patch template scalars + optionally replace the member list
        atomically (delete-then-insert). `members=None` leaves members
        untouched."""
        allowed = {"name", "description", "is_active"}
        sets: list[str] = []
        params: dict[str, Any] = {"id": template_id, "actor": actor_user_id}
        for col, value in updates.items():
            if col not in allowed:
                continue
            sets.append(f"{col} = :{col}")
            params[col] = value
        if sets:
            sets.extend(["updated_at = now()", "updated_by = :actor"])
            await self._session.execute(
                text(
                    f"UPDATE signal_templates SET {', '.join(sets)} "
                    "WHERE id = :id AND deleted_at IS NULL"
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                params,
            )
        if members is not None:
            await self._session.execute(
                text("DELETE FROM signal_template_definitions WHERE template_id = :id").bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True))
                ),
                {"id": template_id},
            )
            await self._insert_template_members(template_id=template_id, members=members)
        return await self.get_template(template_id=template_id)

    async def soft_delete_template(self, *, template_id: UUID, actor_user_id: UUID | None) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE signal_templates "
                "SET deleted_at = now(), updated_by = :actor, updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": template_id, "actor": actor_user_id},
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    async def missing_definitions(self, *, definition_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Return the subset of ids that don't exist (or are soft-deleted).
        Empty tuple means everything resolves; service raises a 400 otherwise.
        (Not named `assert_*` to avoid collision with Mock's auto-protected
        assertion helpers in tests.)"""
        if not definition_ids:
            return ()
        stmt = select(SignalDefinition.id).where(
            SignalDefinition.id.in_(definition_ids),
            SignalDefinition.deleted_at.is_(None),
        )
        present = set((await self._session.execute(stmt)).scalars().all())
        return tuple(d for d in definition_ids if d not in present)

    async def _insert_template_members(
        self,
        *,
        template_id: UUID,
        members: tuple[tuple[UUID, int, bool], ...],
    ) -> None:
        # Bulk INSERT — VALUES list with one row per member. Empty
        # members tuple is a no-op (the create-request schema enforces
        # min_length=1 but an update-request may legitimately replace
        # with an empty list; UX layer is expected to reject that).
        if not members:
            return
        # SQLAlchemy text-based VALUES expansion needs distinct param
        # names per row.
        value_rows = []
        params: dict[str, Any] = {"template_id": template_id}
        binds: list[Any] = [bindparam("template_id", type_=PG_UUID(as_uuid=True))]
        for i, (def_id, position, is_required) in enumerate(members):
            value_rows.append(f"(:def_id_{i}, :template_id, :position_{i}, :is_required_{i})")
            params[f"def_id_{i}"] = def_id
            params[f"position_{i}"] = position
            params[f"is_required_{i}"] = is_required
            binds.append(bindparam(f"def_id_{i}", type_=PG_UUID(as_uuid=True)))
        await self._session.execute(
            text(
                "INSERT INTO signal_template_definitions "
                "(signal_definition_id, template_id, position, is_required) "
                f"VALUES {', '.join(value_rows)}"
            ).bindparams(*binds),
            params,
        )

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
        # CS-1 / CS-4 additive params. Defaults preserve the pre-CS-1
        # call shape so existing one-shot observations keep working
        # without code changes elsewhere. Location_point WKT is
        # rendered as `POINT(lon lat)` by the service layer; the
        # ST_Within trigger from migration 0029 enforces the
        # within-block constraint when location_mode='point_in_entity'.
        template_observation_id: UUID | None = None,
        location_mode: str = "entity",
        location_point_wkt: str | None = None,
    ) -> None:
        stmt = text(
            """
                INSERT INTO signal_observations (
                    time, id, signal_definition_id, farm_id, block_id,
                    value_numeric, value_categorical, value_event, value_boolean,
                    value_geopoint, attachment_s3_key, notes, recorded_by,
                    template_observation_id, location_mode, location_point
                ) VALUES (
                    :time, :id, :def_id, :farm_id, :block_id,
                    :value_numeric, :value_categorical, :value_event, :value_boolean,
                    CASE WHEN :geopoint IS NULL THEN NULL
                         ELSE ST_GeomFromText(:geopoint, 4326) END,
                    :attachment_s3_key, :notes, :recorded_by,
                    :template_observation_id, :location_mode,
                    CASE WHEN :location_point IS NULL THEN NULL
                         ELSE ST_GeomFromText(:location_point, 4326) END
                )
                """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("def_id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("recorded_by", type_=PG_UUID(as_uuid=True)),
            bindparam("template_observation_id", type_=PG_UUID(as_uuid=True)),
            # asyncpg can't infer the type of a bare NULL used only in
            # "CASE WHEN :geopoint IS NULL ... ST_GeomFromText(:geopoint)"
            # (the PostGIS overload leaves it ambiguous). Pin both WKT
            # params to text so the prepared statement type-checks when
            # the observation has no point (the common numeric case).
            bindparam("geopoint", type_=String()),
            bindparam("location_point", type_=String()),
        )
        params = {
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
            "template_observation_id": template_observation_id,
            "location_mode": location_mode,
            "location_point": location_point_wkt,
        }
        try:
            await self._session.execute(stmt, params)
        except DBAPIError as exc:
            # The ST_Within trigger (migration 0029) RAISEs when a
            # `point_in_entity` point falls outside the block boundary.
            # Translate that into a clean 422 instead of a generic 500.
            if "is not within block" in str(getattr(exc, "orig", exc) or exc):
                raise SignalLocationOutsideBlockError(
                    block_id=str(block_id) if block_id else None
                ) from exc
            raise

    async def list_observations(
        self,
        *,
        signal_definition_id: UUID | None = None,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        template_observation_id: UUID | None = None,
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
        if template_observation_id is not None:
            # CS-5: lets the FE fetch every sibling of a template
            # submission in one query — the lead row plus its peers.
            clauses.append("o.template_observation_id = :template_observation_id")
            params["template_observation_id"] = template_observation_id
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT o.id, o.time, o.signal_definition_id, "
            "       d.code AS signal_code, "
            "       o.farm_id, o.block_id, "
            "       o.value_numeric, o.value_categorical, o.value_event, o.value_boolean, "
            "       CASE WHEN o.value_geopoint IS NULL THEN NULL "
            "            ELSE ST_AsGeoJSON(o.value_geopoint)::jsonb END AS value_geopoint_geojson, "
            "       o.attachment_s3_key, o.notes, o.recorded_by, o.inserted_at, "
            # CS-5: surface the CS-1 columns on the read path so existing
            # FE consumers can render them (defaults preserve old shape
            # — entity-mode rows just emit NULL for location_point).
            "       o.location_mode, "
            "       CASE WHEN o.location_point IS NULL THEN NULL "
            "            ELSE ST_AsGeoJSON(o.location_point)::jsonb END AS location_point_geojson, "
            "       o.template_observation_id "
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
            (
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
            )
            .mappings()
            .all()
        )
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
        # CS-1 D3 — round-tripped from DB to API. Defaults applied by
        # migration 0029's server_default so pre-CS-1 rows surface as
        # ('latest', None) on read.
        "aggregation": row.aggregation,
        "aggregation_window_days": row.aggregation_window_days,
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


def _template_to_dict(row: SignalTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _template_member_to_dict(row: SignalTemplateDefinition) -> dict[str, Any]:
    return {
        "signal_definition_id": row.signal_definition_id,
        "position": row.position,
        "is_required": row.is_required,
    }


# Hint to silence "imported but unused" — JSON helper kept for future
# value-event rich payloads that may need round-tripping.
_ = json
