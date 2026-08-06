"""Celery task behind a named verification run.

One task per run, walking its scenes serially. Serial on purpose: a
verification is pure extra load on the same object storage the live pipeline
reads from, and it is never urgent — an operator who asked "is this year's
data right?" is not waiting on a stopwatch. Fanning out per scene would let a
diagnostic starve the thing it is diagnosing.

Runs on the heavy queue because `full` mode reads every band of every scene.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.observer.service import get_observer_service
from app.modules.observer.verify_store import VerifyStore
from app.shared.db.session import AsyncSessionLocal, dispose_engine, sanitize_tenant_schema

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Same pattern as the imagery tasks: dispose the engine per invocation so
    the next task binds a fresh asyncpg pool to its own event loop."""

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="observer.run_verification",
    bind=False,
    ignore_result=True,
    queue="heavy",
)
def run_verification(run_id: str, tenant_schema: str) -> dict[str, Any]:
    return _run_task(_run_verification_async(UUID(run_id), tenant_schema))


async def _run_verification_async(run_id: UUID, tenant_schema: str) -> dict[str, Any]:
    safe = sanitize_tenant_schema(tenant_schema)
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{safe}", public'))
        store = VerifyStore(session)
        run = await store.get_run(run_id)
        if run is None:
            return {"run_id": str(run_id), "status": "missing"}
        if run["status"] != "queued":
            # A retry after the task already started. Re-running would double
            # every counter, so stop rather than redo.
            return {"run_id": str(run_id), "status": run["status"], "noop": True}
        job_ids = await _scene_job_ids(session, run)
        await store.mark_running(run_id, total=len(job_ids))

    done = 0
    failed = 0
    try:
        for job_id in job_ids:
            # Checked between scenes rather than only at the start, so a
            # cancel takes effect on a long run without killing the worker.
            async with factory() as session, session.begin():
                await session.execute(text(f'SET LOCAL search_path TO "{safe}", public'))
                if await VerifyStore(session).is_cancelled(run_id):
                    _log.info("observer_verify_cancelled", run_id=str(run_id), done=done)
                    return {"run_id": str(run_id), "status": "cancelled", "done": done}

            verdict = await _verify_one(
                tenant_schema=safe, run_id=run_id, job_id=job_id, mode=run["mode"]
            )
            if verdict == "error":
                failed += 1
            done += 1

            async with factory() as session, session.begin():
                await session.execute(text(f'SET LOCAL search_path TO "{safe}", public'))
                await VerifyStore(session).bump_progress(run_id, verdict=verdict)
    except Exception as exc:
        async with factory() as session, session.begin():
            await session.execute(text(f'SET LOCAL search_path TO "{safe}", public'))
            await VerifyStore(session).finish_run(run_id, status="failed", error=str(exc)[:1000])
        _log.warning("observer_verify_run_failed", run_id=str(run_id), error=str(exc)[:300])
        return {"run_id": str(run_id), "status": "failed", "done": done}

    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{safe}", public'))
        # A run whose scenes all errored is not a successful run, even though
        # the loop completed. Reporting `succeeded` there would hide the fact
        # that nothing was actually checked.
        status = "failed" if job_ids and failed == len(job_ids) else "succeeded"
        await VerifyStore(session).finish_run(
            run_id,
            status=status,
            error="every scene failed to verify" if status == "failed" else None,
        )
    return {"run_id": str(run_id), "status": status, "done": done}


async def _verify_one(*, tenant_schema: str, run_id: UUID, job_id: UUID, mode: str) -> str:
    """Verify one scene, converting any failure into an `error` verdict.

    A scene that cannot be read must not abort the run: an operator verifying
    a year wants the other 2,499 answers, and "this one could not be checked"
    is itself a finding worth recording.
    """
    factory = AsyncSessionLocal()
    try:
        # `session.begin()` is required, not decorative: the service uses
        # `SET LOCAL search_path`, which needs a transaction, and the
        # verification row would otherwise never commit. In the API path the
        # session dependency owns this; here the task does.
        async with factory() as session, session.begin():
            service = get_observer_service(session)
            row = await service.verify_scene(
                tenant_schema=tenant_schema,
                job_id=job_id,
                mode=mode,  # type: ignore[arg-type]
                run_id=run_id,
            )
        return str(row["verdict"])
    except Exception as exc:
        _log.info(
            "observer_verify_scene_failed",
            run_id=str(run_id),
            job_id=str(job_id),
            error=str(exc)[:300],
        )
        async with factory() as session, session.begin():
            await session.execute(
                text(f'SET LOCAL search_path TO "{sanitize_tenant_schema(tenant_schema)}", public')
            )
            await _record_error_verification(
                session, run_id=run_id, job_id=job_id, mode=mode, exc=exc
            )
        return "error"


async def _record_error_verification(
    session: Any, *, run_id: UUID, job_id: UUID, mode: str, exc: Exception
) -> None:
    """Persist an `error` verdict so the run's report accounts for the scene.

    Without this the counters and the result rows disagree, and a run showing
    "2,486 of 2,500 checked" gives no way to find the missing fourteen.
    """
    row = (
        await session.execute(
            text(
                "SELECT block_id, product_id, scene_datetime, scene_id "
                "FROM imagery_ingestion_jobs WHERE id = :jid"
            ),
            {"jid": str(job_id)},
        )
    ).mappings()
    job = row.first()
    if job is None:
        return
    await VerifyStore(session).insert_verification(
        run_id=run_id,
        job_id=job_id,
        block_id=job["block_id"],
        product_id=job["product_id"],
        scene_time=job["scene_datetime"],
        scene_id=job["scene_id"],
        mode=mode,
        verdict="error",
        per_index={},
        calc_version_stored=None,
        error=str(exc)[:1000],
        duration_ms=None,
    )


async def _scene_job_ids(session: Any, run: dict[str, Any]) -> list[UUID]:
    """Succeeded scenes in the run's scope, oldest first.

    Only `succeeded` jobs: a scene that never produced a raster has nothing
    to verify against, and counting it would report a run as mostly-errored
    when nothing was wrong.

    The time bounds are interpolated for the same reason every other Observer
    query interpolates them — a bound parameter gets no chunk exclusion.
    """
    clauses = ["j.status = 'succeeded'", "j.stac_item_id IS NOT NULL"]
    params: dict[str, Any] = {"fid": str(run["farm_id"])}
    if run["block_ids"]:
        clauses.append("j.block_id = ANY(CAST(:bids AS uuid[]))")
        params["bids"] = [str(b) for b in run["block_ids"]]
    if run["product_id"]:
        clauses.append("j.product_id = :pid")
        params["pid"] = str(run["product_id"])

    window = (
        f"AND j.scene_datetime >= TIMESTAMPTZ '{run['window_from'].isoformat()}' "
        f"AND j.scene_datetime < TIMESTAMPTZ '{run['window_to'].isoformat()}'"
    )
    sql = f"""
        SELECT j.id
          FROM imagery_ingestion_jobs j
          JOIN blocks b ON b.id = j.block_id
         WHERE b.farm_id = :fid
           AND b.deleted_at IS NULL
           AND {" AND ".join(clauses)}
           {window}
         ORDER BY j.scene_datetime
    """  # noqa: S608 - clauses are a closed set; bounds are datetimes we format
    rows = (await session.execute(text(sql), params)).all()
    return [r[0] for r in rows]
