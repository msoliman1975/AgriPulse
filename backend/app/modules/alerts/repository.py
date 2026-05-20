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
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert


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
        rule_code: str,
        severity: str,
        diagnosis_en: str | None,
        diagnosis_ar: str | None,
        prescription_en: str | None,
        prescription_ar: str | None,
        prescription_activity_id: UUID | None,
        signal_snapshot: dict[str, Any] | None,
        actor_user_id: UUID | None,
    ) -> bool:
        """Open one alert. Returns True if a row was inserted, False if
        the partial UNIQUE on (block_id, rule_code) blocked it (an
        active alert already exists).

        Tree-sourced alerts pass ``rule_code`` of the form
        ``tree:<tree_code>:<leaf_node_id>`` so the same partial UNIQUE
        on ``(block_id, rule_code) WHERE status IN open/ack/snoozed``
        keeps re-evaluation idempotent without needing schema changes.
        """
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO alerts (
                        id, block_id, rule_code, severity, status,
                        diagnosis_en, diagnosis_ar,
                        prescription_en, prescription_ar,
                        prescription_activity_id,
                        signal_snapshot, created_by, updated_by
                    ) VALUES (
                        :id, :block_id, :rule_code, :severity, 'open',
                        :diag_en, :diag_ar,
                        :pre_en, :pre_ar,
                        :prescription_activity_id,
                        CAST(:snapshot AS jsonb), :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("prescription_activity_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": alert_id,
                    "block_id": block_id,
                    "rule_code": rule_code,
                    "severity": severity,
                    "diag_en": diagnosis_en,
                    "diag_ar": diagnosis_ar,
                    "pre_en": prescription_en,
                    "pre_ar": prescription_ar,
                    "prescription_activity_id": prescription_activity_id,
                    "snapshot": _serialize_jsonb(signal_snapshot),
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            # Partial UNIQUE on (block_id, rule_code) WHERE status IN
            # open/ack/snoozed — re-firing while a prior alert is
            # active is a no-op by design.
            if "uq_alerts_block_rule_open" in str(exc):
                return False
            raise
        await self._tenant.flush()
        return True

    async def get_alert(self, *, alert_id: UUID) -> dict[str, Any] | None:
        stmt = select(Alert).where(Alert.id == alert_id, Alert.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).scalars().one_or_none()
        return _alert_to_dict(row) if row is not None else None

    async def list_alerts(
        self,
        *,
        block_id: UUID | None = None,
        status_filter: tuple[str, ...] = (),
        severity_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        if block_id is not None:
            clauses.append("block_id = :block_id")
            params["block_id"] = block_id
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
            "SELECT id, block_id, rule_code, severity, status, "
            "       diagnosis_en, diagnosis_ar, prescription_en, prescription_ar, "
            "       prescription_activity_id, "
            "       signal_snapshot, created_at, updated_at, "
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
        "rule_code": row.rule_code,
        "severity": row.severity,
        "status": row.status,
        "diagnosis_en": row.diagnosis_en,
        "diagnosis_ar": row.diagnosis_ar,
        "prescription_en": row.prescription_en,
        "prescription_ar": row.prescription_ar,
        "prescription_activity_id": row.prescription_activity_id,
        "signal_snapshot": row.signal_snapshot,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "acknowledged_at": row.acknowledged_at,
        "acknowledged_by": row.acknowledged_by,
        "resolved_at": row.resolved_at,
        "resolved_by": row.resolved_by,
        "snoozed_until": row.snoozed_until,
    }
