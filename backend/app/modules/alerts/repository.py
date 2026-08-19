"""Async DB access for the alerts module. Internal to the module.

Stage 2 of the rules sunset: this repository now holds only the alert
lifecycle methods (insert, list, get, transition). The rule-catalog
methods (`list_default_rules`, `list_overrides`, `list_tenant_rules`,
etc.) and the cross-module signal loaders (`get_latest_aggregate_per_index`,
`get_block_farm_id`, `get_block_crop_category`, `list_active_block_ids`)
were removed when the rules engine retired. The recommendations engine
now owns signal loading + tree evaluation; tree leaves with
``kind: alert`` insert rows here via
``recommendations.service._open_alert_from_tree`` (PR-E).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert
from app.shared.action_items import ALERT_SQL, TENANT_TODAY_SQL

# Alert lifecycle values that still count as live. Kept as one SQL fragment
# so the dedup predicate, the group lookups and the cascade cannot disagree
# about what "still open" means.
_ACTIVE = ALERT_SQL.active


def _serialize_jsonb(value: dict[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value)


class AlertsRepository:
    """Internal repository — service is the only consumer.

    Holds the alert lifecycle CRUD only. Both legacy rule-sourced
    alerts (now retired) and tree-sourced alerts (PR-E) wrote/write
    into the same ``alerts`` table; this repo doesn't care about the
    source.
    """

    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        # Kept on the API surface for backwards compatibility with the
        # service constructor; no method here uses the public session
        # after Stage 2 (rule catalog reads are gone).
        self._public = public_session

    # ---- Alerts (tenant) ----------------------------------------------

    async def insert_alert(
        self,
        *,
        alert_id: UUID,
        block_id: UUID,
        cell_id: UUID | None = None,
        rule_code: str,
        severity: str,
        action_type: str | None = None,
        diagnosis_en: str | None,
        diagnosis_ar: str | None,
        prescription_en: str | None,
        prescription_ar: str | None,
        prescription_activity_id: UUID | None,
        signal_snapshot: dict[str, Any] | None,
        actor_user_id: UUID | None,
        group_key: str | None = None,
        group_parent_id: UUID | None = None,
        is_group: bool = False,
        today: date | None = None,
    ) -> bool:
        """Open one alert. Returns True if a row was inserted, False if
        the partial UNIQUE on (block_id, rule_code) blocked it (an
        active alert already exists).

        Tree-sourced alerts pass ``rule_code`` of the form
        ``tree:<tree_code>:<leaf_node_id>`` so the same partial UNIQUE
        on ``(block_id, rule_code) WHERE status IN open/ack/snoozed``
        keeps re-evaluation idempotent without needing schema changes.
        """
        # Savepoint so an idempotent conflict (an active alert already exists
        # for this block[/cell] + rule_code) rolls back just this insert instead
        # of poisoning the surrounding sweep transaction.
        savepoint = await self._tenant.begin_nested()
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO alerts (
                        id, block_id, cell_id, rule_code, severity, action_type, status,
                        diagnosis_en, diagnosis_ar,
                        prescription_en, prescription_ar,
                        prescription_activity_id,
                        signal_snapshot, created_by, updated_by,
                        group_key, group_parent_id, is_group,
                        first_seen_at, last_seen_at, last_seen_day
                    ) VALUES (
                        :id, :block_id, :cell_id, :rule_code, :severity,
                        :action_type, 'open',
                        :diag_en, :diag_ar,
                        :pre_en, :pre_ar,
                        :prescription_activity_id,
                        CAST(:snapshot AS jsonb), :actor, :actor,
                        :group_key, :group_parent_id, :is_group,
                        now(), now(), CAST(:today AS date)
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("cell_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("prescription_activity_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    bindparam("group_parent_id", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": alert_id,
                    "block_id": block_id,
                    "cell_id": cell_id,
                    "rule_code": rule_code,
                    "severity": severity,
                    "action_type": action_type,
                    "diag_en": diagnosis_en,
                    "diag_ar": diagnosis_ar,
                    "pre_en": prescription_en,
                    "pre_ar": prescription_ar,
                    "prescription_activity_id": prescription_activity_id,
                    "snapshot": _serialize_jsonb(signal_snapshot),
                    "actor": actor_user_id,
                    "group_key": group_key,
                    "group_parent_id": group_parent_id,
                    "is_group": is_group,
                    "today": today,
                },
            )
            await savepoint.commit()
        except IntegrityError as exc:
            await savepoint.rollback()
            # Partial UNIQUE on (block_id, rule_code) WHERE status IN
            # open/ack/snoozed — re-firing while a prior alert is
            # active is a no-op by design.
            msg = str(exc)
            if "uq_alerts_block_rule_open" in msg or "uq_alerts_group_open" in msg:
                return False
            raise
        await self._tenant.flush()
        return True

    # ---- Grouping + recurrence (tenant migration 0079) ------------------
    #
    # The mirror of the recommendations side. Alerts differ in two ways that
    # leak into every statement here: the lifecycle column is `status` (with
    # three live values, not one), and there is no `tree_id` — provenance
    # lives in the synthesised `rule_code`, so a tree-scoped sweep has to key
    # off the first segment of `group_key` instead.

    async def tenant_today(self, *, tenant_schema: str) -> date:
        """Today in the tenant's own timezone — the boundary streaks are cut on.

        Same statement the recommendations repository runs, from the same
        constant: two tables whose day boundaries disagreed would give one
        finding two different streak counts depending on which half you read.
        """
        row = await self._public.execute(text(TENANT_TODAY_SQL), {"s": tenant_schema})
        return cast(date, row.scalar_one_or_none() or datetime.now(UTC).date())

    async def find_open_group_parent(self, *, block_id: UUID, group_key: str) -> UUID | None:
        return (
            await self._tenant.execute(
                text(
                    "SELECT id FROM alerts "  # noqa: S608 - _ACTIVE is a module constant
                    " WHERE block_id = :b AND group_key = :k AND is_group = TRUE "
                    f"   AND status IN ({_ACTIVE}) AND deleted_at IS NULL"
                ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
                {"b": block_id, "k": group_key},
            )
        ).scalar_one_or_none()

    async def find_open_alert(self, *, block_id: UUID, rule_code: str) -> UUID | None:
        """The alert the partial UNIQUE just refused to duplicate."""
        return (
            await self._tenant.execute(
                text(
                    "SELECT id FROM alerts "  # noqa: S608 - _ACTIVE is a module constant
                    " WHERE block_id = :b AND rule_code = :r "
                    f"   AND status IN ({_ACTIVE}) AND deleted_at IS NULL"
                ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
                {"b": block_id, "r": rule_code},
            )
        ).scalar_one_or_none()

    async def bump_recurrence(
        self, *, row_id: UUID, today: date, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        row = (
            (
                await self._tenant.execute(
                    text(ALERT_SQL.bump).bindparams(
                        bindparam("id", type_=PG_UUID(as_uuid=True)),
                        bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"id": row_id, "today": today, "actor": actor_user_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else {}

    async def attach_child(
        self,
        *,
        child_id: UUID,
        parent_id: UUID,
        group_key: str,
        diagnosis_en: str | None,
        diagnosis_ar: str | None,
        signal_snapshot: dict[str, Any] | None,
        today: date,
        actor_user_id: UUID | None,
        severity: str | None = None,
    ) -> None:
        """Re-point an already-active member at its group, refreshed.

        `severity` is updated when supplied because the member can legitimately
        change it between sweeps: the per-index dedup is `(block_id,
        rule_code)` with no severity in it, so an index that escalates from
        warning to critical keeps its original row and simply moves to the
        critical group. Leaving the row's own severity behind would put a
        warning member under a critical card.
        """
        await self._tenant.execute(
            text(
                """
                UPDATE alerts
                   SET group_parent_id = :parent, group_key = :key,
                       severity = COALESCE(:severity, severity),
                       diagnosis_en = :diag_en, diagnosis_ar = :diag_ar,
                       signal_snapshot = CAST(:snapshot AS jsonb),
                       cleared_at = NULL,
                       updated_at = now(), updated_by = :actor
                 WHERE id = :id
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("parent", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": child_id,
                "parent": parent_id,
                "key": group_key,
                "severity": severity,
                "diag_en": diagnosis_en,
                "diag_ar": diagnosis_ar,
                "snapshot": _serialize_jsonb(signal_snapshot),
                "actor": actor_user_id,
            },
        )
        await self.bump_recurrence(row_id=child_id, today=today, actor_user_id=actor_user_id)

    async def refresh_member_count(self, *, parent_id: UUID, today: date) -> int:
        return (
            await self._tenant.execute(
                text(ALERT_SQL.refresh_member_count).bindparams(
                    bindparam("parent_id", type_=PG_UUID(as_uuid=True))
                ),
                {"parent_id": parent_id, "today": today},
            )
        ).scalar_one_or_none() or 0

    async def clear_stale_children(
        self, *, block_id: UUID, tree_code: str, fired_ids: list[UUID]
    ) -> tuple[UUID, ...]:
        """Mark this tree's cells that did not fire in the pass just finished.

        Scoped by the `group_key` prefix rather than a tree id, because the
        alerts table has never had one — the tree code is the first segment of
        the key the engine writes, and matching on it keeps one tree's sweep
        from clearing another tree's group.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        ALERT_SQL.clear_stale_children("split_part(group_key, ':', 1) = :tree_code")
                    ).bindparams(
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("fired", type_=postgresql.ARRAY(PG_UUID(as_uuid=True))),
                    ),
                    {"block_id": block_id, "tree_code": tree_code, "fired": fired_ids},
                )
            )
            .scalars()
            .all()
        )
        return tuple(r for r in rows if r is not None)

    async def refresh_grid_member_counts(self, *, block_id: UUID, today: date) -> None:
        """Recount every live grid group on one block.

        Scoped to the block rather than to the group just written, because a
        member can MOVE between groups: an index that escalates from warning to
        critical leaves the warning card one member lighter, and nothing else
        in the sweep would ever go back and notice.
        """
        await self._tenant.execute(
            text(
                ALERT_SQL.refresh_member_counts_scoped("split_part(p.group_key, ':', 1) = 'grid'")
            ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
            {"block_id": block_id, "today": today},
        )

    async def refresh_member_counts_for_tree(
        self, *, block_id: UUID, tree_code: str, today: date
    ) -> None:
        await self._tenant.execute(
            text(
                ALERT_SQL.refresh_member_counts_scoped(
                    "split_part(p.group_key, ':', 1) = :tree_code"
                )
            ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
            {"block_id": block_id, "tree_code": tree_code, "today": today},
        )

    async def open_group_parent_ids(self, *, block_id: UUID, tree_code: str) -> tuple[UUID, ...]:
        rows = (
            (
                await self._tenant.execute(
                    text(
                        ALERT_SQL.open_parent_ids("split_part(group_key, ':', 1) = :tree_code")
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id, "tree_code": tree_code},
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    async def list_group_members(self, *, parent_id: UUID) -> tuple[dict[str, Any], ...]:
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT a.id, a.cell_id, a.severity, a.status AS state,
                               a.diagnosis_en AS text_en, a.diagnosis_ar AS text_ar,
                               a.created_at, a.last_seen_at, a.cleared_at,
                               a.occurrence_count, a.day_streak,
                               gc.row_idx, gc.col_idx, gc.area_m2,
                               ST_Y(gc.centroid::geometry) AS lat,
                               ST_X(gc.centroid::geometry) AS lon
                          FROM alerts a
                          LEFT JOIN grid_cells gc ON gc.id = a.cell_id
                         WHERE a.group_parent_id = :p AND a.deleted_at IS NULL
                         ORDER BY a.cleared_at NULLS FIRST, gc.row_idx, gc.col_idx
                        """
                    ).bindparams(bindparam("p", type_=PG_UUID(as_uuid=True))),
                    {"p": parent_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def cascade_children(
        self,
        *,
        parent_id: UUID,
        new_status: str,
        actor_user_id: UUID | None,
        snoozed_until: datetime | None = None,
    ) -> tuple[UUID, ...]:
        """Carry a parent's transition down to every still-active child.

        Children left open under a resolved parent would keep their per-cell
        dedup keys occupied and silently swallow the next real firing there.
        """
        sets = ["status = :status", "updated_at = now()", "updated_by = :actor"]
        if new_status == "acknowledged":
            sets += ["acknowledged_at = now()", "acknowledged_by = :actor", "snoozed_until = NULL"]
        elif new_status == "resolved":
            sets += ["resolved_at = now()", "resolved_by = :actor", "snoozed_until = NULL"]
        elif new_status == "snoozed":
            sets.append("snoozed_until = :snoozed_until")
        params: dict[str, Any] = {"p": parent_id, "status": new_status, "actor": actor_user_id}
        if new_status == "snoozed":
            params["snoozed_until"] = snoozed_until
        rows = (
            (
                await self._tenant.execute(
                    text(
                        f"UPDATE alerts SET {', '.join(sets)} "  # noqa: S608
                        f" WHERE group_parent_id = :p AND status IN ({_ACTIVE})"
                        "   AND deleted_at IS NULL"
                        " RETURNING id"
                    ).bindparams(
                        bindparam("p", type_=PG_UUID(as_uuid=True)),
                        bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    ),
                    params,
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    async def get_alert(self, *, alert_id: UUID) -> dict[str, Any] | None:
        stmt = select(Alert).where(Alert.id == alert_id, Alert.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).scalars().one_or_none()
        return _alert_to_dict(row) if row is not None else None

    async def list_alerts(
        self,
        *,
        block_id: UUID | None = None,
        farm_id: UUID | None = None,
        status_filter: tuple[str, ...] = (),
        severity_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        # Members of a group are excluded — the parent stands for them. See
        # `list_group_members` for the cells behind one.
        clauses = ["deleted_at IS NULL", "group_parent_id IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        if block_id is not None:
            clauses.append("block_id = :block_id")
            params["block_id"] = block_id
        if farm_id is not None:
            # SMK-RBAC-GAP-02: scope a farm's alerts via its blocks.
            clauses.append("block_id IN (SELECT id FROM blocks WHERE farm_id = :farm_id)")
            params["farm_id"] = farm_id
        if status_filter:
            clauses.append("status = ANY(:statuses)")
            params["statuses"] = list(status_filter)
        if severity_filter:
            clauses.append("severity = ANY(:severities)")
            params["severities"] = list(severity_filter)
        # `clauses` is built from a fixed set of static SQL fragments
        # picked above; user-supplied values flow through bind
        # parameters. ruff S608 trips on the f-string but the
        # interpolation is into a closed allow-list of literals.
        where_sql = " AND ".join(clauses)
        sql = (
            "SELECT id, block_id, cell_id, "  # noqa: S608
            "       (SELECT row_idx FROM grid_cells WHERE id = alerts.cell_id) AS cell_row, "
            "       (SELECT col_idx FROM grid_cells WHERE id = alerts.cell_id) AS cell_col, "
            "       rule_code, severity, status, "
            "       diagnosis_en, diagnosis_ar, prescription_en, prescription_ar, "
            "       prescription_activity_id, "
            "       signal_snapshot, "
            "       group_key, group_parent_id, is_group, member_count, "
            "       occurrence_count, day_streak, first_seen_at, "
            "       last_seen_at, last_seen_day, cleared_at, "
            "       created_at, updated_at, "
            "       acknowledged_at, acknowledged_by, "
            "       resolved_at, resolved_by, snoozed_until "
            "FROM alerts "
            "WHERE " + where_sql + " "
            "ORDER BY created_at DESC "
            "LIMIT :limit"
        )
        stmt = text(sql)
        if block_id is not None:
            stmt = stmt.bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True)))
        if farm_id is not None:
            stmt = stmt.bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return tuple(dict(r) for r in rows)

    async def transition_alert(
        self,
        *,
        alert_id: UUID,
        new_status: str,
        actor_user_id: UUID | None,
        snoozed_until: datetime | None = None,
    ) -> None:
        """Stamp the appropriate `*_at` / `*_by` columns for the new state.

        Caller validates the transition before calling — see
        `service.transition_alert` for the policy.
        """
        sets = ["status = :status", "updated_at = now()", "updated_by = :actor"]
        params: dict[str, Any] = {
            "id": alert_id,
            "status": new_status,
            "actor": actor_user_id,
        }
        if new_status == "acknowledged":
            sets.append("acknowledged_at = now()")
            sets.append("acknowledged_by = :actor")
            sets.append("snoozed_until = NULL")
        elif new_status == "resolved":
            sets.append("resolved_at = now()")
            sets.append("resolved_by = :actor")
            sets.append("snoozed_until = NULL")
        elif new_status == "snoozed":
            sets.append("snoozed_until = :snoozed_until")
            params["snoozed_until"] = snoozed_until
        # `sets` entries are static SQL literals picked from the closed
        # set above; no caller-supplied identifiers reach the SQL.
        await self._tenant.execute(
            text(f"UPDATE alerts SET {', '.join(sets)} WHERE id = :id").bindparams(  # noqa: S608
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )


def _alert_to_dict(row: Alert) -> dict[str, Any]:
    return {
        "id": row.id,
        "block_id": row.block_id,
        "cell_id": row.cell_id,
        "rule_code": row.rule_code,
        "action_type": row.action_type,
        "severity": row.severity,
        "status": row.status,
        "diagnosis_en": row.diagnosis_en,
        "diagnosis_ar": row.diagnosis_ar,
        "prescription_en": row.prescription_en,
        "prescription_ar": row.prescription_ar,
        "prescription_activity_id": row.prescription_activity_id,
        "signal_snapshot": row.signal_snapshot,
        "group_key": row.group_key,
        "group_parent_id": row.group_parent_id,
        "is_group": row.is_group,
        "member_count": row.member_count,
        "occurrence_count": row.occurrence_count,
        "day_streak": row.day_streak,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "cleared_at": row.cleared_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "acknowledged_at": row.acknowledged_at,
        "acknowledged_by": row.acknowledged_by,
        "resolved_at": row.resolved_at,
        "resolved_by": row.resolved_by,
        "snoozed_until": row.snoozed_until,
    }
