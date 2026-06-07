"""Re-trigger compute_indices for past scenes so they populate the new
``block_grid_aggregates`` rows.

Use after enabling a grid_config on a block to back-fill cell history.
Walks ``imagery_ingestion_jobs`` for the (tenant, block, product)
combination and queues one Celery task per succeeded job. The compute
task is idempotent: existing ``block_index_aggregates`` rows collide on
the UNIQUE key and DO NOTHING; new cell rows land in
``block_grid_aggregates``.

Run as::

    python -m scripts.grid_backfill \\
        --tenant-schema tenant_<hex> \\
        --block <uuid> \\
        --product <uuid> \\
        [--since 2026-01-01] [--limit 50] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.settings import get_settings
from app.modules.grid.backfill import extract_raw_bands_key

logger = logging.getLogger("grid_backfill")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-schema", required=True, help="tenant_<hex>")
    p.add_argument("--block", required=True, type=UUID, help="Block UUID")
    p.add_argument("--product", required=True, type=UUID, help="Imagery product UUID")
    p.add_argument(
        "--since",
        type=lambda s: datetime.fromisoformat(s),
        default=None,
        help="Only re-process scenes after this ISO datetime.",
    )
    p.add_argument("--limit", type=int, default=200, help="Cap on jobs to queue.")
    p.add_argument("--dry-run", action="store_true", help="List only; don't queue.")
    return p.parse_args()


def _list_jobs(
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    since: datetime | None,
    limit: int,
) -> list[dict[str, str]]:
    """Return [{job_id, scene_datetime, raw_bands_key}] for succeeded jobs."""
    settings = get_settings()
    engine = create_engine(str(settings.database_sync_url), future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{tenant_schema}", public'))
            since_clause = "AND scene_datetime >= :since" if since is not None else ""
            stmt = text(
                f"""
                SELECT id::text       AS job_id,
                       scene_datetime,
                       assets_written
                FROM imagery_ingestion_jobs
                WHERE block_id   = :block
                  AND product_id = :product
                  AND status     = 'succeeded'
                  AND stac_item_id IS NOT NULL
                  {since_clause}
                ORDER BY scene_datetime DESC
                LIMIT :limit
                """
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
            rows = conn.execute(stmt, params).mappings().all()
            out: list[dict[str, str]] = []
            for r in rows:
                # Shared with the grid.backfill_block task so both decode
                # the two asset-manifest shapes identically.
                raw_key = extract_raw_bands_key(r["assets_written"])
                if raw_key is None:
                    logger.warning(
                        "skip job=%s — no raw_bands key in assets_written",
                        r["job_id"],
                    )
                    continue
                out.append(
                    {
                        "job_id": r["job_id"],
                        "scene_datetime": str(r["scene_datetime"]),
                        "raw_bands_key": raw_key,
                    }
                )
            return out
    finally:
        engine.dispose()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    jobs = _list_jobs(
        tenant_schema=args.tenant_schema,
        block_id=args.block,
        product_id=args.product,
        since=args.since,
        limit=args.limit,
    )
    logger.info("found %d candidate jobs", len(jobs))

    if args.dry_run:
        for j in jobs:
            logger.info("would re-process %s @ %s", j["job_id"], j["scene_datetime"])
        return 0

    from app.modules.imagery.tasks import compute_indices

    for j in jobs:
        compute_indices.delay(j["job_id"], args.tenant_schema, j["raw_bands_key"])
        logger.info("queued %s @ %s", j["job_id"], j["scene_datetime"])
    logger.info("done — queued %d compute_indices tasks", len(jobs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
