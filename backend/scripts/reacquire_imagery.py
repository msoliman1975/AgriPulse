"""Re-acquire (re-fetch) imagery scenes so newly-deployed fetch code reruns.

Unlike ``grid_backfill`` (which only re-runs ``compute_indices`` over the
*existing* raw COG), this re-runs the full ``acquire_scene`` chain: it
re-fetches each scene from the provider, overwriting the raw COG at its
deterministic S3 key, then re-registers and re-computes. Use it to pick up a
change to the fetch path — e.g. the native-resolution + SCL-cloud-mask fix in
docs/reports/index-accuracy-agrosina-2026-06-20.md.

Two things make a naive re-run a no-op, so this script handles both:
  * ``acquire_scene`` short-circuits unless the job is ``pending`` — we reset
    matching succeeded jobs back to ``pending``.
  * ``block_index_aggregates`` / ``block_grid_aggregates`` upserts are
    ON CONFLICT DO NOTHING — re-computing would keep the OLD rows. We DELETE
    the affected (block, time, product) aggregate rows first so the recompute
    writes fresh values.

Run INSIDE a worker/api pod (needs DB + the Celery broker + provider creds)::

    python -m scripts.reacquire_imagery \
        --tenant-schema tenant_<hex> \
        [--subscription <uuid>[,<uuid>...]] \
        [--since 2026-03-01] [--limit 500] [--dry-run]

``--dry-run`` lists what it would do and touches nothing. Without
``--subscription`` it targets every succeeded job in the tenant schema.

NOTE ON COVERAGE: this only re-acquires scenes already discovered (rows in
``imagery_ingestion_jobs``). It does not widen the discovery window — going
further back than the existing history is a separate historical-backfill job
(the discovery floor is 90 days; see docs/proposals + the backfill tooling).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings

logger = logging.getLogger("reacquire_imagery")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-schema", required=True, help="tenant_<hex>")
    p.add_argument(
        "--subscription",
        default="",
        help="Comma-separated imagery_aoi_subscriptions UUIDs (default: all in tenant).",
    )
    p.add_argument(
        "--since",
        type=lambda s: datetime.fromisoformat(s),
        default=None,
        help="Only re-acquire scenes sensed on/after this ISO datetime.",
    )
    p.add_argument("--limit", type=int, default=1000, help="Cap on jobs to re-acquire.")
    p.add_argument("--dry-run", action="store_true", help="List only; touch nothing.")
    return p.parse_args()


def _list_jobs(
    conn: Connection,
    *,
    subscription_ids: list[UUID],
    since: datetime | None,
    limit: int,
) -> list[dict[str, object]]:
    clauses = ["status = 'succeeded'", "stac_item_id IS NOT NULL"]
    params: dict[str, object] = {"limit": limit}
    if subscription_ids:
        clauses.append("subscription_id IN :subs")
        params["subs"] = subscription_ids
    if since is not None:
        clauses.append("scene_datetime >= :since")
        params["since"] = since
    stmt = text(
        f"SELECT id::text AS job_id, block_id::text AS block_id, "
        f"       product_id::text AS product_id, scene_datetime "
        f"FROM imagery_ingestion_jobs WHERE {' AND '.join(clauses)} "
        f"ORDER BY scene_datetime DESC LIMIT :limit"
    )
    if subscription_ids:
        stmt = stmt.bindparams(bindparam("subs", expanding=True))
    return [dict(r) for r in conn.execute(stmt, params).mappings().all()]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    subscription_ids = [UUID(s.strip()) for s in args.subscription.split(",") if s.strip()]

    settings = get_settings()
    engine = create_engine(str(settings.database_sync_url), future=True)
    queued: list[dict[str, object]] = []
    try:
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{args.tenant_schema}", public'))
            jobs = _list_jobs(
                conn, subscription_ids=subscription_ids, since=args.since, limit=args.limit
            )
            logger.info("found %d succeeded jobs to re-acquire", len(jobs))

            if args.dry_run:
                for j in jobs:
                    logger.info(
                        "would re-acquire job=%s block=%s @ %s",
                        j["job_id"],
                        j["block_id"],
                        j["scene_datetime"],
                    )
                return 0

            # Per job: delete its aggregate rows + reset to pending, committed
            # BEFORE enqueueing so acquire_scene can't race the reset.
            del_idx = text(
                "DELETE FROM block_index_aggregates "
                "WHERE block_id = CAST(:b AS uuid) AND product_id = CAST(:p AS uuid) AND time = :t"
            )
            del_grid = text(
                "DELETE FROM block_grid_aggregates "
                "WHERE block_id = CAST(:b AS uuid) AND product_id = CAST(:p AS uuid) AND time = :t"
            )
            reset_job = text(
                "UPDATE imagery_ingestion_jobs "
                "SET status = 'pending', completed_at = NULL, "
                "    error_message = NULL, error_code = NULL "
                "WHERE id = CAST(:id AS uuid)"
            )
            for j in jobs:
                with conn.begin():
                    p = {"b": j["block_id"], "p": j["product_id"], "t": j["scene_datetime"]}
                    conn.execute(del_idx, p)
                    conn.execute(del_grid, p)
                    conn.execute(reset_job, {"id": j["job_id"]})
                queued.append(j)
    finally:
        engine.dispose()

    # Enqueue acquire_scene now that the resets are durably committed.
    from app.modules.imagery.tasks import acquire_scene

    for j in queued:
        acquire_scene.delay(j["job_id"], args.tenant_schema)
        logger.info("queued acquire_scene job=%s @ %s", j["job_id"], j["scene_datetime"])
    logger.info("done — re-acquiring %d scenes", len(queued))
    return 0


if __name__ == "__main__":
    sys.exit(main())
