"""Imagery reclamation — STAC items and the COGs behind them.

The hard part of purging imagery is that COG keys carry no tenant identity.
``app.modules.imagery.storage.build_asset_key`` produces

    {provider}/{product}/{scene_id}/{aoi_hash}/{band}.tif

and ``aoi_hash`` is derived from the block's geometry, so two blocks with an
identical AOI — including blocks in *different tenants* — resolve to the same
prefix. Deleting by prefix on purge would therefore be cross-tenant destructive.

So reclamation is refcounted:

* **STAC items** are always safe to delete. Collection ids are
  ``{tenant_schema}__{product_code}``, so an item belongs to exactly one tenant
  even when the object it points at is shared.
* **Objects** are deleted only when the ``aoi_hash`` is referenced by no block
  in any live tenant schema once the purge target is excluded. A shared AOI keeps
  its COGs, and the receipt reports how many were kept and why.

pgstac lives outside the tenant schema, which is why ``DROP SCHEMA … CASCADE``
never removed any of this and every tenant purged to date has left its full STAC
catalogue behind.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.session import sanitize_tenant_schema

logger = logging.getLogger(__name__)


@dataclass
class ReclaimPlan:
    """What imagery reclamation will do. Built before the delete, run after."""

    # (item_id, collection) pairs to remove from pgstac.
    items: list[tuple[str, str]] = field(default_factory=list)
    # Whole collections to drop — tenant purge only.
    collections: list[str] = field(default_factory=list)
    # Object-storage keys safe to delete (AOI referenced by nothing else).
    object_keys: list[str] = field(default_factory=list)
    # Keys left in place because another block still uses the same AOI.
    shared_keys_kept: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stac_items": len(self.items),
            "stac_collections": len(self.collections),
            "objects": len(self.object_keys),
            "objects_kept_shared": len(self.shared_keys_kept),
        }


@dataclass
class ReclaimResult:
    stac_items_deleted: int = 0
    stac_collections_deleted: int = 0
    objects_deleted: int = 0
    objects_kept_shared: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stac_items_deleted": self.stac_items_deleted,
            "stac_collections_deleted": self.stac_collections_deleted,
            "objects_deleted": self.objects_deleted,
            "objects_kept_shared": self.objects_kept_shared,
            "errors": self.errors,
        }


class ImageryReclaimer:
    """Plans and executes STAC + object cleanup for a purge.

    ``session`` must be a public-schema (admin) session: reclamation reaches
    across every tenant schema to refcount AOIs and into ``pgstac``, neither of
    which is reachable from a tenant-pinned session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # -- planning ------------------------------------------------------------

    async def plan_for_blocks(self, *, tenant_schema: str, block_ids: list[UUID]) -> ReclaimPlan:
        """Plan reclamation for specific blocks. Call before they are deleted."""
        safe = sanitize_tenant_schema(tenant_schema)
        plan = ReclaimPlan()
        if not block_ids:
            return plan

        hashes = await self._aoi_hashes(safe, block_ids)
        if not hashes:
            return plan

        shared = await self._shared_hashes(hashes, exclude_block_ids=block_ids)
        await self._collect_items(plan, collection_prefix=f"{safe}__", hashes=hashes, shared=shared)
        return plan

    async def plan_for_tenant(self, *, tenant_schema: str) -> ReclaimPlan:
        """Plan reclamation for a whole tenant, including its STAC collections."""
        safe = sanitize_tenant_schema(tenant_schema)
        plan = ReclaimPlan()

        block_ids = await self._all_block_ids(safe)
        hashes = await self._aoi_hashes(safe, block_ids) if block_ids else set()
        shared = await self._shared_hashes(hashes, exclude_block_ids=block_ids) if hashes else set()
        await self._collect_items(plan, collection_prefix=f"{safe}__", hashes=None, shared=shared)

        rows = await self._s.execute(
            text("SELECT id FROM pgstac.collections WHERE id LIKE :p"),
            {"p": f"{safe}__%"},
        )
        plan.collections = [r[0] for r in rows]
        return plan

    # -- execution -----------------------------------------------------------

    async def execute(self, plan: ReclaimPlan, *, storage: Any | None = None) -> ReclaimResult:
        """Run the plan. Safe to call after the DB transaction has committed.

        Every step is idempotent and individually guarded: a failure to delete
        one object must not abandon the rest, because the rows that referenced
        them are already gone and nothing would retry them.
        """
        result = ReclaimResult(objects_kept_shared=len(plan.shared_keys_kept))

        for item_id, collection in plan.items:
            try:
                await self._s.execute(
                    text("SELECT pgstac.delete_item(:i, :c)"),
                    {"i": item_id, "c": collection},
                )
                result.stac_items_deleted += 1
            except Exception as exc:
                result.errors.append(f"stac_item {item_id}: {exc}")

        for collection in plan.collections:
            try:
                await self._s.execute(
                    text("SELECT pgstac.delete_collection(:c)"), {"c": collection}
                )
                result.stac_collections_deleted += 1
            except Exception as exc:
                result.errors.append(f"stac_collection {collection}: {exc}")

        if storage is not None:
            for key in plan.object_keys:
                try:
                    storage.delete_object(key=key)
                    result.objects_deleted += 1
                except Exception as exc:
                    result.errors.append(f"object {key}: {exc}")

        return result

    # -- internals -----------------------------------------------------------

    async def _aoi_hashes(self, schema: str, block_ids: list[UUID]) -> set[str]:
        rows = await self._s.execute(
            text(
                f'SELECT DISTINCT aoi_hash FROM "{schema}".blocks '  # noqa: S608
                "WHERE id = ANY(:ids) AND aoi_hash IS NOT NULL"
            ).bindparams(bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
            {"ids": block_ids},
        )
        return {r[0] for r in rows}

    async def _all_block_ids(self, schema: str) -> list[UUID]:
        rows = await self._s.execute(text(f'SELECT id FROM "{schema}".blocks'))  # noqa: S608
        return [r[0] for r in rows]

    async def _shared_hashes(self, hashes: set[str], *, exclude_block_ids: list[UUID]) -> set[str]:
        """Subset of ``hashes`` still referenced by a block we are not deleting.

        Scans every live tenant schema — an AOI shared across tenants is exactly
        the case a prefix delete would get catastrophically wrong.
        """
        if not hashes:
            return set()
        from app.shared.purge.scanner import live_tenant_schemas

        schemas = await live_tenant_schemas(self._s)
        if not schemas:
            return set()
        # Schema names come from live_tenant_schemas(), which runs every one
        # through sanitize_tenant_schema; the hashes and ids are bound.
        union = " UNION ALL ".join(
            f'SELECT aoi_hash, id FROM "{s}".blocks WHERE aoi_hash IS NOT NULL'  # noqa: S608
            for s in schemas
        )
        rows = await self._s.execute(
            text(
                f"SELECT DISTINCT b.aoi_hash FROM ({union}) b "  # noqa: S608
                "WHERE b.aoi_hash = ANY(:hashes) AND NOT (b.id = ANY(:ids))"
            ).bindparams(
                bindparam("hashes", type_=ARRAY(Text())),
                bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))),
            ),
            {"hashes": list(hashes), "ids": exclude_block_ids},
        )
        return {r[0] for r in rows}

    async def _collect_items(
        self,
        plan: ReclaimPlan,
        *,
        collection_prefix: str,
        hashes: set[str] | None,
        shared: set[str],
    ) -> None:
        """Gather STAC items and split their assets into delete / keep.

        ``hashes=None`` means "every item in the tenant's collections" (tenant
        purge); otherwise only items whose deterministic id ends in one of the
        given AOI hashes.
        """
        rows = await self._s.execute(
            text("SELECT id, collection, content FROM pgstac.items WHERE collection LIKE :p"),
            {"p": f"{collection_prefix}%"},
        )
        for item_id, collection, content in rows:
            item_hash = _aoi_hash_of(item_id)
            if hashes is not None and item_hash not in hashes:
                continue
            plan.items.append((item_id, collection))
            keys = _asset_keys(content)
            if item_hash is not None and item_hash in shared:
                plan.shared_keys_kept.extend(keys)
            else:
                plan.object_keys.extend(keys)


def _aoi_hash_of(item_id: str) -> str | None:
    """Last path segment of the deterministic item id is the AOI hash.

    Item ids are ``{provider}/{product}/{scene_id}/{aoi_hash}`` — see
    ``app.modules.imagery.pgstac.build_item_doc``.
    """
    parts = item_id.split("/")
    return parts[-1] if len(parts) >= 4 else None


def _asset_keys(content: Any) -> list[str]:
    """Object keys referenced by a STAC item's assets.

    Hrefs are written as ``s3://{bucket}/{key}`` by the imagery pipeline. Any
    other shape (an http href from a future provider) is skipped rather than
    guessed at — deleting the wrong key is worse than leaking one.
    """
    if not isinstance(content, dict):
        return []
    keys: list[str] = []
    for asset in (content.get("assets") or {}).values():
        href = asset.get("href") if isinstance(asset, dict) else None
        if isinstance(href, str) and href.startswith("s3://"):
            _, _, rest = href.partition("s3://")
            _bucket, _, key = rest.partition("/")
            if key:
                keys.append(key)
    return keys
