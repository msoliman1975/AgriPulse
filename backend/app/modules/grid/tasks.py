"""Celery tasks for sub-block grid spatial-anomaly alerting.

* ``grid.detect_anomalies_for_tenant(schema)`` — walks every active grid
  config in one tenant, runs spatial-anomaly detection on the latest
  scene, and opens a block-level alert that *names the worst cells* when
  a block has patches doing markedly worse than the field average.
* ``grid.detect_anomalies_sweep`` — Beat-driven multi-tenant fan-out.

Why block-level alerts (not one per cell): a block can have dozens of
flagged cells in a single scene; one alert per cell would bury the
inbox. Instead we raise a single alert per (block, index) whose
diagnosis cites the worst offenders and stashes the full flagged set in
``signal_snapshot``. Idempotency reuses the existing alerts partial
UNIQUE on ``(block_id, rule_code)`` with ``rule_code =
grid:<index>_spatial_anomaly`` — re-running while an alert is open is a
no-op, and the alert can re-fire once resolved.

Cadence is set in ``workers/beat/main.py`` against
``grid_anomaly_detect_sweep_seconds``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.grid.anomaly import DEFAULT_K, AnomalyResult, effective_k
from app.modules.grid.backfill import list_backfill_jobs
from app.modules.grid.polar_label import ring_sector
from app.modules.grid.service import get_grid_service
from app.shared.db.blocks import read_block_context
from app.shared.db.ids import uuid7
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)

# Platform-default key for the detection threshold. Resolves
# per-block (grid_configs.anomaly_z_threshold) -> tenant override ->
# platform default. See migration 0026 (public) / 0036 (tenant).
_ANOMALY_K_KEY = "grid.anomaly_z_threshold"


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
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


async def _resolve_tenant_default_k(public_session: Any, tenant_schema: str) -> float:
    """Tenant-tier detection threshold: tenant override -> platform default.

    Per-block overrides (``grid_configs.anomaly_z_threshold``) layer on
    top of this in the sweep loop. Falls back to the module
    :data:`DEFAULT_K` if the tenant or the seed key can't be resolved, so
    a missing setting never wedges the sweep.
    """
    from app.shared.settings.errors import SettingNotFoundError
    from app.shared.settings.resolver import SettingsResolver

    tenant_id = (
        await public_session.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :s"),
            {"s": tenant_schema},
        )
    ).scalar_one_or_none()
    if tenant_id is None:
        return DEFAULT_K
    try:
        resolved = await SettingsResolver(public_session=public_session).get_tenant(
            UUID(str(tenant_id)), _ANOMALY_K_KEY
        )
    except SettingNotFoundError:
        return DEFAULT_K
    try:
        return float(resolved.value)
    except (TypeError, ValueError):
        return DEFAULT_K


def _build_diagnosis(
    *, index_code: str, result: AnomalyResult, worst_label: str | None = None
) -> tuple[str, str]:
    """(en, ar) diagnosis text naming the worst flagged cell + counts.

    ``worst_label`` is the pivot-relative location ("ring 3, NE sector")
    when the unit is a center pivot; for square blocks it's None and we
    fall back to the row/col index.
    """
    worst = result.flagged[0]
    idx = index_code.upper()
    n = len(result.flagged)
    where_en = worst_label or f"row {worst.row_idx}, col {worst.col_idx}"
    where_ar = worst_label or f"الصف {worst.row_idx}، العمود {worst.col_idx}"
    en = (
        f"{n} sub-block cell(s) show {idx} well below the field average "
        f"({result.block_mean:.2f}). Worst: {where_en} at {worst.mean:.2f} "
        f"({worst.z:.1f} SD below). Scout these areas."
    )
    ar = (
        f"تُظهر {n} خلية فرعية قيمة {idx} أقل بكثير من متوسط الحقل "
        f"({result.block_mean:.2f}). الأسوأ: {where_ar} عند "
        f"{worst.mean:.2f}. يُنصح بمعاينة هذه المناطق."
    )
    return en, ar


async def _pivot_worst_label(
    *,
    svc: Any,
    block_id: UUID,
    product_id: UUID,
    result: AnomalyResult,
) -> str | None:
    """ "ring N, <sector> sector" for the worst flagged cell on a pivot.

    Returns None for square (non-pivot) blocks so the diagnosis falls
    back to the row/col index.
    """
    pivot = await svc._repo.get_pivot_geometry(block_id=block_id)
    if pivot is None:
        return None
    cfg = await svc._repo.get_active_config(block_id=block_id, product_id=product_id)
    ring_width = float(cfg["cell_size_m"]) if cfg else 0.0
    worst = result.flagged[0]
    rs = ring_sector(
        centroid_lon=worst.centroid_lon,
        centroid_lat=worst.centroid_lat,
        center_lon=pivot["center_lon"],
        center_lat=pivot["center_lat"],
        ring_width_m=ring_width,
        sector_count=pivot["sector_count"],
    )
    return f"ring {rs.ring}, {rs.sector_label} sector"


def _build_snapshot(
    *, index_code: str, scene_time: datetime, result: AnomalyResult
) -> dict[str, Any]:
    return {
        "source": "grid_spatial_anomaly",
        "index_code": index_code,
        "scene_time": scene_time.isoformat(),
        "block_mean": round(result.block_mean, 4),
        "block_std": round(result.block_std, 4),
        "cells_considered": result.cells_considered,
        "flagged_count": len(result.flagged),
        # Cap the embedded list so a pathological scene can't bloat the row.
        "worst_cells": [
            {
                "cell_id": str(f.cell_id),
                "row_idx": f.row_idx,
                "col_idx": f.col_idx,
                "mean": round(f.mean, 4),
                "z": round(f.z, 2),
            }
            for f in result.flagged[:10]
        ],
    }


async def _open_anomaly_alert(
    *,
    session: Any,
    public_session: Any,
    tenant_schema: str,
    block_id: UUID,
    index_code: str,
    scene_time: datetime,
    result: AnomalyResult,
    worst_label: str | None = None,
) -> bool:
    """Insert a block-level alert + audit + event. Returns True if new.

    Mirrors ``recommendations._open_alert_from_tree`` so cell-anomaly
    alerts flow through the same audit log + notification fan-out
    (``AlertOpenedV1``) as tree-sourced alerts.
    """
    from app.modules.alerts.events import AlertOpenedV1
    from app.modules.alerts.repository import AlertsRepository
    from app.modules.audit import get_audit_service
    from app.shared.eventbus import get_default_bus

    block_ctx = await read_block_context(session, block_id=block_id)
    if block_ctx is None:
        return False
    farm_id = block_ctx["farm_id"]

    rule_code = f"grid:{index_code}_spatial_anomaly"
    diag_en, diag_ar = _build_diagnosis(
        index_code=index_code, result=result, worst_label=worst_label
    )
    snapshot = _build_snapshot(index_code=index_code, scene_time=scene_time, result=result)
    alert_id = uuid7()

    repo = AlertsRepository(tenant_session=session, public_session=public_session)
    inserted = await repo.insert_alert(
        alert_id=alert_id,
        block_id=block_id,
        rule_code=rule_code,
        severity=result.severity,
        diagnosis_en=diag_en,
        diagnosis_ar=diag_ar,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot=snapshot,
        actor_user_id=None,
    )
    if not inserted:
        return False

    await get_audit_service().record(
        tenant_schema=tenant_schema,
        event_type="alerts.alert_opened",
        actor_user_id=None,
        actor_kind="system",
        subject_kind="alert",
        subject_id=alert_id,
        farm_id=farm_id,
        details={
            "block_id": str(block_id),
            "rule_code": rule_code,
            "severity": result.severity,
            "source": "grid_spatial_anomaly",
            "flagged_count": len(result.flagged),
        },
    )
    get_default_bus().publish(
        AlertOpenedV1(
            alert_id=alert_id,
            block_id=block_id,
            rule_code=rule_code,
            severity=result.severity,
            created_at=datetime.now(UTC),
            tenant_schema=tenant_schema,
            farm_id=farm_id,
            diagnosis_en=diag_en,
            diagnosis_ar=diag_ar,
            prescription_en=None,
            prescription_ar=None,
            signal_snapshot=snapshot,
        )
    )
    return True


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.detect_anomalies_for_tenant",
    bind=False,
    ignore_result=True,
)
def detect_anomalies_for_tenant(tenant_schema: str) -> dict[str, int]:
    return _run_task(_detect_for_tenant_async(tenant_schema))


async def _detect_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    configs: tuple[dict[str, Any], ...] = ()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        svc = get_grid_service(tenant_session=session)
        configs = await svc.list_active_configs()

    # Resolve the tenant/platform detection threshold once; per-block
    # overrides layer on top inside the loop.
    async with factory() as public_session:
        tenant_default_k = await _resolve_tenant_default_k(public_session, tenant_schema)

    grids_checked = 0
    indices_checked = 0
    alerts_opened = 0
    for cfg in configs:
        block_id = cfg["block_id"]
        product_id = cfg["product_id"]
        k = effective_k(
            block_override=cfg.get("anomaly_z_threshold"),
            tenant_default=tenant_default_k,
        )

        # G-1: sweep every index the pipeline has written for this grid,
        # not just NDVI. One alert per (block, index) — rule_code carries
        # the index so per-index alerts coexist on the same block.
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            svc = get_grid_service(tenant_session=session)
            index_codes = await svc.list_observed_indices(block_id=block_id, product_id=product_id)
        grids_checked += 1

        for index_code in index_codes:
            async with factory() as session, session.begin():
                await _set_tenant_context(session, tenant_schema)
                svc = get_grid_service(tenant_session=session)
                verdict = await svc.detect_block_anomalies(
                    block_id=block_id,
                    product_id=product_id,
                    index_code=index_code,
                    k=k,
                )
                indices_checked += 1
                if verdict is None:
                    continue
                result, scene_time = verdict
                # For a center pivot, translate the worst cell into the
                # machine's own language ("ring 3, NE sector").
                worst_label = await _pivot_worst_label(
                    svc=svc,
                    block_id=block_id,
                    product_id=product_id,
                    result=result,
                )
                async with factory() as public_session:
                    opened = await _open_anomaly_alert(
                        session=session,
                        public_session=public_session,
                        tenant_schema=tenant_schema,
                        block_id=block_id,
                        index_code=index_code,
                        scene_time=scene_time,
                        result=result,
                        worst_label=worst_label,
                    )
                if opened:
                    alerts_opened += 1

    _log.info(
        "grid_anomaly_tenant_sweep_done",
        tenant_schema=tenant_schema,
        grids_checked=grids_checked,
        indices_checked=indices_checked,
        alerts_opened=alerts_opened,
    )
    return {
        "grids_checked": grids_checked,
        "indices_checked": indices_checked,
        "alerts_opened": alerts_opened,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.detect_anomalies_sweep",
    bind=False,
    ignore_result=True,
)
def detect_anomalies_sweep() -> dict[str, int]:
    return _run_task(_detect_sweep_async())


async def _detect_sweep_async() -> dict[str, int]:
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
        detect_anomalies_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.backfill_block",
    bind=False,
    ignore_result=True,
)
def backfill_block(
    tenant_schema: str,
    block_id: str,
    product_id: str,
    limit: int = 200,
    since_iso: str | None = None,
) -> dict[str, int]:
    """Opt-in backfill of past scenes onto a block's current grid (G-5).

    Walks succeeded ingestion jobs and re-enqueues ``compute_indices`` for
    each, which repopulates ``block_grid_aggregates`` on the freshly
    regenerated cells. Idempotent: scenes already computed on the new grid
    collide on the UNIQUE and DO NOTHING.
    """
    return _run_task(_backfill_block_async(tenant_schema, block_id, product_id, limit, since_iso))


async def _backfill_block_async(
    tenant_schema: str,
    block_id: str,
    product_id: str,
    limit: int,
    since_iso: str | None,
) -> dict[str, int]:
    from app.modules.imagery.tasks import compute_indices

    since = datetime.fromisoformat(since_iso) if since_iso else None
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        jobs = await list_backfill_jobs(
            session,
            block_id=UUID(block_id),
            product_id=UUID(product_id),
            since=since,
            limit=limit,
        )

    for j in jobs:
        compute_indices.delay(j["job_id"], tenant_schema, j["raw_bands_key"])

    _log.info(
        "grid_backfill_queued",
        tenant_schema=tenant_schema,
        block_id=block_id,
        product_id=product_id,
        scenes_queued=len(jobs),
    )
    return {"scenes_queued": len(jobs)}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.cleanup_superseded_grids",
    bind=False,
    ignore_result=True,
)
def cleanup_superseded_grids(
    retention_days: int = 7,
    max_configs_per_tenant: int = 20,
) -> dict[str, int]:
    """Drop the rows belonging to grid configs that govern nothing.

    A config is *superseded* once another geometry has been recomputed
    across its whole range (the second step of a rezone). At that point it
    describes no scene time, but its cells and aggregate rows are still on
    disk. This is the task that reclaims them.

    Deliberately not run inline with a rezone. Deleting from a compressed
    hypertable is slow, and doing it inside the apply request would make an
    operator watch a spinner while history is dismantled — worse, a failure
    mid-delete would leave the request looking like it failed when the
    cutover had already succeeded.

    ``retention_days`` is a deliberate delay, not a performance knob: it
    keeps the previous geometry recoverable for a while after a rezone that
    turns out to have been a mistake. It is the same mechanism the
    aggregate-retention policy (G-8) needs, just on a shorter timer.
    """
    return _run_task(
        _cleanup_superseded_async(
            retention_days=retention_days,
            max_configs_per_tenant=max_configs_per_tenant,
        )
    )


async def _cleanup_superseded_async(
    *, retention_days: int, max_configs_per_tenant: int
) -> dict[str, int]:
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

    configs_dropped = 0
    aggregates_deleted = 0
    tenants_failed = 0

    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        factory = AsyncSessionLocal()
        async with factory() as session:
            # One SAVEPOINT per tenant. Without it a failure on any tenant
            # aborts the surrounding transaction, and every later statement
            # — including the reset — dies with "current transaction is
            # aborted", turning one bad tenant into a total sweep failure.
            try:
                async with session.begin():
                    await _set_tenant_context(session, schema)
                    result = await session.execute(
                        text(
                            """
                            WITH doomed AS (
                                SELECT id FROM grid_configs
                                 WHERE superseded_at IS NOT NULL
                                   AND superseded_at < now()
                                       - make_interval(days => :days)
                                 ORDER BY superseded_at
                                 LIMIT :cap
                            ),
                            cells AS (
                                SELECT id FROM grid_cells
                                 WHERE grid_config_id IN (SELECT id FROM doomed)
                            ),
                            killed_aggs AS (
                                DELETE FROM block_grid_aggregates
                                 WHERE cell_id IN (SELECT id FROM cells)
                                RETURNING 1
                            ),
                            killed_cells AS (
                                DELETE FROM grid_cells
                                 WHERE grid_config_id IN (SELECT id FROM doomed)
                                RETURNING 1
                            ),
                            killed_cfg AS (
                                DELETE FROM grid_configs
                                 WHERE id IN (SELECT id FROM doomed)
                                RETURNING 1
                            )
                            SELECT
                                (SELECT count(*) FROM killed_aggs) AS aggs,
                                (SELECT count(*) FROM killed_cfg)  AS cfgs
                            """
                        ),
                        {"days": retention_days, "cap": max_configs_per_tenant},
                    )
                    counts = result.mappings().one()
                    aggregates_deleted += int(counts["aggs"])
                    configs_dropped += int(counts["cfgs"])
            except Exception:
                tenants_failed += 1
                _log.exception("grid_cleanup_superseded_failed", tenant_schema=schema)

    _log.info(
        "grid_cleanup_superseded",
        tenants_scanned=len(schemas),
        configs_dropped=configs_dropped,
        aggregates_deleted=aggregates_deleted,
        tenants_failed=tenants_failed,
    )
    return {
        "tenants_scanned": len(schemas),
        "configs_dropped": configs_dropped,
        "aggregates_deleted": aggregates_deleted,
        "tenants_failed": tenants_failed,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.backfill_farm",
    bind=False,
    ignore_result=True,
)
def backfill_farm(
    tenant_schema: str,
    farm_id: str,
    budget_scenes: int | None = None,
    since_iso: str | None = None,
) -> dict[str, int]:
    """Regenerate history onto a farm's grids under one shared budget.

    Replaces per-block ``limit=200`` fan-out at farm scale. On a 36-block
    farm that cap means 7,200 unbudgeted jobs, truncating silently per
    block with no farm-wide view of what was skipped.

    **The unit is scene-compute jobs, not provider quota.** Each re-run
    reads the stored ``raw_bands_key`` from R2 and recomputes; it does not
    re-fetch from CDSE. The cost is heavy-worker time and the resulting
    rows, so ``budget_scenes`` is a compute knob, not a spend knob.

    ``budget_scenes=None`` means "everything". Whatever the budget does
    not reach is **reported, not hidden** — those scenes stay readable on
    the older geometry, which is a genuinely two-geometry farm, and the UI
    has to say so.
    """
    return _run_task(
        _backfill_farm_async(
            tenant_schema=tenant_schema,
            farm_id=farm_id,
            budget_scenes=budget_scenes,
            since_iso=since_iso,
        )
    )


async def _backfill_farm_async(
    *,
    tenant_schema: str,
    farm_id: str,
    budget_scenes: int | None,
    since_iso: str | None,
) -> dict[str, int]:
    from app.modules.grid.backfill import allocate_budget, list_farm_grid_pairs
    from app.modules.imagery.tasks import compute_indices

    since = datetime.fromisoformat(since_iso) if since_iso else None
    # Per-pair fetch cap. With a farm budget set we can never enqueue more
    # than the budget in total, so fetching beyond it is pure waste; with
    # no budget we still bound the query rather than reading a decade of
    # jobs into memory.
    per_pair_cap = budget_scenes if budget_scenes is not None else 2000

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        pairs = await list_farm_grid_pairs(session, farm_id=UUID(farm_id))
        jobs_by_pair: dict[tuple[UUID, UUID], list[dict[str, str]]] = {}
        for p in pairs:
            jobs_by_pair[(p["block_id"], p["product_id"])] = await list_backfill_jobs(
                session,
                block_id=p["block_id"],
                product_id=p["product_id"],
                since=since,
                limit=per_pair_cap,
            )

    allocated, stranded = allocate_budget(jobs_by_pair, budget=budget_scenes)

    queued = 0
    for jobs in allocated.values():
        for j in jobs:
            compute_indices.delay(j["job_id"], tenant_schema, j["raw_bands_key"])
            queued += 1

    _log.info(
        "grid_backfill_farm_queued",
        tenant_schema=tenant_schema,
        farm_id=farm_id,
        grids=len(jobs_by_pair),
        scenes_queued=queued,
        scenes_stranded=stranded,
        budget=budget_scenes,
    )
    return {
        "grids": len(jobs_by_pair),
        "scenes_queued": queued,
        "scenes_stranded": stranded,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.settle_rezones",
    bind=False,
    ignore_result=True,
)
def settle_rezones(tenant_schema: str) -> dict[str, int]:
    """Step 2 of a rezone: hand history over to the new geometry.

    The apply itself only opens the new grid at ``now`` and closes the old
    one there, so history stays readable on the geometry that produced it
    while the backfill runs. This task completes the cutover once the
    recomputed rows actually exist.

    Deliberately re-derived from the database rather than triggered by a
    completion callback. A chord over thousands of scene jobs is fragile —
    one lost result and the cutover never finishes — whereas this is
    idempotent and self-correcting: run it as often as you like, and a
    partially-completed backfill simply settles further next time.

    Two outcomes per grid:

    * **Full** — the new geometry now covers everything the old one did.
      The old config is superseded (its rows become cleanup fodder) and
      the new one extends back to ``-infinity``. Net effect is "rewrite
      history": one geometry over the whole record.
    * **Partial** — the budget did not reach everything. ``effective_from``
      walks back only as far as was actually recomputed, and the old
      config keeps governing the rest. The farm genuinely has two
      geometries across its history, and this records that truthfully
      instead of implying a clean rewrite.
    """
    return _run_task(_settle_rezones_async(tenant_schema))


async def _settle_rezones_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        candidates = (
            (
                await session.execute(
                    text(
                        """
                        SELECT new.id AS new_id, old.id AS old_id,
                               new.effective_from AS new_from
                        FROM grid_configs new
                        JOIN grid_configs old
                          ON old.block_id   = new.block_id
                         AND old.product_id = new.product_id
                         AND old.id <> new.id
                         AND old.superseded_at IS NULL
                         AND old.deleted_at IS NULL
                         AND old.effective_to IS NOT NULL
                        WHERE new.retired_at IS NULL
                          AND new.deleted_at IS NULL
                          AND new.superseded_at IS NULL
                          AND new.effective_from > '-infinity'::timestamptz
                        """
                    )
                )
            )
            .mappings()
            .all()
        )

        settled_full = 0
        settled_partial = 0
        for row in candidates:
            min_new = await _min_scene_time(session, row["new_id"])
            if min_new is None:
                continue  # nothing recomputed onto the new geometry yet
            min_old = await _min_scene_time(session, row["old_id"])

            if min_old is None or min_new <= min_old:
                # The new geometry covers everything the old one held.
                # Supersede FIRST: that drops the old row out of the
                # non-overlap constraint's WHERE clause, so the new range
                # can legally expand over it. The reverse order trips the
                # constraint mid-transaction.
                await session.execute(
                    text("UPDATE grid_configs SET superseded_at = now() WHERE id = :id"),
                    {"id": row["old_id"]},
                )
                await session.execute(
                    text(
                        "UPDATE grid_configs "
                        "SET effective_from = '-infinity'::timestamptz "
                        "WHERE id = :id"
                    ),
                    {"id": row["new_id"]},
                )
                settled_full += 1
            elif min_new < row["new_from"]:
                # Partial. Shrink the old range BEFORE growing the new one,
                # for the same constraint reason — shrinking can never
                # create an overlap, growing can.
                await session.execute(
                    text("UPDATE grid_configs SET effective_to = :t WHERE id = :id"),
                    {"id": row["old_id"], "t": min_new},
                )
                await session.execute(
                    text("UPDATE grid_configs SET effective_from = :t WHERE id = :id"),
                    {"id": row["new_id"], "t": min_new},
                )
                settled_partial += 1

    _log.info(
        "grid_rezones_settled",
        tenant_schema=tenant_schema,
        candidates=len(candidates),
        settled_full=settled_full,
        settled_partial=settled_partial,
    )
    return {
        "candidates": len(candidates),
        "settled_full": settled_full,
        "settled_partial": settled_partial,
    }


async def _min_scene_time(session: Any, config_id: Any) -> datetime | None:
    """Oldest observation recorded against a config's own cells."""
    result = await session.execute(
        text(
            """
            SELECT MIN(obs.time)
            FROM grid_cells gc
            JOIN block_grid_aggregates obs ON obs.cell_id = gc.id
            WHERE gc.grid_config_id = :cfg
            """
        ),
        {"cfg": config_id},
    )
    value = result.scalar_one_or_none()
    return value if value is None else cast(datetime, value)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="grid.settle_rezones_sweep",
    bind=False,
    ignore_result=True,
)
def settle_rezones_sweep() -> dict[str, int]:
    """Beat-driven fan-out of :func:`settle_rezones` across tenants.

    Step 2 of a rezone can only run once the backfill has actually
    recomputed history, and nothing knows when that is — so it is polled
    rather than signalled. Without this schedule a rezone would stay in
    its two-geometry state forever, which is safe but never completes.
    """
    return _run_task(_settle_sweep_async())


async def _settle_sweep_async() -> dict[str, int]:
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
        settle_rezones.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
