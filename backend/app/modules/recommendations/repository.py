"""Async DB access for the recommendations module. Internal to the module.

Two sessions:

  * `tenant_session` — `recommendations` and `recommendations_history`,
    plus cross-module reads of `block_index_aggregates` and the block →
    farm / crop mapping.
  * `public_session` — `decision_trees` + `decision_tree_versions` catalog
    reads. The catalog is tenant-agnostic.
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

from app.modules.recommendations.models import DecisionTree, DecisionTreeVersion


def _serialize_jsonb(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class RecommendationsRepository:
    """Internal repository — service is the only consumer."""

    def __init__(self, *, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        self._public = public_session

    # ---- Decision-tree catalog (public) -------------------------------

    async def list_active_trees_with_current_version(self) -> tuple[dict[str, Any], ...]:
        """Every active tree paired with its current published version.

        Trees that have no published version yet are skipped — the
        evaluator has nothing to run.
        """
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT t.id   AS tree_id,
                           t.code AS tree_code,
                           t.name_en, t.name_ar,
                           t.crop_id,
                           t.applicable_regions,
                           v.id    AS version_id,
                           v.version,
                           v.tree_compiled
                    FROM public.decision_trees t
                    JOIN public.decision_tree_versions v
                      ON v.id = t.current_version_id
                    WHERE t.is_active = TRUE
                      AND t.deleted_at IS NULL
                      AND v.published_at IS NOT NULL
                    ORDER BY t.code
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def get_tree_by_code(self, tree_code: str) -> dict[str, Any] | None:
        row = (
            (
                await self._public.execute(
                    select(DecisionTree).where(
                        DecisionTree.code == tree_code, DecisionTree.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "code": row.code,
            "name_en": row.name_en,
            "name_ar": row.name_ar,
            "description_en": row.description_en,
            "description_ar": row.description_ar,
            "crop_id": row.crop_id,
            "applicable_regions": list(row.applicable_regions or []),
            "is_active": row.is_active,
            "current_version_id": row.current_version_id,
        }

    async def get_version(self, version_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._public.execute(
                    select(DecisionTreeVersion).where(DecisionTreeVersion.id == version_id)
                )
            )
            .scalars()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "tree_id": row.tree_id,
            "version": row.version,
            "tree_compiled": row.tree_compiled,
            "compiled_hash": row.compiled_hash,
            "published_at": row.published_at,
        }

    # ---- Decision-tree authoring (PlatformAdmin) ----------------------

    async def list_all_trees(self) -> tuple[dict[str, Any], ...]:
        """Every non-deleted tree + the version number of its current
        published version (if any). Drives the editor's tree list."""
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT t.id, t.code, t.name_en, t.name_ar,
                           t.description_en, t.description_ar,
                           t.crop_id, t.applicable_regions, t.is_active,
                           v.version AS current_version
                    FROM public.decision_trees t
                    LEFT JOIN public.decision_tree_versions v
                      ON v.id = t.current_version_id
                    WHERE t.deleted_at IS NULL
                    ORDER BY t.code
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_versions_for_tree(self, *, tree_id: UUID) -> tuple[dict[str, Any], ...]:
        """All versions for one tree, newest first. Includes raw YAML +
        compiled JSON so the editor can offer diff-between-versions."""
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT id, tree_id, version, tree_yaml, tree_compiled,
                           compiled_hash, published_at, notes,
                           created_at, updated_at
                    FROM public.decision_tree_versions
                    WHERE tree_id = :tid
                    ORDER BY version DESC
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": tree_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def get_version_by_number(self, *, tree_id: UUID, version: int) -> dict[str, Any] | None:
        row = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT id, tree_id, version, tree_yaml, tree_compiled,
                           compiled_hash, published_at, notes,
                           created_at, updated_at
                    FROM public.decision_tree_versions
                    WHERE tree_id = :tid AND version = :v
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": tree_id, "v": version},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def get_latest_version_number(self, *, tree_id: UUID) -> int:
        row = (
            await self._public.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) AS v "
                    "FROM public.decision_tree_versions WHERE tree_id = :tid"
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"tid": tree_id},
            )
        ).first()
        return int(row.v) if row is not None else 0

    async def insert_tree(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str | None,
        description_en: str | None,
        description_ar: str | None,
        crop_id: UUID | None,
        applicable_regions: list[str],
        actor_user_id: UUID | None,
    ) -> UUID:
        """Insert a new `decision_trees` row. Caller wraps insertion + first
        version + current_version_id update in one transaction."""
        row = (
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.decision_trees
                        (code, name_en, name_ar, description_en, description_ar,
                         crop_id, applicable_regions, is_active,
                         created_by, updated_by)
                    VALUES (:code, :name_en, :name_ar, :description_en, :description_ar,
                            :crop_id, :applicable_regions, TRUE,
                            :actor, :actor)
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("crop_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "code": code,
                    "name_en": name_en,
                    "name_ar": name_ar,
                    "description_en": description_en,
                    "description_ar": description_ar,
                    "crop_id": crop_id,
                    "applicable_regions": applicable_regions,
                    "actor": actor_user_id,
                },
            )
        ).first()
        return row.id

    async def insert_version(
        self,
        *,
        tree_id: UUID,
        version: int,
        tree_yaml: str,
        tree_compiled: dict[str, Any],
        compiled_hash: str,
        notes: str | None,
        published_at: datetime | None,
        published_by: UUID | None,
    ) -> UUID:
        row = (
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.decision_tree_versions
                        (tree_id, version, tree_yaml, tree_compiled,
                         compiled_hash, notes, published_at, published_by)
                    VALUES (:tid, :version, :yaml, CAST(:compiled AS jsonb),
                            :hash, :notes, :published_at, :published_by)
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                    bindparam("published_by", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "tid": tree_id,
                    "version": version,
                    "yaml": tree_yaml,
                    "compiled": _serialize_jsonb(tree_compiled),
                    "hash": compiled_hash,
                    "notes": notes,
                    "published_at": published_at,
                    "published_by": published_by,
                },
            )
        ).first()
        return row.id

    async def set_current_version(
        self,
        *,
        tree_id: UUID,
        version_id: UUID,
        actor_user_id: UUID | None,
    ) -> None:
        await self._public.execute(
            text(
                "UPDATE public.decision_trees "
                "SET current_version_id = :vid, updated_by = :actor, updated_at = now() "
                "WHERE id = :tid"
            ).bindparams(
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("vid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"tid": tree_id, "vid": version_id, "actor": actor_user_id},
        )

    async def update_tree_metadata(
        self,
        *,
        tree_id: UUID,
        name_en: str,
        name_ar: str | None,
        description_en: str | None,
        description_ar: str | None,
        crop_id: UUID | None,
        applicable_regions: list[str],
        actor_user_id: UUID | None,
    ) -> None:
        """Sync tree-level metadata when a new version's YAML changes
        the name / description / crop. The version's compiled JSON is
        the audit record; the tree row holds the human-friendly latest."""
        await self._public.execute(
            text(
                """
                UPDATE public.decision_trees
                   SET name_en = :name_en,
                       name_ar = :name_ar,
                       description_en = :description_en,
                       description_ar = :description_ar,
                       crop_id = :crop_id,
                       applicable_regions = :applicable_regions,
                       updated_by = :actor,
                       updated_at = now()
                 WHERE id = :tid
                """
            ).bindparams(
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("crop_id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "tid": tree_id,
                "name_en": name_en,
                "name_ar": name_ar,
                "description_en": description_en,
                "description_ar": description_ar,
                "crop_id": crop_id,
                "applicable_regions": applicable_regions,
                "actor": actor_user_id,
            },
        )

    async def resolve_crop_id(self, crop_code: str | None) -> UUID | None:
        """Lookup `crops.id` by code. Returns None when crop_code is
        None/empty or unknown — same permissive behaviour as the YAML
        loader's `_resolve_crop_id`."""
        if not crop_code:
            return None
        row = (
            await self._public.execute(
                text("SELECT id FROM public.crops WHERE code = :c AND deleted_at IS NULL"),
                {"c": crop_code},
            )
        ).first()
        return row.id if row is not None else None

    # ---- Recommendations (tenant) -------------------------------------

    async def insert_recommendation(
        self,
        *,
        recommendation_id: UUID,
        block_id: UUID,
        farm_id: UUID,
        tree_id: UUID,
        tree_code: str,
        tree_version: int,
        block_crop_id: UUID | None,
        action_type: str,
        severity: str,
        parameters: dict[str, Any],
        confidence: Decimal,
        tree_path: list[Any],
        text_en: str,
        text_ar: str | None,
        valid_until: datetime | None,
        evaluation_snapshot: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> bool:
        """Open one recommendation. Returns True if a row was inserted,
        False if the partial UNIQUE on (block_id, tree_id) blocked it
        (an open recommendation already exists)."""
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO recommendations (
                        id, block_id, farm_id, tree_id, tree_code, tree_version,
                        block_crop_id, action_type, severity, parameters,
                        confidence, tree_path, text_en, text_ar,
                        valid_until, evaluation_snapshot, state,
                        created_by, updated_by
                    ) VALUES (
                        :id, :block_id, :farm_id, :tree_id, :tree_code, :tree_version,
                        :block_crop_id, :action_type, :severity,
                        CAST(:parameters AS jsonb),
                        :confidence,
                        CAST(:tree_path AS jsonb), :text_en, :text_ar,
                        :valid_until, CAST(:snapshot AS jsonb), 'open',
                        :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("tree_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_crop_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": recommendation_id,
                    "block_id": block_id,
                    "farm_id": farm_id,
                    "tree_id": tree_id,
                    "tree_code": tree_code,
                    "tree_version": tree_version,
                    "block_crop_id": block_crop_id,
                    "action_type": action_type,
                    "severity": severity,
                    "parameters": _serialize_jsonb(parameters),
                    "confidence": confidence,
                    "tree_path": _serialize_jsonb(tree_path),
                    "text_en": text_en,
                    "text_ar": text_ar,
                    "valid_until": valid_until,
                    "snapshot": _serialize_jsonb(evaluation_snapshot),
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if "uq_recommendations_block_tree_open" in str(exc):
                return False
            raise
        await self._tenant.flush()
        return True

    async def get_recommendation(self, *, recommendation_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT id, block_id, farm_id, tree_id, tree_code, tree_version,
                           block_crop_id, action_type, severity, parameters,
                           confidence, tree_path, text_en, text_ar,
                           valid_until, state, applied_at, applied_by,
                           dismissed_at, dismissed_by, dismissal_reason,
                           deferred_until, outcome_notes, evaluation_snapshot,
                           created_at, updated_at
                    FROM recommendations
                    WHERE id = :id AND deleted_at IS NULL
                    """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": recommendation_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def list_recommendations(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        state_filter: tuple[str, ...] = (),
        action_type_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        clauses = ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        if farm_id is not None:
            clauses.append("farm_id = :farm_id")
            params["farm_id"] = farm_id
        if block_id is not None:
            clauses.append("block_id = :block_id")
            params["block_id"] = block_id
        if state_filter:
            clauses.append("state = ANY(:states)")
            params["states"] = list(state_filter)
        if action_type_filter:
            clauses.append("action_type = ANY(:actions)")
            params["actions"] = list(action_type_filter)
        where_sql = " AND ".join(clauses)
        sql = (
            "SELECT id, block_id, farm_id, tree_id, tree_code, tree_version, "
            "       block_crop_id, action_type, severity, parameters, "
            "       confidence, tree_path, text_en, text_ar, "
            "       valid_until, state, applied_at, applied_by, "
            "       dismissed_at, dismissed_by, dismissal_reason, "
            "       deferred_until, outcome_notes, "
            "       created_at, updated_at "
            "FROM recommendations "
            "WHERE " + where_sql + " "
            "ORDER BY created_at DESC LIMIT :limit"
        )
        stmt = text(sql)
        if farm_id is not None:
            stmt = stmt.bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        if block_id is not None:
            stmt = stmt.bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True)))
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return tuple(dict(r) for r in rows)

    async def transition_recommendation(
        self,
        *,
        recommendation_id: UUID,
        new_state: str,
        actor_user_id: UUID | None,
        dismissal_reason: str | None = None,
        deferred_until: datetime | None = None,
        outcome_notes: str | None = None,
    ) -> None:
        """Stamp the *_at / *_by columns for the new state. Caller validates."""
        sets = ["state = :state", "updated_at = now()", "updated_by = :actor"]
        params: dict[str, Any] = {
            "id": recommendation_id,
            "state": new_state,
            "actor": actor_user_id,
        }
        if new_state == "applied":
            sets.append("applied_at = now()")
            sets.append("applied_by = :actor")
            sets.append("deferred_until = NULL")
            if outcome_notes is not None:
                sets.append("outcome_notes = :outcome_notes")
                params["outcome_notes"] = outcome_notes
        elif new_state == "dismissed":
            sets.append("dismissed_at = now()")
            sets.append("dismissed_by = :actor")
            sets.append("deferred_until = NULL")
            sets.append("dismissal_reason = :reason")
            params["reason"] = dismissal_reason
        elif new_state == "deferred":
            sets.append("deferred_until = :deferred_until")
            params["deferred_until"] = deferred_until
        elif new_state == "expired":
            pass  # only state change

        await self._tenant.execute(
            text(
                f"UPDATE recommendations SET {', '.join(sets)} "  # noqa: S608
                "WHERE id = :id"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )

    async def insert_history(
        self,
        *,
        recommendation_id: UUID,
        block_id: UUID,
        farm_id: UUID,
        from_state: str | None,
        to_state: str,
        actor_user_id: UUID | None,
        details: dict[str, Any] | None,
    ) -> None:
        await self._tenant.execute(
            text(
                """
                INSERT INTO recommendations_history
                    (recommendation_id, block_id, farm_id, from_state, to_state,
                     actor_user_id, details)
                VALUES (:rec, :block, :farm, :from_state, :to_state,
                        :actor, CAST(:details AS jsonb))
                """
            ).bindparams(
                bindparam("rec", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "rec": recommendation_id,
                "block": block_id,
                "farm": farm_id,
                "from_state": from_state,
                "to_state": to_state,
                "actor": actor_user_id,
                "details": _serialize_jsonb(details),
            },
        )

    # ---- Cross-module readers for the engine ---------------------------

    async def get_latest_aggregate_per_index(self, *, block_id: UUID) -> dict[str, dict[str, Any]]:
        """Latest `block_index_aggregates` row per index_code — same
        query the alerts engine uses, repeated here so the recommendations
        module doesn't reach into alerts internals."""
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

    async def get_block_farm_id(self, *, block_id: UUID) -> UUID | None:
        row = (
            await self._tenant.execute(
                text(
                    "SELECT farm_id FROM blocks WHERE id = :block_id " "AND deleted_at IS NULL"
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        ).first()
        return row.farm_id if row is not None else None

    async def get_block_current_crop(
        self, *, block_id: UUID
    ) -> tuple[UUID | None, UUID | None, str | None]:
        """Return (block_crop_id, crop_id, crop_category) for the active
        assignment, or (None, None, None) if no current assignment."""
        row = (
            await self._tenant.execute(
                text(
                    """
                    SELECT id AS block_crop_id, crop_id
                    FROM block_crops
                    WHERE block_id = :block_id
                      AND is_current = TRUE
                      AND deleted_at IS NULL
                    LIMIT 1
                    """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        ).first()
        if row is None:
            return None, None, None
        crop_row = (
            await self._public.execute(
                text("SELECT category FROM public.crops WHERE id = :crop_id").bindparams(
                    bindparam("crop_id", type_=PG_UUID(as_uuid=True))
                ),
                {"crop_id": row.crop_id},
            )
        ).first()
        category = crop_row.category if crop_row is not None else None
        return row.block_crop_id, row.crop_id, category

    async def list_active_block_ids(self) -> tuple[UUID, ...]:
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM blocks "
                    "WHERE deleted_at IS NULL "
                    "  AND active_from <= current_date "
                    "  AND (active_to IS NULL OR active_to > current_date)"
                )
            )
        ).all()
        return tuple(r.id for r in rows)
