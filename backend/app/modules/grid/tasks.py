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
from typing import Any
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
