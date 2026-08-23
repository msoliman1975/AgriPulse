"""Celery tasks for the indices module.

Currently one task: a Beat-driven weekly sweep that recomputes
per-(block, index, day-of-year) baselines from the rolling history of
``block_index_aggregates``, then re-derives ``baseline_deviation`` on the
rows already stored. The actual aggregate writes happen inside imagery's
``compute_indices`` task; baselines are derived data that trail behind by
up to a week.

The second step matters because ``compute_indices`` computes the z-score
once, when it writes the row, against the baselines that exist at that
moment. A baseline needs three samples in a rolling window, and the row
being written is one of them, so the first rows of a season are always
written before their own baseline exists. Without this catch-up they keep
NULL for ever and every decision tree reading
``indices.<code>.baseline_deviation`` gets nothing.

We keep the task off the heavy queue because the math is light —
loading a few thousand rows per (block, index) and computing means is
trivially cheap. CPU is not the constraint; what we care about is
not contending with the imagery acquisition flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.logging import get_logger
from app.modules.indices.service import get_indices_service
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Same pattern as imagery/tasks.py: dispose the engine after each
    invocation so a fresh asyncpg pool gets bound to the next task's
    event loop."""

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


async def _set_tenant_context(session: Any, tenant_schema: str) -> None:
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )


# Result KEPT, deliberately against the module's convention: this task is on the
# `platform.run_tasks` allowlist, and the only way an operator or the simulation
# harness can tell a triggered run apart from one that never started is to read
# its return value back through GET /admin/tasks/runs/{id}. With
# `ignore_result=True` Celery stores nothing, so that endpoint reports PENDING
# forever even for a task that succeeded — measured at 0.16 s against 480 s of
# polling. Do not "restore consistency" here without also giving the trigger
# endpoint another way to observe completion.
@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.recompute_baselines_for_tenant",
    bind=False,
)
def recompute_baselines_for_tenant(tenant_schema: str) -> dict[str, int]:
    """Recompute every (block, index) baseline pair in one tenant."""
    return _run_task(_recompute_baselines_for_tenant_async(tenant_schema))


async def _recompute_baselines_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    pairs: tuple[Any, ...] = ()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        svc = get_indices_service(tenant_session=session)
        # Reach through to the repo for the cheap distinct query.
        pairs = await svc._repo.list_distinct_block_index_pairs()  # type: ignore[attr-defined]

    counts = await _recompute_pairs(tenant_schema, pairs)

    _log.info(
        "indices_baselines_recomputed",
        tenant_schema=tenant_schema,
        **counts,
    )
    return counts


# Postgres SQLSTATEs that mean "this transaction lost a race and can be run
# again unchanged": 40001 serialization_failure, 40P01 deadlock_detected.
_RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})

# Attempts per pair, and the wait before each retry. The pair is retried
# `_PAIR_ATTEMPTS - 1` times, so at most 1.5s is added to a pair that keeps
# losing. No jitter: the contending party is a TimescaleDB policy job on a
# fixed schedule, not another copy of this loop, so spreading retries out
# buys nothing.
_PAIR_ATTEMPTS = 3
_RETRY_BASE_SECONDS = 0.5


def _is_retryable_conflict(exc: DBAPIError) -> bool:
    """True for a deadlock or serialization failure.

    Read off SQLSTATE rather than the driver's exception class. asyncpg,
    psycopg and the SQLAlchemy wrapper all name these differently, and the
    production failure arrived wrapped twice — as a
    `sqlalchemy.dialects.postgresql.asyncpg.Error` inside a `DBAPIError`.
    """
    return getattr(exc.orig, "sqlstate", None) in _RETRYABLE_SQLSTATES


async def _recompute_pairs(tenant_schema: str, pairs: tuple[Any, ...]) -> dict[str, int]:
    """Recompute baselines, then re-derive deviations, for each pair.

    One transaction per pair so a long list does not hold a single
    transaction open, and one bad pair cannot lose the counters of the ones
    before it. Shared by the tenant-wide sweep and the farm-scoped task a
    backfill queues.

    That second promise needed the error handling below to be true. Until
    2026-08-23 an exception from any pair escaped and killed the whole run,
    so every pair after it was skipped. Production hit that: this task's
    UPDATE on `block_index_aggregates` deadlocked against the TimescaleDB
    columnstore policy converting the same chunk, and the sweep stopped at
    that pair. The sweep walks 828 pairs in about 420 seconds on the largest
    tenant, and the policy runs every 12 hours, so the two meet regularly.

    A deadlock is retried, because re-running the pair is the documented cure
    and the statement is safe to run more than once. Any other error is
    counted and skipped, so one broken pair costs one pair.
    """
    factory = AsyncSessionLocal()
    written_total = 0
    deviations_total = 0
    pairs_processed = 0
    pairs_failed = 0
    conflict_retries = 0
    for block_id, index_code in pairs:
        for attempt in range(1, _PAIR_ATTEMPTS + 1):
            try:
                async with factory() as session, session.begin():
                    await _set_tenant_context(session, tenant_schema)
                    svc = get_indices_service(tenant_session=session)
                    written = await svc.recompute_block_index_baselines(
                        block_id=block_id, index_code=index_code
                    )
                    # Push the fresh baselines back onto the rows already
                    # stored. `record_aggregate_row` derives the z-score once,
                    # at write time, so a row written before its day-of-year
                    # had enough samples keeps NULL until this runs. Same
                    # catch-up the weather sweep already does for
                    # `weather_index_daily`.
                    deviations = await svc.recompute_block_index_deviations(
                        block_id=block_id, index_code=index_code
                    )
            except DBAPIError as exc:
                if _is_retryable_conflict(exc) and attempt < _PAIR_ATTEMPTS:
                    conflict_retries += 1
                    _log.warning(
                        "indices_baseline_pair_conflict_retry",
                        tenant_schema=tenant_schema,
                        block_id=str(block_id),
                        index_code=index_code,
                        attempt=attempt,
                    )
                    await asyncio.sleep(_RETRY_BASE_SECONDS * attempt)
                    continue
                pairs_failed += 1
                _log.exception(
                    "indices_baseline_pair_failed",
                    tenant_schema=tenant_schema,
                    block_id=str(block_id),
                    index_code=index_code,
                    attempts=attempt,
                )
                break
            except Exception:
                pairs_failed += 1
                _log.exception(
                    "indices_baseline_pair_failed",
                    tenant_schema=tenant_schema,
                    block_id=str(block_id),
                    index_code=index_code,
                    attempts=attempt,
                )
                break
            written_total += written
            deviations_total += deviations
            pairs_processed += 1
            break
    return {
        "pairs_processed": pairs_processed,
        "pairs_failed": pairs_failed,
        "conflict_retries": conflict_retries,
        "baselines_written": written_total,
        "deviations_updated": deviations_total,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.recompute_baselines_for_farm",
    bind=False,
    ignore_result=True,
)
def recompute_baselines_for_farm(farm_id: str, tenant_schema: str) -> dict[str, int]:
    """Recompute one farm's baselines and z-scores.

    Queued by the imagery indices backfill so a run's numbers appear without
    waiting for the hourly tenant sweep. Farm-scoped because a backfill is
    farm-scoped, and because the tenant sweep measured 420s for 828 pairs —
    too long to run repeatedly during a backfill.
    """
    return _run_task(_recompute_baselines_for_farm_async(farm_id, tenant_schema))


async def _recompute_baselines_for_farm_async(farm_id: str, tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    pairs: tuple[Any, ...] = ()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        svc = get_indices_service(tenant_session=session)
        pairs = await svc._repo.list_distinct_block_index_pairs_for_farm(  # type: ignore[attr-defined]
            farm_id=UUID(farm_id)
        )

    counts = await _recompute_pairs(tenant_schema, pairs)

    _log.info(
        "indices_farm_baselines_recomputed",
        tenant_schema=tenant_schema,
        farm_id=farm_id,
        **counts,
    )
    return counts


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.recompute_baselines_sweep",
    bind=False,
    ignore_result=True,
)
def recompute_baselines_sweep() -> dict[str, int]:
    """Beat sweep: walk every active tenant and queue per-tenant recomputes."""
    return _run_task(_recompute_baselines_sweep_async())


async def _recompute_baselines_sweep_async() -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        recompute_baselines_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}


# --- continuous-aggregate refresh -------------------------------------------
#
# `block_index_daily` / `block_index_weekly` are TimescaleDB continuous
# aggregates whose refresh policies use a ROLLING window (3 days and 21 days
# respectively, see tenant migration 0003). That is right for live ingest and
# wrong for backfill: a historical load writes rows far outside those windows,
# so their invalidations are never processed and the buckets are never
# materialized. And because the views are real-time aggregates
# (`materialized_only=false`, migration 0004), buckets OLDER than the
# materialization threshold are served from the materialized store alone --
# so backfilled history is simply invisible to every reader.
#
# This sweep closes that gap. A full refresh of both views measured ~2.5s per
# tenant on production-sized data, which is cheap enough to run unconditionally
# rather than trying to detect which windows went stale.


# Result KEPT — allowlisted for on-demand triggering; see the note on
# `recompute_baselines_for_tenant` above.
@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.refresh_index_caggs_for_tenant",
    bind=False,
)
def refresh_index_caggs_for_tenant(tenant_schema: str) -> dict[str, Any]:
    """Materialize both index continuous aggregates for one tenant."""
    return _run_task(_refresh_index_caggs_for_tenant_async(tenant_schema))


async def _refresh_index_caggs_for_tenant_async(tenant_schema: str) -> dict[str, Any]:
    safe = sanitize_tenant_schema(tenant_schema)
    refreshed: list[str] = []
    factory = AsyncSessionLocal()
    for view in ("block_index_daily", "block_index_weekly"):
        # refresh_continuous_aggregate cannot run inside a transaction block,
        # so each call gets its own autocommit connection.
        async with factory() as session:
            conn = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
            try:
                await conn.execute(
                    text(f"CALL refresh_continuous_aggregate('{safe}.{view}', NULL, NULL)")
                )
                refreshed.append(view)
            except Exception as exc:  # one bad view must not block the other
                _log.warning(
                    "index_cagg_refresh_failed",
                    tenant_schema=safe,
                    view=view,
                    error=str(exc)[:300],
                )
    return {"tenant_schema": safe, "refreshed": refreshed}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.refresh_index_caggs_sweep",
    bind=False,
    ignore_result=True,
)
def refresh_index_caggs_sweep() -> dict[str, int]:
    """Beat sweep: queue a continuous-aggregate refresh per active tenant."""
    return _run_task(_refresh_index_caggs_sweep_async())


async def _refresh_index_caggs_sweep_async() -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        refresh_index_caggs_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
