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
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.indices.trends import compute_trend
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

    async def list_active_trees_with_current_version(
        self, *, visible_to_tenant_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        """Every active tree visible to the given tenant, paired with its
        current published version.

        Visibility = platform catalog (tenant_id IS NULL) plus the
        tenant's own authored trees (tenant_id = :tid). Other tenants'
        trees are excluded. Trees without a published version yet are
        skipped (PR-A).
        """
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT t.id   AS tree_id,
                           t.code AS tree_code,
                           t.tenant_id,
                           t.name_en, t.name_ar,
                           t.crop_id,
                           t.crop_path,
                           t.crop_paths,
                           t.country_codes,
                           t.soil_textures,
                           t.scope,
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
                      AND (t.tenant_id IS NULL OR t.tenant_id = :tid)
                    ORDER BY t.code
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": visible_to_tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def get_tree_by_code(
        self,
        tree_code: str,
        *,
        scope_tenant_id: UUID | None,
        include_platform: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        """Look up one tree by code (PR-A).

        ``scope_tenant_id``:
          * UUID  — match trees authored by that tenant.
          * None  — match platform trees only (tenant_id IS NULL).

        ``include_platform`` (meaningful only when scope_tenant_id is a
        UUID): when True, also include platform trees. Used by read
        sites where a tenant should see "platform OR my own"; the
        create_tree path rejects tenant codes that collide with
        platform codes, so the result is unambiguous.

        ``include_deleted``: when True, also match soft-archived rows
        (``deleted_at IS NOT NULL``). Only the restore path needs this —
        every other caller wants the archived tree to read as absent.
        """
        stmt = select(DecisionTree).where(DecisionTree.code == tree_code)
        if not include_deleted:
            stmt = stmt.where(DecisionTree.deleted_at.is_(None))
        if scope_tenant_id is None:
            stmt = stmt.where(DecisionTree.tenant_id.is_(None))
        elif include_platform:
            stmt = stmt.where(
                (DecisionTree.tenant_id.is_(None)) | (DecisionTree.tenant_id == scope_tenant_id)
            )
        else:
            stmt = stmt.where(DecisionTree.tenant_id == scope_tenant_id)
        row = (await self._public.execute(stmt)).scalars().one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "code": row.code,
            "tenant_id": row.tenant_id,
            "name_en": row.name_en,
            "name_ar": row.name_ar,
            "description_en": row.description_en,
            "description_ar": row.description_ar,
            "crop_id": row.crop_id,
            "crop_paths": list(row.crop_paths or []),
            "country_codes": list(row.country_codes or []),
            "soil_textures": list(row.soil_textures or []),
            "scope": row.scope,
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

    async def list_all_trees(self, *, visible_to_tenant_id: UUID) -> tuple[dict[str, Any], ...]:
        """Every non-deleted tree visible to the given tenant + the
        version number of its current published version (if any).
        Drives the authoring tree list.

        Visibility mirrors `list_active_trees_with_current_version`:
        platform trees plus the tenant's own. Platform trees sort first
        so the authoring UI naturally groups them at the top (PR-A).
        """
        rows = (
            (
                await self._public.execute(
                    text(
                        """
                    SELECT t.id, t.code, t.tenant_id,
                           t.name_en, t.name_ar,
                           t.description_en, t.description_ar,
                           t.crop_id, t.crop_paths, t.country_codes,
                           t.soil_textures, t.scope, t.applicable_regions, t.is_active,
                           v.version AS current_version
                    FROM public.decision_trees t
                    LEFT JOIN public.decision_tree_versions v
                      ON v.id = t.current_version_id
                    WHERE t.deleted_at IS NULL
                      AND (t.tenant_id IS NULL OR t.tenant_id = :tid)
                    ORDER BY t.tenant_id NULLS FIRST, t.code
                    """
                    ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                    {"tid": visible_to_tenant_id},
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
        tenant_id: UUID | None,
        name_en: str,
        name_ar: str | None,
        description_en: str | None,
        description_ar: str | None,
        crop_id: UUID | None,
        applicable_regions: list[str],
        actor_user_id: UUID | None,
        crop_path: str | None = None,
        crop_paths: list[str] | None = None,
        country_codes: list[str] | None = None,
        soil_textures: list[str] | None = None,
        scope: str = "block",
    ) -> UUID:
        """Insert a new `decision_trees` row. Caller wraps insertion + first
        version + current_version_id update in one transaction.

        ``tenant_id`` is None for platform-shipped trees (the YAML seed
        loader path) and a tenant UUID for API-authored trees (PR-A).
        ``crop_path`` (optional) is the hierarchical taxonomy targeting key.
        """
        row = (
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.decision_trees
                        (code, tenant_id, name_en, name_ar,
                         description_en, description_ar,
                         crop_id, crop_path, crop_paths, country_codes,
                         soil_textures, scope, applicable_regions, is_active,
                         created_by, updated_by)
                    VALUES (:code, :tenant_id, :name_en, :name_ar,
                            :description_en, :description_ar,
                            :crop_id, :crop_path, :crop_paths, :country_codes,
                            :soil_textures, :scope, :applicable_regions, TRUE,
                            :actor, :actor)
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("tenant_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("crop_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "code": code,
                    "tenant_id": tenant_id,
                    "name_en": name_en,
                    "name_ar": name_ar,
                    "description_en": description_en,
                    "description_ar": description_ar,
                    "crop_id": crop_id,
                    "crop_path": crop_path,
                    "crop_paths": crop_paths or [],
                    "country_codes": country_codes or [],
                    "soil_textures": soil_textures or [],
                    "scope": scope,
                    "applicable_regions": applicable_regions,
                    "actor": actor_user_id,
                },
            )
        ).first()
        assert row is not None  # INSERT ... RETURNING always yields one row
        return cast(UUID, row.id)

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
        assert row is not None  # INSERT ... RETURNING always yields one row
        return cast(UUID, row.id)

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
        crop_path: str | None = None,
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
                       crop_path = :crop_path,
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
                "crop_path": crop_path,
                "applicable_regions": applicable_regions,
                "actor": actor_user_id,
            },
        )

    async def update_tree_targeting_metadata(
        self,
        *,
        tree_id: UUID,
        name_en: str,
        name_ar: str | None,
        description_en: str | None,
        description_ar: str | None,
        crop_id: UUID | None,
        crop_path: str | None,
        crop_paths: list[str],
        country_codes: list[str],
        soil_textures: list[str],
        scope: str,
        actor_user_id: UUID | None,
    ) -> None:
        """Full-replace of the editable tree-level metadata from the
        authoring metadata panel (PATCH path). Unlike
        ``update_tree_metadata`` (which only syncs name/description/crop
        from a freshly compiled version's YAML), this also writes the
        multi-axis targeting sets + execution scope so the structured
        pickers are the source of truth for crop/country/soil/scope."""
        await self._public.execute(
            text(
                """
                UPDATE public.decision_trees
                   SET name_en = :name_en,
                       name_ar = :name_ar,
                       description_en = :description_en,
                       description_ar = :description_ar,
                       crop_id = :crop_id,
                       crop_path = :crop_path,
                       crop_paths = :crop_paths,
                       country_codes = :country_codes,
                       soil_textures = :soil_textures,
                       scope = :scope,
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
                "crop_path": crop_path,
                "crop_paths": crop_paths,
                "country_codes": country_codes,
                "soil_textures": soil_textures,
                "scope": scope,
                "actor": actor_user_id,
            },
        )

    async def set_tree_archived(
        self,
        *,
        tree_id: UUID,
        archived: bool,
        actor_user_id: UUID | None,
    ) -> None:
        """Soft-archive (``deleted_at = now()``) or restore
        (``deleted_at = NULL``) one tree. Archived trees drop out of the
        catalog + are never evaluated (every read filters
        ``deleted_at IS NULL``) but the row + its version history stay
        intact, so a restore is loss-free."""
        # Two static statements rather than interpolating the deleted_at
        # expression into the SQL — keeps the query free of f-string
        # construction (and the linter happy).
        sql = (
            "UPDATE public.decision_trees "
            "SET deleted_at = now(), updated_by = :actor, updated_at = now() "
            "WHERE id = :tid"
            if archived
            else "UPDATE public.decision_trees "
            "SET deleted_at = NULL, updated_by = :actor, updated_at = now() "
            "WHERE id = :tid"
        )
        await self._public.execute(
            text(sql).bindparams(
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"tid": tree_id, "actor": actor_user_id},
        )

    async def get_tenant_id_by_schema(self, schema_name: str) -> UUID | None:
        """Resolve a tenant's UUID via `public.tenants.schema_name`.

        Used by the sweep loop to compute the scoping UUID once per
        tenant before walking blocks. Returns None when the schema is
        unknown / soft-deleted; the caller logs and skips.
        """
        row = (
            await self._public.execute(
                text(
                    "SELECT id FROM public.tenants " "WHERE schema_name = :s AND deleted_at IS NULL"
                ),
                {"s": schema_name},
            )
        ).first()
        return cast(UUID, row.id) if row is not None else None

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

    # ---- Tree parameter overrides (tenant) ----------------------------

    async def list_param_overrides_for_tree(self, *, tree_id: UUID) -> dict[str, Any]:
        """Fetch every override row for one tree as a flat
        ``{param_name: value}`` dict — the shape the engine consumes
        via ``evaluate_tree(param_overrides=...)``.

        Returns ``{}`` when no overrides exist (the engine falls back
        to declared defaults entirely).
        """
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT param_name, value FROM tree_parameter_overrides " "WHERE tree_id = :tid"
                ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
                {"tid": tree_id},
            )
        ).all()
        return {r.param_name: r.value for r in rows}

    async def list_all_param_overrides_visible_to_tenant(
        self, *, tree_ids: tuple[UUID, ...]
    ) -> dict[UUID, dict[str, Any]]:
        """Bulk variant of `list_param_overrides_for_tree` for the
        sweep: one query for every tree the sweep is about to walk,
        grouped by tree_id. Returns an empty dict per tree if the
        tenant has no overrides.
        """
        if not tree_ids:
            return {}
        rows = (
            await self._tenant.execute(
                text(
                    "SELECT tree_id, param_name, value "
                    "FROM tree_parameter_overrides "
                    "WHERE tree_id = ANY(:tids)"
                ).bindparams(bindparam("tids", type_=postgresql.ARRAY(PG_UUID(as_uuid=True)))),
                {"tids": list(tree_ids)},
            )
        ).all()
        grouped: dict[UUID, dict[str, Any]] = {tid: {} for tid in tree_ids}
        for r in rows:
            grouped.setdefault(r.tree_id, {})[r.param_name] = r.value
        return grouped

    async def upsert_param_override(
        self,
        *,
        tree_id: UUID,
        param_name: str,
        value: Any,
        actor_user_id: UUID | None,
    ) -> None:
        """Set or replace one override. ON CONFLICT updates value +
        updated_by/_at; created_by/_at stay from the first insert."""
        await self._tenant.execute(
            text(
                """
                INSERT INTO tree_parameter_overrides
                    (tree_id, param_name, value, created_by, updated_by)
                VALUES (:tid, :n, CAST(:v AS jsonb), :actor, :actor)
                ON CONFLICT (tree_id, param_name) DO UPDATE
                SET value = EXCLUDED.value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """
            ).bindparams(
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "tid": tree_id,
                "n": param_name,
                "v": _serialize_jsonb(value),
                "actor": actor_user_id,
            },
        )

    async def delete_param_override(self, *, tree_id: UUID, param_name: str) -> bool:
        """Remove one override. Returns True if a row was deleted."""
        result = await self._tenant.execute(
            text(
                "DELETE FROM tree_parameter_overrides " "WHERE tree_id = :tid AND param_name = :n"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tree_id, "n": param_name},
        )
        return bool(getattr(result, "rowcount", 0) or 0)

    # ---- Recommendations (tenant) -------------------------------------

    async def insert_recommendation(
        self,
        *,
        recommendation_id: UUID,
        block_id: UUID,
        cell_id: UUID | None = None,
        farm_id: UUID,
        tree_id: UUID,
        tree_code: str,
        tree_version: int,
        block_crop_id: UUID | None,
        action_type: str,
        severity: str,
        parameters: dict[str, Any],
        actions: dict[str, Any],
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
        # Savepoint so an idempotent conflict (an open rec already exists for
        # this block[/cell] + tree) rolls back just this insert instead of
        # poisoning the surrounding sweep transaction — the cell-scoped sweep
        # does many inserts that conflict on re-evaluation.
        savepoint = await self._tenant.begin_nested()
        try:
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO recommendations (
                        id, block_id, cell_id, farm_id, tree_id, tree_code,
                        tree_version,
                        block_crop_id, action_type, severity, parameters, actions,
                        confidence, tree_path, text_en, text_ar,
                        valid_until, evaluation_snapshot, state,
                        created_by, updated_by
                    ) VALUES (
                        :id, :block_id, :cell_id, :farm_id, :tree_id, :tree_code,
                        :tree_version,
                        :block_crop_id, :action_type, :severity,
                        CAST(:parameters AS jsonb), CAST(:actions AS jsonb),
                        :confidence,
                        CAST(:tree_path AS jsonb), :text_en, :text_ar,
                        :valid_until, CAST(:snapshot AS jsonb), 'open',
                        :actor, :actor
                    )
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("cell_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("tree_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_crop_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": recommendation_id,
                    "block_id": block_id,
                    "cell_id": cell_id,
                    "farm_id": farm_id,
                    "tree_id": tree_id,
                    "tree_code": tree_code,
                    "tree_version": tree_version,
                    "block_crop_id": block_crop_id,
                    "action_type": action_type,
                    "severity": severity,
                    "parameters": _serialize_jsonb(parameters),
                    "actions": _serialize_jsonb(actions),
                    "confidence": confidence,
                    "tree_path": _serialize_jsonb(tree_path),
                    "text_en": text_en,
                    "text_ar": text_ar,
                    "valid_until": valid_until,
                    "snapshot": _serialize_jsonb(evaluation_snapshot),
                    "actor": actor_user_id,
                },
            )
            await savepoint.commit()
        except IntegrityError as exc:
            await savepoint.rollback()
            # Either the block-scoped or the cell-scoped open-state dedup
            # blocked it — an open rec already exists for this (block[/cell], tree).
            msg = str(exc)
            if (
                "uq_recommendations_block_tree_open" in msg
                or "uq_recommendations_cell_tree_open" in msg
            ):
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
                    SELECT id, block_id, cell_id,
                           (SELECT row_idx FROM grid_cells WHERE id = recommendations.cell_id)
                               AS cell_row,
                           (SELECT col_idx FROM grid_cells WHERE id = recommendations.cell_id)
                               AS cell_col,
                           farm_id, tree_id, tree_code, tree_version,
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
        # S608: values flow through bind params; `where_sql` is built only from
        # the closed allow-list of literal fragments above.
        sql = (
            "SELECT id, block_id, cell_id, "  # noqa: S608
            "       (SELECT row_idx FROM grid_cells WHERE id = recommendations.cell_id) "
            "           AS cell_row, "
            "       (SELECT col_idx FROM grid_cells WHERE id = recommendations.cell_id) "
            "           AS cell_col, "
            "       farm_id, tree_id, tree_code, tree_version, "
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
        cell_id: UUID | None = None,
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
                    (recommendation_id, block_id, cell_id, farm_id, from_state,
                     to_state, actor_user_id, details)
                VALUES (:rec, :block, :cell, :farm, :from_state, :to_state,
                        :actor, CAST(:details AS jsonb))
                """
            ).bindparams(
                bindparam("rec", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("cell", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "rec": recommendation_id,
                "block": block_id,
                "cell": cell_id,
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

    async def get_latest_cell_aggregates(
        self, *, block_id: UUID
    ) -> dict[UUID, dict[str, dict[str, Any]]]:
        """Latest per-cell mean per index for the block's active grid(s).

        Shape ``{cell_id: {index_code: {time, mean}}}`` — the per-cell analogue
        of :meth:`get_latest_aggregate_per_index`, read from
        ``block_grid_aggregates`` (the grid module's cell-grain hypertable).
        Only cells of a non-retired grid config are included. Drives the
        per-cell evaluation path for ``scope='cell'`` trees (PR-C3); empty when
        the block has no grid, so cell-scoped trees simply don't fire there.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT DISTINCT ON (obs.cell_id, obs.index_code)
                               obs.cell_id, obs.index_code, obs.time, obs.mean
                        FROM block_grid_aggregates obs
                        JOIN grid_cells gc ON gc.id = obs.cell_id
                        -- Valid time, not transaction time: the latest
                        -- observation per cell may predate a rezone, and
                        -- filtering on `retired_at IS NULL` would drop it
                        -- entirely rather than serve it from the geometry
                        -- that produced it (tenant migration 0054).
                        JOIN grid_configs cfg
                          ON cfg.id = gc.grid_config_id
                         AND cfg.deleted_at IS NULL
                         AND cfg.superseded_at IS NULL
                         AND tstzrange(cfg.effective_from, cfg.effective_to)
                             @> obs.time
                        WHERE obs.block_id = :block_id
                        ORDER BY obs.cell_id, obs.index_code, obs.time DESC
                        """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id},
                )
            )
            .mappings()
            .all()
        )
        out: dict[UUID, dict[str, dict[str, Any]]] = {}
        for row in rows:
            out.setdefault(row["cell_id"], {})[row["index_code"]] = {
                "time": row["time"],
                "mean": row["mean"],
            }
        return out

    async def get_index_trends(
        self, *, block_id: UUID, window_days: int = 30
    ) -> dict[str, dict[str, Any]]:
        """Trend features per index_code over the last ``window_days`` of
        ``block_index_aggregates`` means (KB P2).

        Returns ``{index_code: {slope, delta, trend_direction}}`` computed
        by the pure ``indices.trends.compute_trend``. Indices with fewer
        than two valid means in the window are omitted (the merge then
        leaves their trend fields ``None``, so trend predicates fail
        closed). 30 days ≈ up to ~6 Sentinel-2 revisits, usually enough
        for a 2-4-point fit after cloud masking.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT index_code, time, mean
                        FROM block_index_aggregates
                        WHERE block_id = :block_id
                          AND mean IS NOT NULL
                          AND time >= now() - make_interval(days => :window_days)
                        ORDER BY index_code, time
                        """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id, "window_days": window_days},
                )
            )
            .mappings()
            .all()
        )
        series: dict[str, list[tuple[Any, Any]]] = {}
        for row in rows:
            series.setdefault(row["index_code"], []).append((row["time"], row["mean"]))

        out: dict[str, dict[str, Any]] = {}
        for code, points in series.items():
            trend = compute_trend(points)
            if trend.direction is None:
                continue
            out[code] = {
                "slope": trend.slope,
                "delta": trend.delta,
                "trend_direction": trend.direction,
            }
        return out

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

    async def get_farm_country_code(self, *, farm_id: UUID) -> str | None:
        """Return the farm's ``country_code`` (PR-1) — a block inherits its
        country from its parent farm for decision-tree country targeting."""
        row = (
            await self._tenant.execute(
                text(
                    "SELECT country_code FROM farms WHERE id = :farm_id AND deleted_at IS NULL"
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        ).first()
        return row.country_code if row is not None else None

    async def get_block_soil(self, *, block_id: UUID) -> tuple[str | None, str | None]:
        """Return (soil_texture, salinity_class) for the block — block-source
        fields read by the recommendation engine (e.g. sandy -> SAVI path)."""
        row = (
            await self._tenant.execute(
                text(
                    "SELECT soil_texture, salinity_class FROM blocks "
                    "WHERE id = :block_id AND deleted_at IS NULL"
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                {"block_id": block_id},
            )
        ).first()
        if row is None:
            return None, None
        return row.soil_texture, row.salinity_class

    async def get_block_current_crop(
        self, *, block_id: UUID
    ) -> tuple[UUID | None, UUID | None, str | None, str | None]:
        """Return (block_crop_id, crop_id, growth_stage, crop_path) for the
        active assignment, or all-None if none.

        ``growth_stage`` (KB P3) is the stored phenological stage on the
        block_crops row, advanced daily by the phenology task; conditions
        read it as ``{source: block, field: growth_stage}``.

        ``crop_path`` is the denormalized hierarchical taxonomy code
        (``mango.alphonso.short`` / ``cotton``). It drives decision-tree
        path-prefix *targeting* and is stamped on every recommendation — it is
        no longer readable as a condition, since the targeting already says
        which crops the tree runs on."""
        row = (
            await self._tenant.execute(
                text(
                    """
                    SELECT id AS block_crop_id, crop_id, growth_stage, crop_path
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
            return None, None, None, None
        return (
            row.block_crop_id,
            row.crop_id,
            row.growth_stage,
            row.crop_path,
        )

    async def list_crop_attribute_codes_for_paths(self, *, paths: list[str]) -> set[str]:
        """Active crop-attribute codes reachable from any of ``paths``.

        Matches the taxonomy in both directions, which is what "reachable"
        means for a decision tree: a definition at ``mango`` resolves for a
        ``mango.keitt`` block, and a tree targeting ``mango`` runs on blocks
        that may carry ``mango.keitt``, so a definition one level deeper is
        reachable too.

        ``starts_with`` rather than ``LIKE`` on purpose: crop paths contain
        underscores (``sugar_beet``), and ``_`` is a single-character
        wildcard in LIKE — ``path LIKE 'sugar_beet.%'`` would also match
        ``sugarXbeet.something``.
        """
        if not paths:
            return set()
        rows = (
            await self._public.execute(
                text(
                    """
                    SELECT DISTINCT d.code
                    FROM public.crop_attribute_definitions d
                    WHERE d.is_active = TRUE
                      AND EXISTS (
                          SELECT 1
                          FROM unnest(CAST(:paths AS text[])) AS t(p)
                          WHERE d.path = t.p
                             OR starts_with(t.p, d.path || '.')
                             OR starts_with(d.path, t.p || '.')
                      )
                    """
                ),
                {"paths": list(paths)},
            )
        ).all()
        return {r.code for r in rows}

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

    async def list_blocks_for_targeting(self) -> list[dict[str, Any]]:
        """Every active block with the attributes the targeting matcher reads
        (crop path/id, parent-farm country, soil) plus display labels.

        Drives the dry-run candidate-block picker: the author service filters
        these through ``tree_targets_block`` so the dropdown only offers blocks
        the tree would actually fire on.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT b.id          AS block_id,
                           b.name        AS block_name,
                           b.code        AS block_code,
                           b.soil_texture,
                           f.name        AS farm_name,
                           f.country_code,
                           bc.crop_id,
                           bc.crop_path
                    FROM blocks b
                    JOIN farms f
                      ON f.id = b.farm_id AND f.deleted_at IS NULL
                    LEFT JOIN block_crops bc
                      ON bc.block_id = b.id
                     AND bc.is_current = TRUE
                     AND bc.deleted_at IS NULL
                    WHERE b.deleted_at IS NULL
                      AND b.active_from <= current_date
                      AND (b.active_to IS NULL OR b.active_to > current_date)
                    ORDER BY f.name, b.code
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def get_grid_cell_labels(self, *, block_id: UUID) -> dict[UUID, tuple[int, int]]:
        """``{cell_id: (row_idx, col_idx)}`` for the block's live grid.

        The dry-run needs the zone label for every cell it reports, and joining
        per cell in the response loop would be one query per cell.

        ``grid_cells`` carries no ``block_id`` — a cell belongs to a *grid
        config*, and the config is what belongs to the block. Ownership has to
        be reached through the join.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT gc.id, gc.row_idx, gc.col_idx
                        FROM grid_cells gc
                        JOIN grid_configs cfg
                          ON cfg.id = gc.grid_config_id
                         AND cfg.deleted_at IS NULL
                         AND cfg.superseded_at IS NULL
                        WHERE cfg.block_id = :block_id
                        """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id},
                )
            )
            .mappings()
            .all()
        )
        return {r["id"]: (r["row_idx"], r["col_idx"]) for r in rows}

    # ---- Evaluation lineage (tenant 0062) ------------------------------

    async def open_eval_run(self, *, kind: str, actor_user_id: UUID | None) -> UUID:
        """Start a run and return its id. Counters are filled in by
        ``close_eval_run`` once the work is done."""
        run_id = (
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO decision_tree_eval_runs (kind, actor_user_id)
                    VALUES (:kind, :actor)
                    RETURNING id
                    """
                ),
                {"kind": kind, "actor": actor_user_id},
            )
        ).scalar_one()
        return cast(UUID, run_id)

    async def close_eval_run(
        self,
        *,
        run_id: UUID,
        blocks_evaluated: int,
        trees_evaluated: int,
        trees_skipped: int,
        recommendations_opened: int,
        alerts_opened: int,
        traces_written: int,
        outcome: str = "ok",
        error: str | None = None,
    ) -> None:
        """Stamp the run's totals and finish time.

        ``duration_ms`` is derived in SQL from ``started_at`` rather than timed
        in Python: the sweep runs each block in its own transaction, so a
        wall-clock measured around the loop would not survive a worker restart
        mid-run, and the row already knows when it opened.
        """
        await self._tenant.execute(
            text(
                """
                UPDATE decision_tree_eval_runs
                   SET finished_at = now(),
                       duration_ms =
                           (EXTRACT(EPOCH FROM (now() - started_at)) * 1000)::int,
                       blocks_evaluated = :blocks,
                       trees_evaluated = :trees,
                       trees_skipped = :skipped,
                       recommendations_opened = :recs,
                       alerts_opened = :alerts,
                       traces_written = :traces,
                       outcome = :outcome,
                       error = :error
                 WHERE id = :run_id
                """
            ).bindparams(bindparam("run_id", type_=PG_UUID(as_uuid=True))),
            {
                "run_id": run_id,
                "blocks": blocks_evaluated,
                "trees": trees_evaluated,
                "skipped": trees_skipped,
                "recs": recommendations_opened,
                "alerts": alerts_opened,
                "traces": traces_written,
                "outcome": outcome,
                "error": error,
            },
        )

    async def insert_eval_traces(self, *, rows: list[dict[str, Any]]) -> int:
        """Bulk-insert one block's traces; returns the number written.

        One multi-row statement rather than a loop: a 121-cell grid with a
        cell-scoped tree contributes 121 rows for a single block, and a round
        trip per row would make the lineage cost more than the evaluation it
        describes.
        """
        if not rows:
            return 0
        params = [
            {
                "run_id": r["run_id"],
                "farm_id": r["farm_id"],
                "block_id": r["block_id"],
                "cell_id": r["cell_id"],
                "tree_id": r["tree_id"],
                "tree_code": r["tree_code"],
                "tree_version": r["tree_version"],
                "scope": r["scope"],
                "status": r["status"],
                "skip_axis": r["skip_axis"],
                "skip_detail": _serialize_jsonb(r["skip_detail"]),
                "node_path": _serialize_jsonb(r["node_path"]),
                "resolved_values": _serialize_jsonb(r["resolved_values"]),
                "param_overrides": _serialize_jsonb(r["param_overrides"]),
                "outcome": _serialize_jsonb(r["outcome"]),
                "recommendation_id": r["recommendation_id"],
                "alert_id": r["alert_id"],
                "duration_ms": r["duration_ms"],
                "error": r["error"],
            }
            for r in rows
        ]
        await self._tenant.execute(
            text(
                """
                INSERT INTO decision_tree_eval_traces (
                    run_id, farm_id, block_id, cell_id,
                    tree_id, tree_code, tree_version, scope, status,
                    skip_axis, skip_detail, node_path, resolved_values,
                    param_overrides, outcome, recommendation_id, alert_id,
                    duration_ms, error
                ) VALUES (
                    :run_id, :farm_id, :block_id, :cell_id,
                    :tree_id, :tree_code, :tree_version, :scope, :status,
                    :skip_axis, CAST(:skip_detail AS jsonb),
                    CAST(:node_path AS jsonb), CAST(:resolved_values AS jsonb),
                    CAST(:param_overrides AS jsonb), CAST(:outcome AS jsonb),
                    :recommendation_id, :alert_id, :duration_ms, :error
                )
                """
            ).bindparams(
                bindparam("run_id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("cell_id", type_=PG_UUID(as_uuid=True)),
                bindparam("tree_id", type_=PG_UUID(as_uuid=True)),
                bindparam("recommendation_id", type_=PG_UUID(as_uuid=True)),
                bindparam("alert_id", type_=PG_UUID(as_uuid=True)),
            ),
            params,
        )
        return len(params)

    async def list_eval_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT id, kind, actor_user_id, started_at, finished_at,
                           duration_ms, blocks_evaluated, trees_evaluated,
                           trees_skipped, recommendations_opened, alerts_opened,
                           traces_written, outcome, error
                    FROM decision_tree_eval_runs
                    ORDER BY started_at DESC, id DESC
                    LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def list_eval_traces(
        self,
        *,
        run_id: UUID | None = None,
        block_id: UUID | None = None,
        farm_id: UUID | None = None,
        tree_code: str | None = None,
        status_filter: tuple[str, ...] = (),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Trace rows newest-first, with block and cell labels resolved.

        ``node_path`` and ``resolved_values`` are deliberately **not** selected
        here — a 200-row page of full walks is megabytes of JSONB the list view
        never renders. ``get_eval_trace`` fetches them for one row.
        """
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        # Built alongside the clauses, never unconditionally: `bindparams`
        # raises ArgumentError for a parameter the statement does not
        # mention, so declaring all three up front 500s every call that
        # omits one.
        binds: list[Any] = []
        for name, value in (
            ("run_id", run_id),
            ("block_id", block_id),
            ("farm_id", farm_id),
        ):
            if value is None:
                continue
            clauses.append(f"t.{name} = :{name}")
            params[name] = value
            binds.append(bindparam(name, type_=PG_UUID(as_uuid=True)))
        if tree_code is not None:
            clauses.append("t.tree_code = :tree_code")
            params["tree_code"] = tree_code
        if status_filter:
            clauses.append("t.status = ANY(:statuses)")
            params["statuses"] = list(status_filter)
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # S608: every fragment above is a literal from the closed set of
        # conditions; all values travel as bind parameters.
        sql = (
            "SELECT t.id, t.run_id, t.evaluated_at, t.farm_id, t.block_id, "  # noqa: S608
            "       t.cell_id, t.tree_id, t.tree_code, t.tree_version, "
            "       t.scope, t.status, t.skip_axis, t.skip_detail, "
            "       t.outcome, t.recommendation_id, t.alert_id, "
            "       t.duration_ms, t.error, "
            "       COALESCE(b.name, b.code) AS block_name, "
            "       c.row_idx AS cell_row, c.col_idx AS cell_col "
            "FROM decision_tree_eval_traces t "
            "LEFT JOIN blocks b ON b.id = t.block_id "
            "LEFT JOIN grid_cells c ON c.id = t.cell_id"
            f"{where_sql} "
            "ORDER BY t.evaluated_at DESC, t.id DESC "
            "LIMIT :limit"
        )
        rows = (await self._tenant.execute(text(sql).bindparams(*binds), params)).mappings().all()
        return [dict(r) for r in rows]

    async def get_eval_trace(self, *, trace_id: UUID) -> dict[str, Any] | None:
        """One trace with its full walk — the drill-down payload."""
        row = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT t.*,
                           COALESCE(b.name, b.code) AS block_name,
                           c.row_idx AS cell_row, c.col_idx AS cell_col
                    FROM decision_tree_eval_traces t
                    LEFT JOIN blocks b ON b.id = t.block_id
                    LEFT JOIN grid_cells c ON c.id = t.cell_id
                    WHERE t.id = :trace_id
                    """
                    ).bindparams(bindparam("trace_id", type_=PG_UUID(as_uuid=True))),
                    {"trace_id": trace_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None
