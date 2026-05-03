"""pgstac collection + item helpers.

We use pypgstac's bundled SQL helpers via plain SQL calls:
``pgstac.create_collection(jsonb)`` and ``pgstac.create_items(jsonb)``.
Both take a STAC JSON object and handle partitioning + validation.
data_model.md § 6.6 mandates per-tenant collection IDs of the form
``tenant_<uuid>__<product_code>`` so the per-tenant RLS policy on
``pgstac.items`` can isolate by ``collection LIKE 'tenant_<id>__%'``.

Collections are created lazily on first ingestion (Q3 in the PR-A
plan) — no upfront seeding at tenant bootstrap. The lazy create is
idempotent via ``ON CONFLICT DO NOTHING`` semantics (pypgstac's
``create_collection`` upserts by id).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

# A single tenant_<uuid>__<product_code> string ID.
_COLLECTION_RE = re.compile(r"^tenant_[a-z0-9_]{1,80}$")


class CollectionIdError(ValueError):
    """Raised when a collection id does not match the expected shape."""


def collection_id_for(tenant_schema: str, product_code: str) -> str:
    """Return the canonical collection id for a (tenant, product) pair.

    The tenant schema is already validated upstream
    (``app.shared.db.session.sanitize_tenant_schema``); we re-check
    here so a typo can't write a row outside the per-tenant RLS prefix.
    """
    if not _COLLECTION_RE.fullmatch(tenant_schema):
        raise CollectionIdError(f"Unexpected tenant schema: {tenant_schema!r}")
    if not re.fullmatch(r"^[a-z0-9_]+$", product_code):
        raise CollectionIdError(f"Unexpected product code: {product_code!r}")
    return f"{tenant_schema}__{product_code}"


def build_collection_doc(
    *,
    collection_id: str,
    product_code: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Minimal STAC Collection JSON.

    pgstac validates the ``id``, ``type``, ``description``, and
    ``extent`` fields at create time. Spatial extent is intentionally
    world-bounded so per-tenant collections don't have to be re-bounded
    every time a new block is added; queries always filter by
    ``collection LIKE`` plus geometry intersect anyway.
    """
    return {
        "type": "Collection",
        "id": collection_id,
        "title": f"{product_code} (tenant scope)",
        "description": description or f"MissionAgre {product_code} per-tenant collection.",
        "stac_version": "1.0.0",
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, None]]},
        },
    }


def build_item_doc(
    *,
    collection_id: str,
    item_id: str,
    geometry_geojson: dict[str, Any],
    bbox: tuple[float, float, float, float],
    scene_datetime_iso: str,
    assets: dict[str, dict[str, Any]],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal STAC Item JSON for a single ingested scene.

    ``item_id`` is expected to be the deterministic
    ``{provider}/{product}/{scene_id}/{aoi_hash}`` string per
    data_model § 6.6 — pgstac stores it verbatim and the tile server
    looks it up that way.

    ``assets`` maps role names (``raw_bands``, ``ndvi``, ...) to STAC
    Asset JSON. Adding asset entries later (e.g., when PR-C writes
    per-index COGs) is done via ``upsert_item`` with the merged set;
    pgstac's ``create_items`` is upsert-by-id.
    """
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": collection_id,
        "geometry": geometry_geojson,
        "bbox": list(bbox),
        "properties": {
            "datetime": scene_datetime_iso,
            **(properties or {}),
        },
        "assets": assets,
        "links": [],
    }


async def ensure_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    product_code: str,
) -> None:
    """Create the collection if absent. Idempotent.

    pypgstac's ``create_collection`` is upsert-by-id, so re-running is
    a no-op once the row exists.
    """
    doc = build_collection_doc(collection_id=collection_id, product_code=product_code)
    await session.execute(
        text("SELECT pgstac.create_collection(:doc)").bindparams(bindparam("doc", type_=JSONB)),
        {"doc": doc},
    )


async def upsert_item(
    session: AsyncSession,
    *,
    item_doc: dict[str, Any],
) -> None:
    """Insert or update one STAC item via pypgstac.

    pgstac's ``create_items`` is INSERT-only and raises on duplicate
    id. ``upsert_items`` is INSERT … ON CONFLICT DO UPDATE — exactly
    the contract we need so the imagery pipeline can call this once
    after ``register_stac_item`` (raw_bands only) and again after
    ``compute_indices`` (raw_bands + six index assets) without the
    second call colliding.
    """
    await session.execute(
        text("SELECT pgstac.upsert_items(:doc)").bindparams(bindparam("doc", type_=JSONB)),
        {"doc": [item_doc]},
    )
