"""Sync decision-tree YAML files on disk into the public catalog.

The seed YAMLs live in ``app/modules/recommendations/seeds/*.yaml``.
Each file authors one tree. ``sync_from_disk`` reads them, compiles
them to JSON, and upserts ``public.decision_trees`` +
``public.decision_tree_versions`` so the catalog matches what's on
disk. Idempotent — re-running with no YAML changes is a no-op.

Compilation is structural validation only: we check the node graph is
walkable (root exists, every ``on_match``/``on_miss`` resolves, every
leaf has an outcome, no obvious cycles via reachability). Predicate
syntax inside ``condition.tree`` is left to the shared evaluator —
malformed predicates simply never match at runtime, matching the
"permissive on missing data" contract.

Crop FK resolution: YAML references crops by their stable ``crops.code``
(e.g. ``citrus``); the loader resolves to ``crops.id`` at sync time.
A null / missing ``crop_code`` means "applies to any crop".

Called once at app startup from ``_lifespan``. Tests that need the
catalog populated call it directly with a fixture session.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.models import DecisionTree

_log = get_logger(__name__)

_SEEDS_DIR = Path(__file__).parent / "seeds"


def _seed_files() -> Iterable[Path]:
    if not _SEEDS_DIR.exists():
        return ()
    return sorted(_SEEDS_DIR.glob("*.yaml"))


def compile_tree(spec: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    """Validate + normalize an authored YAML spec into the compiled JSON
    shape consumed by ``engine.evaluate_tree``.

    Raises ``DecisionTreeParseError`` on structural problems (missing
    root, dangling pointer, leaf without outcome). The exception is
    surfaced at startup-time sync; never at request time.
    """
    if not isinstance(spec, dict):
        raise DecisionTreeParseError(path=source_path, detail="top-level must be a mapping")

    code = spec.get("code")
    if not isinstance(code, str) or not code:
        raise DecisionTreeParseError(path=source_path, detail="missing 'code'")

    name_en = spec.get("name_en")
    if not isinstance(name_en, str) or not name_en:
        raise DecisionTreeParseError(path=source_path, detail="missing 'name_en'")

    nodes_raw = spec.get("nodes")
    if not isinstance(nodes_raw, dict) or not nodes_raw:
        raise DecisionTreeParseError(path=source_path, detail="'nodes' must be a non-empty mapping")

    root = spec.get("root", "root")
    if not isinstance(root, str) or root not in nodes_raw:
        raise DecisionTreeParseError(
            path=source_path,
            detail=f"'root' {root!r} is not a node in 'nodes'",
        )

    # Walk reachability so a typo in on_match/on_miss surfaces here, not
    # at sweep time when a tenant block hits the dead branch.
    _validate_reachability(nodes_raw, root, source_path)

    compiled: dict[str, Any] = {
        "code": code,
        "name_en": name_en,
        "name_ar": spec.get("name_ar"),
        "description_en": spec.get("description_en"),
        "description_ar": spec.get("description_ar"),
        "crop_code": spec.get("crop_code"),
        "applicable_regions": list(spec.get("applicable_regions") or []),
        "root": root,
        "nodes": nodes_raw,
    }
    return compiled


def _validate_reachability(
    nodes: dict[str, Any], root: str, source_path: str, *, max_steps: int = 1024
) -> None:
    seen: set[str] = set()
    stack: list[str] = [root]
    steps = 0
    while stack:
        steps += 1
        if steps > max_steps:
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"reachability check exceeded {max_steps} steps",
            )
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes.get(nid)
        if not isinstance(node, dict):
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"node {nid!r} is not a mapping",
            )
        if "outcome" in node:
            outcome = node["outcome"]
            if not isinstance(outcome, dict):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"leaf {nid!r} 'outcome' must be a mapping",
                )
            if not isinstance(outcome.get("action_type"), str):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"leaf {nid!r} 'outcome.action_type' must be a string",
                )
            continue
        # Decision node — both branches must point at known nodes.
        for branch in ("on_match", "on_miss"):
            target = node.get(branch)
            if not isinstance(target, str) or target not in nodes:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"node {nid!r} {branch!r} → {target!r} is not a known node",
                )
            stack.append(target)


def _hash_compiled(compiled: dict[str, Any]) -> str:
    payload = json.dumps(compiled, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _resolve_crop_id(public_session: AsyncSession, crop_code: str | None) -> Any:
    if not crop_code:
        return None
    row = (
        await public_session.execute(
            text("SELECT id FROM public.crops WHERE code = :c AND deleted_at IS NULL"),
            {"c": crop_code},
        )
    ).first()
    if row is None:
        _log.warning("decision_tree_unknown_crop_code", crop_code=crop_code)
        return None
    return row.id


async def sync_from_disk(public_session: AsyncSession) -> dict[str, int]:
    """Read every YAML in seeds/ and upsert the public catalog.

    Idempotent. For each file:

      * If no `decision_trees` row exists for the code, insert one.
      * Compile + hash the YAML; compare hash to the latest version row
        for the tree. If different (or no version exists), insert a new
        version row, advance ``decision_trees.current_version_id``, and
        stamp ``published_at = now()``.
      * Otherwise leave both rows alone.

    Returns counts so the lifespan startup can log a one-line summary.
    """
    files = list(_seed_files())
    trees_seen = 0
    versions_inserted = 0

    for path in files:
        trees_seen += 1
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        compiled = compile_tree(raw, source_path=str(path))
        compiled_hash = _hash_compiled(compiled)
        crop_code = compiled.get("crop_code")
        crop_id = await _resolve_crop_id(public_session, crop_code)

        # Fetch existing tree by code.
        existing = (
            (
                await public_session.execute(
                    select(DecisionTree).where(
                        DecisionTree.code == compiled["code"], DecisionTree.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .one_or_none()
        )

        if existing is None:
            tree_id = await _insert_tree(
                public_session,
                code=compiled["code"],
                name_en=compiled["name_en"],
                name_ar=compiled.get("name_ar"),
                description_en=compiled.get("description_en"),
                description_ar=compiled.get("description_ar"),
                crop_id=crop_id,
                applicable_regions=compiled.get("applicable_regions") or [],
            )
            latest_version: int | None = None
            latest_hash: str | None = None
        else:
            tree_id = existing.id
            # Patch metadata that may have evolved on disk (name etc.).
            await public_session.execute(
                text(
                    """
                    UPDATE public.decision_trees
                       SET name_en = :name_en,
                           name_ar = :name_ar,
                           description_en = :description_en,
                           description_ar = :description_ar,
                           crop_id = :crop_id,
                           applicable_regions = :applicable_regions,
                           is_active = TRUE,
                           updated_at = now()
                     WHERE id = :id
                    """
                ),
                {
                    "name_en": compiled["name_en"],
                    "name_ar": compiled.get("name_ar"),
                    "description_en": compiled.get("description_en"),
                    "description_ar": compiled.get("description_ar"),
                    "crop_id": crop_id,
                    "applicable_regions": compiled.get("applicable_regions") or [],
                    "id": tree_id,
                },
            )
            latest = await _latest_version_for_tree(public_session, tree_id)
            latest_version = latest[0] if latest else None
            latest_hash = latest[1] if latest else None

        if latest_hash == compiled_hash:
            continue

        next_version = (latest_version or 0) + 1
        version_id = await _insert_version(
            public_session,
            tree_id=tree_id,
            version=next_version,
            tree_yaml=path.read_text(encoding="utf-8"),
            tree_compiled=compiled,
            compiled_hash=compiled_hash,
            published_at=datetime.now(UTC),
        )
        await public_session.execute(
            text(
                "UPDATE public.decision_trees SET current_version_id = :vid, "
                "updated_at = now() WHERE id = :tid"
            ),
            {"vid": version_id, "tid": tree_id},
        )
        versions_inserted += 1

    await public_session.commit()
    _log.info(
        "decision_trees_sync_done",
        trees_seen=trees_seen,
        versions_inserted=versions_inserted,
    )
    return {"trees_seen": trees_seen, "versions_inserted": versions_inserted}


async def _insert_tree(
    session: AsyncSession,
    *,
    code: str,
    name_en: str,
    name_ar: str | None,
    description_en: str | None,
    description_ar: str | None,
    crop_id: Any,
    applicable_regions: list[str],
) -> Any:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO public.decision_trees
                    (code, name_en, name_ar, description_en, description_ar,
                     crop_id, applicable_regions, is_active)
                VALUES (:code, :name_en, :name_ar, :description_en, :description_ar,
                        :crop_id, :applicable_regions, TRUE)
                RETURNING id
                """
            ),
            {
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "description_en": description_en,
                "description_ar": description_ar,
                "crop_id": crop_id,
                "applicable_regions": applicable_regions,
            },
        )
    ).first()
    return row.id


async def _latest_version_for_tree(session: AsyncSession, tree_id: Any) -> tuple[int, str] | None:
    row = (
        await session.execute(
            text(
                "SELECT version, compiled_hash FROM public.decision_tree_versions "
                "WHERE tree_id = :tid ORDER BY version DESC LIMIT 1"
            ),
            {"tid": tree_id},
        )
    ).first()
    if row is None:
        return None
    return row.version, row.compiled_hash


async def _insert_version(
    session: AsyncSession,
    *,
    tree_id: Any,
    version: int,
    tree_yaml: str,
    tree_compiled: dict[str, Any],
    compiled_hash: str,
    published_at: datetime,
) -> Any:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO public.decision_tree_versions
                    (tree_id, version, tree_yaml, tree_compiled,
                     compiled_hash, published_at)
                VALUES (:tid, :version, :yaml, CAST(:compiled AS jsonb),
                        :hash, :published_at)
                RETURNING id
                """
            ),
            {
                "tid": tree_id,
                "version": version,
                "yaml": tree_yaml,
                "compiled": json.dumps(tree_compiled),
                "hash": compiled_hash,
                "published_at": published_at,
            },
        )
    ).first()
    return row.id
