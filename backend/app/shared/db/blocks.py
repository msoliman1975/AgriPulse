"""Cross-module helper: read a block's `farm_id` (and aoi_hash, geometry).

The farms module owns `blocks`, but the imagery and indices modules
both need to know which farm a block belongs to before they can run
per-farm RBAC checks. Going through `FarmService` would couple every
caller to a session-bearing service; instead we expose a single
side-effect-free reader here that takes a tenant session and returns
the few columns those callers actually need.

This is allowed under ARCHITECTURE.md § 6.1 — `app.shared` is the one
namespace where leaf utilities live; module boundaries forbid crossing
*module internals*, not reading rows other modules own.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def read_block_context(
    session: AsyncSession,
    *,
    block_id: UUID,
) -> dict[str, Any] | None:
    """Read farm_id, aoi_hash, and both boundary forms for a block.

    Returns ``None`` when the block doesn't exist or is soft-deleted.
    Callers translate ``None`` into a domain-appropriate 404.
    """
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                    b.farm_id,
                    b.aoi_hash,
                    ST_AsGeoJSON(b.boundary)::text AS boundary_geojson,
                    ST_AsGeoJSON(b.boundary_utm)::text AS boundary_utm_geojson
                FROM blocks b
                WHERE b.id = :id AND b.deleted_at IS NULL
                """
                ),
                {"id": block_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return {
        "farm_id": row["farm_id"],
        "aoi_hash": row["aoi_hash"],
        "boundary_geojson": json.loads(row["boundary_geojson"]),
        "boundary_utm_geojson": json.loads(row["boundary_utm_geojson"]),
    }
