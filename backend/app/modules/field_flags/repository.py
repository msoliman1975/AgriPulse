"""Async DB access for field flags. Internal to the module.

All three tables are tenant-scoped, so the caller binds the session to the
right schema via `SET LOCAL search_path` before calling in — the same contract
every other tenant module uses.

Raw SQL rather than the ORM for the same reason scouting uses it: `point` is a
PostGIS geometry and has to be rendered as GeoJSON on the way out. Every bind
is a real UUID / datetime object rather than a string; a `CAST(:x AS uuid)`
with a string bind has taken this platform down three times in one day.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# `is_pinned` is derived here rather than stored: it is a comparison against
# now(), and a stored copy would be wrong the moment the clock moved.
_FLAG_COLUMNS = """
    f.id, f.farm_id, f.block_id, b.name AS block_name, b.code AS block_code,
    f.note, f.severity, f.status,
    CASE WHEN f.point IS NULL THEN NULL
         ELSE ST_AsGeoJSON(f.point)::jsonb END AS point,
    f.accuracy_m, f.pin_until, (f.pin_until > now()) AS is_pinned,
    f.raised_by, f.closed_at, f.closed_by, f.close_reason,
    f.created_at, f.updated_at,
    (SELECT count(*) FROM field_flag_comments c WHERE c.flag_id = f.id) AS comment_count
"""

_FLAG_FROM = "field_flags f JOIN blocks b ON b.id = f.block_id"


class FieldFlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Reads -------------------------------------------------------------

    async def list_flags(
        self,
        *,
        farm_id: UUID,
        open_only: bool = False,
        pinned_only: bool = False,
        limit: int = 500,
    ) -> tuple[dict[str, Any], ...]:
        """Flags on a farm, newest first.

        `pinned_only` is what the map layer asks for; the panel asks without
        it, because a flag whose pin has expired is still open work and still
        belongs in a list.
        """
        clauses = ["f.farm_id = :farm_id"]
        if open_only:
            clauses.append("f.status = 'open'")
        if pinned_only:
            clauses.append("f.pin_until > now()")
        sql = (
            f"SELECT {_FLAG_COLUMNS} FROM {_FLAG_FROM} "  # noqa: S608
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY f.created_at DESC LIMIT :limit"
        )
        rows = (
            await self._session.execute(
                text(sql).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id, "limit": limit},
            )
        ).mappings()
        return tuple(dict(r) for r in rows)

    async def get_flag(self, *, flag_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._session.execute(
                text(
                    f"SELECT {_FLAG_COLUMNS} FROM {_FLAG_FROM} WHERE f.id = :id"  # noqa: S608
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": flag_id},
            )
        ).mappings()
        first = row.first()
        return dict(first) if first else None

    async def list_photos(self, *, flag_id: UUID) -> tuple[dict[str, Any], ...]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT id, attachment_s3_key, created_at FROM field_flag_photos "
                    "WHERE flag_id = :id ORDER BY created_at"
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": flag_id},
            )
        ).mappings()
        return tuple(dict(r) for r in rows)

    async def list_comments(self, *, flag_id: UUID) -> tuple[dict[str, Any], ...]:
        """The thread, oldest first — it is a conversation, so it reads down.

        `author_name` is resolved from `public.users` by a join rather than an
        FK; a real foreign key from a tenant schema into public would make
        dropping that schema take an ACCESS EXCLUSIVE lock platform-wide.
        """
        rows = (
            await self._session.execute(
                text(
                    "SELECT c.id, c.body, c.author_id, u.full_name AS author_name, "
                    "       c.kind, c.created_at "
                    "  FROM field_flag_comments c "
                    "  LEFT JOIN public.users u ON u.id = c.author_id "
                    " WHERE c.flag_id = :id ORDER BY c.created_at"
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": flag_id},
            )
        ).mappings()
        return tuple(dict(r) for r in rows)

    async def resolve_names(self, *, user_ids: list[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        rows = (
            await self._session.execute(
                text("SELECT id, full_name FROM public.users WHERE id = ANY(:ids)").bindparams(
                    bindparam("ids", type_=PG_UUID(as_uuid=True), expanding=False)
                ),
                {"ids": user_ids},
            )
        ).mappings()
        return {r["id"]: r["full_name"] for r in rows}

    async def pin_days_for_farm(self, *, farm_id: UUID) -> int:
        """The farm's flag lifetime, in days.

        Falls back to 14 rather than raising: a farm created before this
        column existed should still be able to take a flag.
        """
        row = (
            await self._session.execute(
                text(
                    "SELECT COALESCE(default_field_flag_pin_days, 14) AS d "
                    "FROM farms WHERE id = :id"
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": farm_id},
            )
        ).first()
        return int(row.d) if row else 14

    # ---- Writes ------------------------------------------------------------

    async def insert_flag(self, *, values: dict[str, Any]) -> UUID:
        point_sql = (
            "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            if values.get("lat") is not None
            else "NULL"
        )
        sql = (
            "INSERT INTO field_flags "  # noqa: S608
            "  (farm_id, block_id, note, severity, point, accuracy_m, pin_until, raised_by) "
            f"VALUES (:farm_id, :block_id, :note, :severity, {point_sql}, "
            "         :accuracy_m, :pin_until, :raised_by) "
            "RETURNING id"
        )
        row = (
            await self._session.execute(
                text(sql).bindparams(
                    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("raised_by", type_=PG_UUID(as_uuid=True)),
                ),
                values,
            )
        ).first()
        assert row is not None
        return UUID(str(row.id))

    async def insert_photos(self, *, flag_id: UUID, keys: list[str]) -> None:
        if not keys:
            return
        await self._session.execute(
            text(
                "INSERT INTO field_flag_photos (flag_id, attachment_s3_key) "
                "SELECT :flag_id, unnest(CAST(:keys AS text[]))"
            ).bindparams(bindparam("flag_id", type_=PG_UUID(as_uuid=True))),
            {"flag_id": flag_id, "keys": keys},
        )

    async def insert_comment(
        self, *, flag_id: UUID, body: str, author_id: UUID, kind: str = "comment"
    ) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text(
                    "INSERT INTO field_flag_comments (flag_id, body, author_id, kind) "
                    "VALUES (:flag_id, :body, :author_id, :kind) "
                    "RETURNING id, body, author_id, kind, created_at"
                ).bindparams(
                    bindparam("flag_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("author_id", type_=PG_UUID(as_uuid=True)),
                ),
                {"flag_id": flag_id, "body": body, "author_id": author_id, "kind": kind},
            )
        ).mappings()
        first = row.first()
        assert first is not None
        return dict(first)

    async def close_flag(self, *, flag_id: UUID, reason: str, closed_by: UUID) -> None:
        await self._session.execute(
            text(
                "UPDATE field_flags SET status = 'closed', close_reason = :reason, "
                "       closed_by = :closed_by, closed_at = now(), updated_at = now() "
                " WHERE id = :id AND status = 'open'"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("closed_by", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": flag_id, "reason": reason, "closed_by": closed_by},
        )

    async def reopen_flag(self, *, flag_id: UUID, pin_until: datetime) -> None:
        """Re-opening restarts the pin lifetime.

        A closed pin stays on the map for its full period and a flag may be
        re-opened at any time, including after that period ended. Without the
        new `pin_until` the result is an open flag with no pin — open work
        nobody can see.
        """
        await self._session.execute(
            text(
                "UPDATE field_flags SET status = 'open', close_reason = NULL, "
                "       closed_by = NULL, closed_at = NULL, pin_until = :pin_until, "
                "       updated_at = now() "
                " WHERE id = :id AND status = 'closed'"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": flag_id, "pin_until": pin_until},
        )
