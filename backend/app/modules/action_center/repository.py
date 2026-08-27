"""Unified reads over ``recommendations`` + ``alerts``.

Why one SQL statement and not two calls merged in Python: the screen sorts by
urgency across both kinds and pages the result. Merging two independently
limited lists client-side gives a page that is neither the top N of the union
nor stable as you page — the classic wrong answer. So the union happens in the
database, where the sort and the limit can both be honest.

The two tables are not symmetric and the query has to bridge that:

* ``alerts`` has no ``farm_id`` — it is farm-scoped through its block, so the
  join to ``blocks`` is load-bearing, not decoration.
* ``recommendations`` carries ``tree_code``/``version``/``confidence`` as
  columns; an alert's provenance is encoded in ``rule_code`` as
  ``tree:<code>:<leaf>`` and is split out here.
* cell geometry lives in ``grid_cells``; both tables carry only ``cell_id``.

Since tenant migration 0079 both tables also carry a group parent and its
per-cell members. Only parents and ungrouped items are listed here: a member is
one cell's evidence under a finding the parent already states, and listing both
would put the same sentence on the screen once per cell — the noise the
grouping exists to remove. `list_members` is how the drill-down asks for them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Native -> unified status. The only place this mapping exists.
#
# `deferred` and `expired` land in `dismissed` with the rest of the closed-
# without-doing-it states: they are off the supervisor's plate today, which is
# what the tab means. `native_status` still travels on every row, so a deferred
# item remains distinguishable from a dismissed one in the UI.
_REC_STATUS = {
    "open": "needs_action",
    "applied": "done",
    "dismissed": "dismissed",
    "deferred": "dismissed",
    "expired": "dismissed",
}
_ALERT_STATUS = {
    "open": "needs_action",
    "acknowledged": "dispatched",
    "resolved": "done",
    "snoozed": "dismissed",
}


def unified_status(kind: str, native: str, *, has_assignee: bool) -> str:
    """Fold a native state into the queue's four-state vocabulary.

    An assignee outranks the native state for anything still open: a
    recommendation that has been sent to a named person is no longer waiting
    for a supervisor's decision, even though its own table still says `open`.
    """
    base = (_REC_STATUS if kind == "recommendation" else _ALERT_STATUS).get(native, "needs_action")
    if has_assignee and base == "needs_action":
        return "dispatched"
    return base


# One row shape from two tables. Written as a UNION ALL of two SELECTs with
# identical column lists — Postgres will not union them otherwise, and the
# explicit casts keep the two sides' types from being inferred differently
# (a NULL literal on one side and a uuid on the other unions as text).
_UNIFIED = """
WITH cell_geo AS (
    SELECT
        gc.id,
        gc.row_idx,
        gc.col_idx,
        gc.area_m2,
        ST_Y(gc.centroid::geometry) AS lat,
        ST_X(gc.centroid::geometry) AS lon,
        ROW_NUMBER() OVER (
            PARTITION BY gc.grid_config_id ORDER BY gc.row_idx, gc.col_idx
        ) AS ordinal,
        COUNT(*) OVER (PARTITION BY gc.grid_config_id) AS total
    FROM grid_cells gc
),
items AS (
    SELECT
        r.id                          AS id,
        'recommendation'              AS kind,
        r.state                       AS native_status,
        r.farm_id                     AS farm_id,
        r.block_id                    AS block_id,
        r.cell_id                     AS cell_id,
        r.action_type                 AS action_type,
        r.severity                    AS severity,
        r.text_en                     AS title_en,
        r.text_ar                     AS title_ar,
        NULL::text                    AS detail_en,
        NULL::text                    AS detail_ar,
        r.tree_code                   AS tree_code,
        r.tree_version                AS tree_version,
        r.confidence                  AS confidence,
        r.created_at                  AS created_at,
        r.valid_until                 AS valid_until,
        r.actions                     AS actions,
        r.tree_path                   AS reasoning_path,
        NULL::jsonb                   AS signal_snapshot,
        NULL::text                    AS rule_code,
        -- Lifecycle timestamps. Each kind fills its own pair and leaves the
        -- other NULL: applying a recommendation and resolving an alert are
        -- different events and must not share one column.
        NULL::timestamptz             AS acknowledged_at,
        NULL::timestamptz             AS resolved_at,
        r.applied_at                  AS applied_at,
        r.dismissed_at                AS dismissed_at,
        r.deferred_until              AS deferred_until,
        NULL::timestamptz             AS snoozed_until,
        r.is_group                    AS is_group,
        r.member_count                AS member_count,
        r.previous_member_count       AS previous_member_count,
        r.occurrence_count            AS occurrence_count,
        r.day_streak                  AS day_streak,
        r.first_seen_at               AS first_seen_at,
        r.last_seen_at                AS last_seen_at
    FROM recommendations r
    WHERE r.deleted_at IS NULL AND r.group_parent_id IS NULL
    UNION ALL
    SELECT
        a.id                          AS id,
        'alert'                       AS kind,
        a.status                      AS native_status,
        b.farm_id                     AS farm_id,
        a.block_id                    AS block_id,
        a.cell_id                     AS cell_id,
        a.action_type                 AS action_type,
        a.severity                    AS severity,
        COALESCE(a.diagnosis_en, a.rule_code) AS title_en,
        a.diagnosis_ar                AS title_ar,
        a.prescription_en             AS detail_en,
        a.prescription_ar             AS detail_ar,
        -- Provenance for a tree-sourced alert is encoded in the rule_code as
        -- `tree:<code>:<leaf>`; legacy rule alerts have no tree and stay NULL.
        CASE WHEN split_part(a.rule_code, ':', 1) = 'tree'
             THEN split_part(a.rule_code, ':', 2) END AS tree_code,
        NULL::integer                 AS tree_version,
        1.0::numeric                  AS confidence,
        a.created_at                  AS created_at,
        NULL::timestamptz             AS valid_until,
        '{}'::jsonb                   AS actions,
        NULL::jsonb                   AS reasoning_path,
        a.signal_snapshot             AS signal_snapshot,
        a.rule_code                   AS rule_code,
        a.acknowledged_at             AS acknowledged_at,
        a.resolved_at                 AS resolved_at,
        NULL::timestamptz             AS applied_at,
        NULL::timestamptz             AS dismissed_at,
        NULL::timestamptz             AS deferred_until,
        a.snoozed_until               AS snoozed_until,
        a.is_group                    AS is_group,
        a.member_count                AS member_count,
        a.previous_member_count       AS previous_member_count,
        a.occurrence_count            AS occurrence_count,
        a.day_streak                  AS day_streak,
        a.first_seen_at               AS first_seen_at,
        a.last_seen_at                AS last_seen_at
    FROM alerts a
    JOIN blocks b ON b.id = a.block_id
    WHERE a.deleted_at IS NULL AND a.group_parent_id IS NULL
)
SELECT
    i.*,
    bl.code                AS block_code,
    bl.name                AS block_name,
    bl.name_ar             AS block_name_ar,
    bl.agronomist_membership_id AS responsible_membership_id,
    cg.row_idx, cg.col_idx, cg.lat, cg.lon, cg.area_m2,
    cg.ordinal, cg.total,
    act.id                 AS activity_id,
    act.assigned_membership_id AS assigned_membership_id,
    act.scheduled_date     AS scheduled_date
FROM items i
JOIN blocks bl ON bl.id = i.block_id
LEFT JOIN cell_geo cg ON cg.id = i.cell_id
-- Newest linked activity wins: re-dispatching an item writes a second
-- activity rather than mutating the first, so the audit trail keeps both.
LEFT JOIN LATERAL (
    SELECT pa.id, pa.assigned_membership_id, pa.scheduled_date
    FROM plan_activities pa
    WHERE pa.deleted_at IS NULL
      AND (
        (i.kind = 'recommendation' AND pa.recommendation_id = i.id)
        OR (i.kind = 'alert' AND pa.id = (
             SELECT a2.prescription_activity_id FROM alerts a2 WHERE a2.id = i.id
        ))
      )
    ORDER BY pa.created_at DESC
    LIMIT 1
) act ON TRUE
WHERE i.farm_id = :farm_id
"""


class ActionCenterRepository:
    """Read side of the Action Center. Tenant session only."""

    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._tenant = tenant_session

    async def list_items(
        self,
        *,
        farm_id: UUID,
        kinds: tuple[str, ...] = (),
        block_id: UUID | None = None,
        action_types: tuple[str, ...] = (),
        severities: tuple[str, ...] = (),
        native_statuses: tuple[str, ...] = (),
        assigned_membership_id: UUID | None = None,
        raised_from: datetime | None = None,
        raised_to: datetime | None = None,
        limit: int = 500,
    ) -> tuple[dict[str, Any], ...]:
        sql = _UNIFIED
        params: dict[str, Any] = {"farm_id": farm_id, "limit": limit}
        binds = [bindparam("farm_id", type_=PG_UUID(as_uuid=True))]

        if kinds:
            sql += " AND i.kind = ANY(:kinds)"
            params["kinds"] = list(kinds)
        if block_id is not None:
            sql += " AND i.block_id = :block_id"
            params["block_id"] = block_id
            binds.append(bindparam("block_id", type_=PG_UUID(as_uuid=True)))
        if action_types:
            sql += " AND i.action_type = ANY(:action_types)"
            params["action_types"] = list(action_types)
        if severities:
            sql += " AND i.severity = ANY(:severities)"
            params["severities"] = list(severities)
        # The row's own state, not the unified one. A single tab holds
        # `deferred`, `expired`, `snoozed` and `dismissed`, so without this
        # there is no way to ask for one of them.
        if native_statuses:
            sql += " AND i.native_status = ANY(:native_statuses)"
            params["native_statuses"] = list(native_statuses)
        if assigned_membership_id is not None:
            sql += " AND act.assigned_membership_id = :assignee"
            params["assignee"] = assigned_membership_id
            binds.append(bindparam("assignee", type_=PG_UUID(as_uuid=True)))
        # Bound as real datetimes, never as strings: a text bind on a
        # timestamptz comparison is the shape that has bitten this codebase
        # repeatedly, and it also costs the index.
        if raised_from is not None:
            sql += " AND i.created_at >= :raised_from"
            params["raised_from"] = raised_from
        if raised_to is not None:
            sql += " AND i.created_at <= :raised_to"
            params["raised_to"] = raised_to

        sql += """
        ORDER BY
            CASE i.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            i.created_at DESC
        LIMIT :limit
        """
        stmt = text(sql).bindparams(*binds)
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return tuple(dict(r) for r in rows)

    async def get_item(self, *, farm_id: UUID, item_id: UUID) -> dict[str, Any] | None:
        sql = _UNIFIED + " AND i.id = :item_id LIMIT 1"
        stmt = text(sql).bindparams(
            bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
            bindparam("item_id", type_=PG_UUID(as_uuid=True)),
        )
        row = (
            (await self._tenant.execute(stmt, {"farm_id": farm_id, "item_id": item_id}))
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    # One statement per table rather than a UNION: the caller has already
    # resolved which kind the parent is (it came off a listed row), so unioning
    # would read the other table for nothing on every drill-down.
    _MEMBERS = {
        "recommendation": """
            SELECT r.id, r.cell_id, r.severity, r.state AS native_status,
                   NULL::text AS rule_code,
                   r.text_en, r.text_ar, r.created_at, r.last_seen_at,
                   r.cleared_at, r.occurrence_count, r.day_streak,
                   gc.row_idx, gc.col_idx, gc.area_m2,
                   ST_Y(gc.centroid::geometry) AS lat,
                   ST_X(gc.centroid::geometry) AS lon,
                   ROW_NUMBER() OVER (ORDER BY gc.row_idx, gc.col_idx) AS ordinal,
                   COUNT(*) OVER () AS total
              FROM recommendations r
              LEFT JOIN grid_cells gc ON gc.id = r.cell_id
             WHERE r.group_parent_id = :parent_id AND r.deleted_at IS NULL
             ORDER BY (r.cleared_at IS NOT NULL), gc.row_idx, gc.col_idx
        """,
        "alert": """
            SELECT a.id, a.cell_id, a.severity, a.status AS native_status,
                   a.rule_code,
                   a.diagnosis_en AS text_en, a.diagnosis_ar AS text_ar,
                   a.created_at, a.last_seen_at,
                   a.cleared_at, a.occurrence_count, a.day_streak,
                   gc.row_idx, gc.col_idx, gc.area_m2,
                   ST_Y(gc.centroid::geometry) AS lat,
                   ST_X(gc.centroid::geometry) AS lon,
                   ROW_NUMBER() OVER (ORDER BY gc.row_idx, gc.col_idx) AS ordinal,
                   COUNT(*) OVER () AS total
              FROM alerts a
              LEFT JOIN grid_cells gc ON gc.id = a.cell_id
             WHERE a.group_parent_id = :parent_id AND a.deleted_at IS NULL
             ORDER BY (a.cleared_at IS NOT NULL), gc.row_idx, gc.col_idx
        """,
    }

    async def list_members(self, *, kind: str, parent_id: UUID) -> tuple[dict[str, Any], ...]:
        """The per-cell rows behind one group card.

        Cleared members are returned too, sorted after the live ones and
        carrying their `cleared_at`. A shrinking outbreak and one that never
        spread look identical if the cells that have gone quiet are simply
        dropped.
        """
        sql = self._MEMBERS.get(kind)
        if sql is None:
            return ()
        rows = (
            (
                await self._tenant.execute(
                    text(sql).bindparams(bindparam("parent_id", type_=PG_UUID(as_uuid=True))),
                    {"parent_id": parent_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def membership_subject(self, *, membership_id: UUID) -> UUID | None:
        """The Keycloak subject behind a membership.

        The board addresses people by membership id; a scouting visit's
        `assigned_to` is the subject carried in the JWT. They are different
        UUIDs for the same person, `assigned_to` has no FK, and sending the
        wrong one produces a visit that reads as assigned in the database and
        appears on nobody's phone. Hence an explicit translation rather than
        passing the membership through and hoping.
        """
        stmt = text(
            "SELECT u.keycloak_subject::uuid FROM public.users u "
            "JOIN public.tenant_memberships m ON m.user_id = u.id "
            "WHERE m.id = :m"
        ).bindparams(bindparam("m", type_=PG_UUID(as_uuid=True)))
        return (await self._tenant.execute(stmt, {"m": membership_id})).scalar_one_or_none()

    async def block_responsible(self, *, block_id: UUID) -> UUID | None:
        stmt = text("SELECT agronomist_membership_id FROM blocks WHERE id = :b").bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True))
        )
        return (await self._tenant.execute(stmt, {"b": block_id})).scalar_one_or_none()

    async def any_farm_member(self, *, farm_id: UUID) -> UUID | None:
        """Fallback assignee when a block names nobody.

        Deterministic (lowest membership id) rather than random: a dispatch
        that lands on a different person each time it is retried is worse than
        one that is merely arbitrary, and the caller is told it defaulted.
        """
        stmt = text(
            """
            SELECT membership_id FROM farm_scopes
            WHERE farm_id = :f AND revoked_at IS NULL
            ORDER BY membership_id
            LIMIT 1
            """
        ).bindparams(bindparam("f", type_=PG_UUID(as_uuid=True)))
        return (await self._tenant.execute(stmt, {"f": farm_id})).scalar_one_or_none()

    async def link_alert_activity(self, *, alert_id: UUID, activity_id: UUID) -> None:
        stmt = text("UPDATE alerts SET prescription_activity_id = :act WHERE id = :a").bindparams(
            bindparam("act", type_=PG_UUID(as_uuid=True)),
            bindparam("a", type_=PG_UUID(as_uuid=True)),
        )
        await self._tenant.execute(stmt, {"act": activity_id, "a": alert_id})


__all__ = ["ActionCenterRepository", "unified_status", "date"]
