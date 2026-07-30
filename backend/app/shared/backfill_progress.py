"""Progress reporting for platform-triggered backfill runs.

Lives in ``app.shared`` rather than in the ``backfill`` module because the
imagery and weather Celery tasks are the ones that report progress, and a
module importing another module's internals is exactly what the
import-linter contracts forbid. Shared may not import ``app.modules`` — so
this file touches ``public.backfill_runs`` through raw SQL and nothing else.

Everything here is best-effort by design. A backfill that succeeds but
fails to write its counter is far better than one that dies because the
bookkeeping table was unreachable, so every function swallows its errors
and logs. Progress is decoration; the data load is the job.

``run_id`` is threaded through the tasks as an optional argument: when it
is ``None`` the task was triggered from the CLI (``scripts.backfill_history``)
rather than the console, and all of this is a no-op.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# Terminal states a run can settle into.
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"


def _sync_engine() -> Any:
    """A short-lived sync engine.

    Celery tasks are sync, and these writes are rare, tiny and outside the
    request path, so a pooled engine buys nothing. ``NullPool`` semantics
    (connect, write, dispose) also keep us clear of the idle-in-transaction
    behaviour seen on the worker side.
    """
    settings = get_settings()
    return create_engine(str(settings.database_sync_url), future=True)


def mark_running(run_id: UUID | str | None) -> None:
    """Flip a queued run to running and stamp ``started_at``.

    Only the first caller sets ``started_at`` — with two sources on one run
    (imagery and weather) both tasks call this, and the run started when the
    first one did.
    """
    if run_id is None:
        return
    _execute(
        """
        UPDATE public.backfill_runs
           SET status = :running,
               started_at = COALESCE(started_at, now())
         WHERE id = :rid
           AND status = 'queued'
        """,
        {"rid": str(run_id), "running": STATUS_RUNNING},
    )


def report(run_id: UUID | str | None, source: str, counters: dict[str, Any]) -> None:
    """Merge ``counters`` into ``progress -> source``.

    Uses a jsonb merge rather than a read-modify-write so the imagery and
    weather tasks can report concurrently without clobbering each other.
    """
    if run_id is None:
        return
    _execute(
        """
        UPDATE public.backfill_runs
           SET progress = jsonb_set(
                 COALESCE(progress, '{}'::jsonb),
                 ARRAY[:source],
                 COALESCE(progress -> :source, '{}'::jsonb) || CAST(:patch AS jsonb),
                 true
               )
         WHERE id = :rid
        """,
        {"rid": str(run_id), "source": source, "patch": json.dumps(counters)},
    )


def finish(
    run_id: UUID | str | None,
    source: str,
    *,
    counters: dict[str, Any] | None = None,
    failed: bool = False,
    error: str | None = None,
) -> None:
    """Record one source as done, then settle the run if nothing is left.

    A run holds one or two sources. It settles only once every declared
    source has reported terminal, and the resulting status is the honest
    summary: ``failed`` when everything failed, ``partial`` when some work
    landed and some did not, ``succeeded`` otherwise.
    """
    if run_id is None:
        return
    if counters:
        report(run_id, source, counters)
    # Both casts here are load-bearing, and this statement silently failed
    # without them (every write in this module swallows its errors, so the
    # only symptom was runs that never left `running`):
    #   * jsonb_build_object's value argument is `"any"`, so the driver's
    #     server-side bind has nothing to infer :state from -> psycopg raises
    #     IndeterminateDatatype "could not determine data type of parameter".
    #   * a postfix `:err::text` does not survive SQLAlchemy text() -> the
    #     colons reach Postgres literally as a syntax error. CAST(... AS ...)
    #     is the function form that works.
    _execute(
        """
        UPDATE public.backfill_runs
           SET progress = jsonb_set(
                 COALESCE(progress, '{}'::jsonb),
                 ARRAY[:source],
                 COALESCE(progress -> :source, '{}'::jsonb)
                   || jsonb_build_object('state', CAST(:state AS text))
                   || CASE WHEN CAST(:err AS text) IS NULL THEN '{}'::jsonb
                           ELSE jsonb_build_object('error', CAST(:err AS text)) END,
                 true
               )
         WHERE id = :rid
        """,
        {
            "rid": str(run_id),
            "source": source,
            "state": "failed" if failed else "done",
            "err": error,
        },
    )
    _settle(run_id)


def fail_run(run_id: UUID | str | None, error: str) -> None:
    """Hard-fail the whole run — used when submission itself blew up."""
    if run_id is None:
        return
    _execute(
        """
        UPDATE public.backfill_runs
           SET status = :failed, error = :err, completed_at = now()
         WHERE id = :rid
           AND status IN ('queued', 'running')
        """,
        {"rid": str(run_id), "failed": STATUS_FAILED, "err": error[:2000]},
    )


def _settle(run_id: UUID | str) -> None:
    """Settle the run iff every declared source has reported terminal.

    The set of declared sources is ``sources`` (written at submit); the set
    of finished ones is every key under ``progress`` carrying a ``state``.
    Comparing the two is what makes a two-source run wait for both.
    """
    _execute(
        """
        WITH declared AS (
            SELECT id,
                   (SELECT count(*) FROM jsonb_each(sources) s
                     WHERE s.value = 'true'::jsonb) AS n_declared,
                   (SELECT count(*) FROM jsonb_each(COALESCE(progress, '{}'::jsonb)) p
                     WHERE p.value ? 'state') AS n_done,
                   (SELECT count(*) FROM jsonb_each(COALESCE(progress, '{}'::jsonb)) p
                     WHERE p.value ->> 'state' = 'failed') AS n_failed
              FROM public.backfill_runs
             WHERE id = :rid
        )
        UPDATE public.backfill_runs r
           SET status = CASE
                          WHEN d.n_failed = 0            THEN 'succeeded'
                          WHEN d.n_failed >= d.n_declared THEN 'failed'
                          ELSE 'partial'
                        END,
               completed_at = now()
          FROM declared d
         WHERE r.id = d.id
           AND d.n_declared > 0
           AND d.n_done >= d.n_declared
           AND r.status IN ('queued', 'running')
        """,
        {"rid": str(run_id)},
    )


def _execute(sql: str, params: dict[str, Any]) -> None:
    try:
        engine = _sync_engine()
        try:
            with engine.begin() as conn:
                conn.execute(text(sql), params)
        finally:
            engine.dispose()
    except Exception:
        logger.warning("backfill progress write failed", exc_info=True, extra=params)
