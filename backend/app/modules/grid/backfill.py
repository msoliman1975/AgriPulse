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

# Per-(block, product) ceiling applied when a farm backfill runs without
# an explicit budget. Bounds the query rather than reading a decade of
# ingestion jobs into memory. Shared with the apply endpoint's estimate so
# the number reported and the number enqueued are capped identically.
DEFAULT_PER_PAIR_CAP = 2000


def _has_raw_bands_sql(col: str = "assets_written") -> str:
    """SQL mirror of :func:`extract_raw_bands_key`'s "is there one?" test.

    Built once and shared by every query that reasons about the
    backfillable set. The alternative — one query enumerating jobs and
    another counting them with a hand-copied predicate — is exactly the
    silent drift that made a first-time grid report zero queued scenes
    while hours of compute ran. A lock-step test pins this against the
    Python extractor over both manifest shapes.

    ``col`` is a caller-supplied column reference, never user input.
    """
    return f"""
        (
          (jsonb_typeof({col}) = 'object'
           AND {col} -> 'raw_bands' ->> 'href' LIKE 's3://%')
          OR
          (jsonb_typeof({col}) = 'array'
           AND EXISTS (
             SELECT 1 FROM jsonb_array_elements_text({col}) AS e
             WHERE e LIKE '%raw_bands.tif'
           ))
        )
    """  # noqa: S608 - `col` is a caller-supplied literal, never user input


def split_budget(total_candidates: int, *, budget: int | None) -> tuple[int, int]:
    """``(queued, stranded)`` for a candidate pool under a farm budget.

    :func:`allocate_budget` decides *which* scenes each grid gets; this
    decides how many run at all. The totals reduce to a clamp because the
    round-robin never leaves budget unspent while any queue still holds a
    scene — a property :mod:`tests.unit.grid.test_budget_allocation` pins
    against the allocator itself rather than restating here.
    """
    if budget is None:
        return total_candidates, 0
    queued = min(total_candidates, max(0, budget))
    return queued, total_candidates - queued


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


async def list_farm_grid_pairs(session: AsyncSession, *, farm_id: UUID) -> list[dict[str, Any]]:
    """``(block_id, product_id)`` for every live grid under a farm.

    Drives the farm-wide backfill fan-out. Caller must have set the tenant
    search_path on ``session``.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT cfg.block_id, cfg.product_id, b.code AS block_code
                    FROM grid_configs cfg
                    JOIN blocks b ON b.id = cfg.block_id AND b.deleted_at IS NULL
                    WHERE b.farm_id = :farm
                      AND cfg.retired_at IS NULL
                      AND cfg.deleted_at IS NULL
                    ORDER BY b.code
                    """
                ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                {"farm": farm_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def allocate_budget(
    jobs_by_pair: dict[tuple[UUID, UUID], list[dict[str, str]]],
    *,
    budget: int | None,
) -> tuple[dict[tuple[UUID, UUID], list[dict[str, str]]], int]:
    """Spread a farm-wide scene budget fairly across grids.

    Returns ``(allocated, stranded_count)``.

    Round-robin, newest scene first within each pair. Two properties this
    is chosen for:

    * **Fair share.** A single 500-scene block cannot swallow the whole
      farm budget and leave 35 blocks with nothing — which is exactly what
      the old per-block ``limit=200`` did at farm scale (36 x 200 = 7,200
      unbudgeted jobs, truncating silently per block with no farm-wide
      view).
    * **Newest first.** Recent history is what gets looked at, and it
      makes the settle step's ``effective_from`` walk backwards
      monotonically — the only order that yields a coherent two-geometry
      state when the budget doesn't cover everything.

    ``budget=None`` means "everything", so nothing is stranded.
    """
    remaining = {k: list(v) for k, v in jobs_by_pair.items()}
    total = sum(len(v) for v in remaining.values())
    if budget is None:
        return remaining, 0

    allocated: dict[tuple[UUID, UUID], list[dict[str, str]]] = {k: [] for k in remaining}
    left = max(0, budget)
    # Cycle the pairs, taking one scene each pass, until the budget runs
    # out or every queue is empty.
    while left > 0 and any(remaining.values()):
        for pair, queue in remaining.items():
            if left == 0:
                break
            if not queue:
                continue
            allocated[pair].append(queue.pop(0))
            left -= 1
    taken = sum(len(v) for v in allocated.values())
    return allocated, total - taken


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

    The raw-bands filter is applied in SQL as well as in the loop below,
    so ``LIMIT`` counts only rows that can actually become jobs. Without
    it a pair whose newest scenes lack the asset would silently return
    fewer than ``limit`` backfillable scenes while claiming to be capped.
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
          AND {_has_raw_bands_sql()}
          {since_clause}
        ORDER BY scene_datetime DESC
        LIMIT :limit
        """  # noqa: S608 - both interpolations are fixed literals, not user input
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


async def count_farm_backfill_candidates(
    session: AsyncSession,
    *,
    farm_id: UUID,
    since: datetime | None,
    per_pair_cap: int,
) -> int:
    """How many scenes a farm-wide backfill would have to recompute.

    Counts the same rows :func:`backfill_farm` would enqueue — every live
    grid under the farm, capped per pair exactly as ``list_backfill_jobs``
    caps it — without materialising them. The apply endpoint needs the
    number to report queued work honestly, and cannot pay for the real
    enumeration inside a request: that is thousands of rows per farm, and
    the whole reason the backfill is a task in the first place.

    Deliberately keyed on the farm's live grids rather than on the rows a
    given Apply wrote, because the task fans out over the former. An Apply
    that adds one grid to a farm that already has 35 really does queue all
    36 grids' worth of work, and saying otherwise would understate it.

    Caller must have set the tenant search_path on ``session``.
    """
    since_clause = "AND j.scene_datetime >= :since" if since is not None else ""
    stmt = text(
        f"""
        SELECT count(*) AS scenes
        FROM (
            SELECT row_number() OVER (
                       PARTITION BY j.block_id, j.product_id
                       ORDER BY j.scene_datetime DESC
                   ) AS rn
            FROM imagery_ingestion_jobs j
            JOIN grid_configs cfg
              ON cfg.block_id   = j.block_id
             AND cfg.product_id = j.product_id
             AND cfg.retired_at IS NULL
             AND cfg.deleted_at IS NULL
            JOIN blocks b
              ON b.id = cfg.block_id
             AND b.deleted_at IS NULL
             AND b.farm_id = :farm
            WHERE j.status = 'succeeded'
              AND j.stac_item_id IS NOT NULL
              AND {_has_raw_bands_sql("j.assets_written")}
              {since_clause}
        ) ranked
        WHERE rn <= :cap
        """  # noqa: S608 - both interpolations are fixed literals, not user input
    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True)))
    params: dict[str, object] = {"farm": farm_id, "cap": per_pair_cap}
    if since is not None:
        params["since"] = since
    return int((await session.execute(stmt, params)).scalar_one() or 0)
