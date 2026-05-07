"""Async DB access for the alerts module. Internal to the module.

Two sessions:

  * `tenant_session` — ``rule_overrides`` and ``alerts``, plus the
    cross-module read of ``block_index_aggregates`` for the latest
    per-index values feeding the engine.
  * `public_session` — ``default_rules`` catalog. The catalog is
    tenant-agnostic; reads happen on the admin connection that lives
    alongside every tenant request.
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

from app.modules.alerts.models import Alert, DefaultRule, RuleOverride


def _serialize_jsonb(value: dict[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value)


class AlertsRepository:
    """Internal repository — service is the only consumer."""

    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        self._public = public_session

    # ---- Default rules (public catalog) -------------------------------

    async def list_default_rules(
        self, *, status_filter: str = "active"
    ) -> tuple[dict[str, Any], ...]:
        stmt = select(DefaultRule).where(DefaultRule.deleted_at.is_(None))
        if status_filter:
            stmt = stmt.where(DefaultRule.status == status_filter)
        stmt = stmt.order_by(DefaultRule.code)
        rows = (await self._public.execute(stmt)).scalars().all()
        return tuple(
            {
                "code": r.code,
                "name_en": r.name_en,
                "name_ar": r.name_ar,
                "description_en": r.description_en,
                "description_ar": r.description_ar,
                "severity": r.severity,
                "status": r.status,
                "applies_to_crop_categories": list(r.applies_to_crop_categories or []),
                "conditions": r.conditions,
                "actions": r.actions,
                "version": r.version,
            }
            for r in rows
        )

    async def get_default_rule(self, *, rule_code: str) -> dict[str, Any] | None:
        stmt = select(DefaultRule).where(
            DefaultRule.code == rule_code, DefaultRule.deleted_at.is_(None)
        )
        row = (await self._public.execute(stmt)).scalars().one_or_none()
        if row is None:
            return None
        return {
            "code": row.code,
            "name_en": row.name_en,
            "name_ar": row.name_ar,
            "description_en": row.description_en,
            "description_ar": row.description_ar,
            "severity": row.severity,
            "status": row.status,
            "applies_to_crop_categories": list(row.applies_to_crop_categories or []),
            "conditions": row.conditions,
            "actions": row.actions,
            "version": row.version,
        }

    # ---- Rule overrides (tenant) ---------------------------------------

    async def list_overrides(self) -> tuple[dict[str, Any], ...]:
        stmt = (
            select(RuleOverride)
            .where(RuleOverride.deleted_at.is_(None))
            .order_by(RuleOverride.rule_code)
        )
        rows = (await self._tenant.execute(stmt)).scalars().all()
        return tuple(_override_to_dict(r) for r in rows)

    async def get_override(self, *, rule_code: str) -> dict[str, Any] | None:
        stmt = select(RuleOverride).where(
            RuleOverride.rule_code == rule_code, RuleOverride.deleted_at.is_(None)
        )
        row = (await self._tenant.execute(stmt)).scalars().one_or_none()
        return _override_to_dict(row) if row is not None else None

    async def upsert_override(
        self,
        *,
        rule_code: str,
        modified_conditions: dict[str, Any] | None,
        modified_actions: dict[str, Any] | None,
        modified_severity: str | None,
        is_disabled: bool,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Insert-or-update one override row for the given rule_code.

        Conflicts on the partial UNIQUE `(rule_code) WHERE deleted_at
        IS NULL` index — overwriting is intentional, since each rule
        has at most one effective override per tenant.
        """
        await self._tenant.execute(
            text(
                """
                INSERT INTO rule_overrides (
                    rule_code, modified_conditions, modified_actions,
                    modified_severity, is_disabled,
                    created_by, updated_by
                )
                VALUES (
                    :rule_code,
                    CAST(:conditions AS jsonb), CAST(:actions AS jsonb),
                    :severity, :is_disabled,
                    :actor, :actor
                )
                ON CONFLICT (rule_code) WHERE deleted_at IS NULL
                DO UPDATE SET
                    modified_conditions = EXCLUDED.modified_conditions,
                    modified_actions = EXCLUDED.modified_actions,
                    modified_severity = EXCLUDED.modified_severity,
                    is_disabled = EXCLUDED.is_disabled,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """
            ).bindparams(bindparam("actor", type_=PG_UUID(as_uuid=True))),
            {
                "rule_code": rule_code,
                "conditions": _serialize_jsonb(modified_conditions),
                "actions": _serialize_jsonb(modified_actions),
                "severity": modified_severity,
                "is_disabled": is_disabled,
                "actor": actor_user_id,
            },
        )
        await self._tenant.flush()
        out = await self.get_override(rule_code=rule_code)
        if out is None:
            raise RuntimeError("Override upsert succeeded but row is missing")
        return out

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
            text(
                f"UPDATE alerts SET {', '.join(sets)} WHERE id = :id"  # noqa: S608
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )

    # ---- Cross-module reader for the engine ----------------------------

    async def get_latest_aggregate_per_index(self, *, block_id: UUID) -> dict[str, dict[str, Any]]:
        """Pull the latest `block_index_aggregates` row per index_code.

        Used by the engine to assemble a `BlockSignals` snapshot. We
        DISTINCT ON (index_code) ORDER BY time DESC so each index
        contributes exactly its most recent observation.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT DISTINCT ON (index_code)
                           index_code, time, mean, baseline_deviation
                    FROM block_index_aggregates
                    WHERE block_id = :block_id
                    ORDER BY index_code, time DESC
                    """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id},
                )
            )
            .mappings()
            .all()
        )
        return {
            row["index_code"]: {
                "time": row["time"],
                "mean": row["mean"],
                "baseline_deviation": row["baseline_deviation"],
            }
            for row in rows
        }

    async def get_block_crop_category(self, *, block_id: UUID) -> str | None:
        """Look up the block's *current* crop's category.

        Returns None if the block has no current assignment.
        """
        row = (
            await self._tenant.execute(
                text(
                    """
                    SELECT bc.crop_id
                    FROM block_crops bc
                    WHERE bc.block_id = :block_id
                      AND bc.is_current = TRUE
                      AND bc.deleted_at IS NULL
                    LIMIT 1
                    """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        ).first()
        if row is None:
            return None
        crop_row = (
            await self._public.execute(
                text("SELECT category FROM public.crops WHERE id = :crop_id").bindparams(
                    bindparam("crop_id", type_=PG_UUID(as_uuid=True))
                ),
                {"crop_id": row.crop_id},
            )
        ).first()
        return crop_row.category if crop_row is not None else None

    async def list_active_block_ids(self) -> tuple[UUID, ...]:
        """Every active block in the tenant — Beat sweep input."""
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM blocks "
                    "WHERE deleted_at IS NULL AND status NOT IN ('archived', 'abandoned')"
                )
            )
        ).all()
        return tuple(r.id for r in rows)


def _override_to_dict(row: RuleOverride) -> dict[str, Any]:
    return {
        "id": row.id,
        "rule_code": row.rule_code,
        "modified_conditions": row.modified_conditions,
        "modified_actions": row.modified_actions,
        "modified_severity": row.modified_severity,
        "is_disabled": row.is_disabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


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
