"""Shared helpers for backfilling per-cell aggregates onto a grid (G-5).

After a rezone (new cell size -> new cells) the fresh grid has no
observations until the next scene lands. Backfill re-runs
``compute_indices`` for past succeeded ingestion jobs so historical
scenes repopulate ``block_grid_aggregates`` on the new cells. The compute
task is idempotent on the block-level UNIQUE, so re-processing only adds
the missing per-cell rows.

The work is opt-in and potentially heavy (each scene re-reads its raw
bands COG), so it runs as the ``grid.backfill_block`` Celery task, never
inline in a request. Both the task and the standalone
``scripts/grid_backfill`` CLI share :func:`extract_raw_bands_key` so the
two asset-manifest shapes stay decoded the same way.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession


def extract_raw_bands_key(assets: Any) -> str | None:
    """Pull the raw-bands object key out of a job's ``assets_written``.

    Two shapes coexist in the wild:
      * dict ``{"raw_bands": {"href": "s3://bucket/key", ...}, ...}`` from
        the production ``compute_indices`` path.
      * list ``[".../raw_bands.tif", ...]`` from the local upload script.
    Returns the storage key (sans ``s3://bucket/``) or ``None`` if absent.
    """
    if isinstance(assets, dict):
        raw_bands = assets.get("raw_bands") or {}
        if isinstance(raw_bands, dict):
            href = raw_bands.get("href")
            if isinstance(href, str) and href.startswith("s3://"):
                return href.split("/", 3)[-1]
    elif isinstance(assets, list):
        for entry in assets:
            if isinstance(entry, str) and entry.endswith("raw_bands.tif"):
                return entry
    return None


async def list_backfill_jobs(
    session: AsyncSession,
    *,
    block_id: UUID,
    product_id: UUID,
    since: datetime | None,
    limit: int,
) -> list[dict[str, str]]:
    """Succeeded ingestion jobs for (block, product) with a raw-bands key.

    Returns ``[{job_id, scene_datetime, raw_bands_key}]`` newest-first.
    Caller must have set the tenant search_path on ``session``.
    """
    since_clause = "AND scene_datetime >= :since" if since is not None else ""
    stmt = text(
        f"""
        SELECT id::text AS job_id, scene_datetime, assets_written
        FROM imagery_ingestion_jobs
        WHERE block_id   = :block
          AND product_id = :product
          AND status     = 'succeeded'
          AND stac_item_id IS NOT NULL
          {since_clause}
        ORDER BY scene_datetime DESC
        LIMIT :limit
        """  # noqa: S608 - since_clause is a fixed literal, not user input
    ).bindparams(
        bindparam("block", type_=PG_UUID(as_uuid=True)),
        bindparam("product", type_=PG_UUID(as_uuid=True)),
    )
    params: dict[str, object] = {
        "block": block_id,
        "product": product_id,
        "limit": limit,
    }
    if since is not None:
        params["since"] = since
    rows = (await session.execute(stmt, params)).mappings().all()
    out: list[dict[str, str]] = []
    for r in rows:
        raw_key = extract_raw_bands_key(r["assets_written"])
        if raw_key is None:
            continue
        out.append(
            {
                "job_id": r["job_id"],
                "scene_datetime": str(r["scene_datetime"]),
                "raw_bands_key": raw_key,
            }
        )
    return out
