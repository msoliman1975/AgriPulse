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
from app.modules.grid.anomaly import AnomalyResult
from app.modules.grid.service import get_grid_service
from app.shared.db.blocks import read_block_context
from app.shared.db.ids import uuid7
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)

# V1 hardcodes NDVI, matching the rest of the grid V1 surface (the
# overlay/worst-N default). A future pass can sweep each grid's
# subscribed indices.
_INDEX_CODE = "ndvi"


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


def _build_diagnosis(
    *, index_code: str, result: AnomalyResult
) -> tuple[str, str]:
    """(en, ar) diagnosis text naming the worst flagged cell + counts."""
    worst = result.flagged[0]
    idx = index_code.upper()
    n = len(result.flagged)
    en = (
        f"{n} sub-block cell(s) show {idx} well below the field average "
        f"({result.block_mean:.2f}). Worst: row {worst.row_idx}, col "
        f"{worst.col_idx} at {worst.mean:.2f} "
        f"({worst.z:.1f} SD below). Scout these areas."
    )
    ar = (
        f"تُظهر {n} خلية فرعية قيمة {idx} أقل بكثير من متوسط الحقل "
        f"({result.block_mean:.2f}). الأسوأ: الصف {worst.row_idx}، العمود "
        f"{worst.col_idx} عند {worst.mean:.2f}. يُنصح بمعاينة هذه المناطق."
    )
    return en, ar


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
    diag_en, diag_ar = _build_diagnosis(index_code=index_code, result=result)
    snapshot = _build_snapshot(
        index_code=index_code, scene_time=scene_time, result=result
    )
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

    grids_checked = 0
    alerts_opened = 0
    for cfg in configs:
        block_id = cfg["block_id"]
        product_id = cfg["product_id"]
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            svc = get_grid_service(tenant_session=session)
            verdict = await svc.detect_block_anomalies(
                block_id=block_id, product_id=product_id, index_code=_INDEX_CODE
            )
            grids_checked += 1
            if verdict is None:
                continue
            result, scene_time = verdict
            async with factory() as public_session:
                opened = await _open_anomaly_alert(
                    session=session,
                    public_session=public_session,
                    tenant_schema=tenant_schema,
                    block_id=block_id,
                    index_code=_INDEX_CODE,
                    scene_time=scene_time,
                    result=result,
                )
            if opened:
                alerts_opened += 1

    _log.info(
        "grid_anomaly_tenant_sweep_done",
        tenant_schema=tenant_schema,
        grids_checked=grids_checked,
        alerts_opened=alerts_opened,
    )
    return {"grids_checked": grids_checked, "alerts_opened": alerts_opened}


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
