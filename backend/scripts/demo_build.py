"""Build a demo farm's history in one run, and report where anyone can read it.

Made for a cluster Job nobody can attach to. Progress, failures and the
final totals are written as audit-archive events on the build tenant, so
`GET /api/v1/admin/tenants/{id}/sidecar` shows them to a platform admin
without log access::

    DEMO_HISTORY_BUILD_SCHEMA_PREFIX=tenant_01a0eec1 \
    python -m scripts.demo_build \
        --tenant-schema tenant_01a0eec13ae9703dbfa8a7cfafe11675 \
        --scenario ewais_grove --mode all \
        --from 2024-09-29 --to 2026-09-28

Modes:

* ``incidents-dry-run``: apply every incident in a transaction, report the
  rows each would move, roll back. Changes nothing.
* ``incidents``: apply the incidents. Already-applied ones are skipped.
* ``replay``: replay the range, in chunks, with the build steps.
* ``all``: ``incidents`` then ``replay``.
* ``reset``: delete the tenant's derived history (engine output, team
  work, hindcasts) and keep its inputs. See `demo_history.reset`.
* ``rebuild``: ``incidents``, ``reset``, then ``replay``. Applied
  incidents are skipped, so a scenario that gained one applies only that.
* ``copy-history-dry-run``: copy the scenario's ``COPY_SOURCE`` history
  onto its farm in a transaction, report the rows, roll back.
* ``copy-history``: copy it. Rows the farm already has are skipped, so a
  second run adds nothing. See `demo_history.copy_history`.
* ``irrigation``: redo the irrigation history over the range: clear its
  schedules, then replay only yesterday's water balance, the day's
  schedule and the operator's evening log. For days replayed while the
  daily weather was missing.

The replay goes in chunks of ``--chunk-days``, and each chunk writes one
progress event. A chunk that fails stops the run and its error is the
last event. A range already replayed must not be replayed again: the
engine would open a second history on top of the first. Restart after a
failure from the day after the last reported chunk.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import importlib
import logging
import sys
import time
import traceback
from collections.abc import Coroutine
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.modules.audit.service import get_audit_service
from app.modules.demo_history import people
from app.modules.demo_history.copy_history import copy_history
from app.modules.demo_history.incidents import apply_scenario
from app.modules.demo_history.reset import clear_irrigation, reset_build_tenant
from app.modules.demo_history.runner import ReplayNotAllowedError, ensure_build_tenant, replay
from app.modules.demo_history.steps import DEMO_BUILD_STEPS, IRRIGATION_STEPS, Step
from app.shared.db.session import AsyncSessionLocal, dispose_engine

logger = logging.getLogger("demo_build")

_MODES = (
    "copy-history-dry-run",
    "copy-history",
    "incidents-dry-run",
    "incidents",
    "replay",
    "all",
    "reset",
    "rebuild",
    "irrigation",
)
_REPLAYS = ("replay", "all", "rebuild", "irrigation")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-schema", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--mode", choices=_MODES, required=True)
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--chunk-days", type=int, default=7)
    args = parser.parse_args(argv)
    if args.mode in _REPLAYS and (args.start is None or args.end is None):
        parser.error("--from and --to are required to replay")
    return args


def _run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


async def _tenant_id(tenant_schema: str) -> UUID:
    async with AsyncSessionLocal()() as session, session.begin():
        found = (
            await session.execute(
                text("SELECT id FROM public.tenants WHERE schema_name = :s"),
                {"s": tenant_schema},
            )
        ).scalar_one_or_none()
    if found is None:
        raise ValueError(f"no tenant with schema {tenant_schema}")
    return UUID(str(found))


class Reporter:
    """Writes one archive event per report, on the build tenant."""

    def __init__(self, tenant_id: UUID, mode: str) -> None:
        self.tenant_id = tenant_id
        self.mode = mode
        self.started = time.monotonic()

    def __call__(self, event: str, **details: Any) -> None:
        payload = {
            "mode": self.mode,
            "elapsed_s": round(time.monotonic() - self.started),
            **details,
        }
        logger.info("%s %s", event, payload)
        _run_async(
            get_audit_service().record_archive(
                event_type=f"demo_build.{event}",
                actor_user_id=None,
                subject_kind="tenant",
                subject_id=self.tenant_id,
                details=payload,
                actor_kind="system",
            )
        )


def _scenario(args: argparse.Namespace) -> Any:
    return importlib.import_module(f"app.modules.demo_history.scenarios.{args.scenario}")


def scenario_steps(scenario: Any, base: tuple[Step, ...] = DEMO_BUILD_STEPS) -> tuple[Step, ...]:
    """The build steps, with the scenario's own team words and dated edits.

    A scenario without a `TEAM_POLICY` keeps the default (mango) wording,
    and one without `ATTRIBUTE_CHANGES` adds no step, so Ewais Grove builds
    exactly as before.
    """
    policy = getattr(scenario, "TEAM_POLICY", None)
    steps: list[Step] = []
    for base_step in base:
        step = base_step
        if policy is not None and step.name == "demo.team_work":
            step = Step(
                step.name,
                step.hour,
                functools.partial(people.act_for_tenant, policy=policy),
                step.weekday,
            )
        elif policy is not None and step.name == "demo.irrigation_work":
            step = Step(
                step.name,
                step.hour,
                functools.partial(people.irrigate_for_tenant, policy=policy),
                step.weekday,
            )
        steps.append(step)
    changes = tuple(getattr(scenario, "ATTRIBUTE_CHANGES", ()))
    if changes:
        steps.append(
            Step(
                "demo.attribute_changes",
                15,
                functools.partial(people.attribute_changes_for_tenant, changes=changes),
            )
        )
    return tuple(steps)


def _copy(args: argparse.Namespace, report: Reporter, *, dry_run: bool) -> None:
    scenario = _scenario(args)
    source = getattr(scenario, "COPY_SOURCE", None)
    if source is None:
        raise ValueError(f"scenario {args.scenario} has no COPY_SOURCE")
    result = _run_async(
        copy_history(
            AsyncSessionLocal(),
            source=source,
            target_schema=args.tenant_schema,
            target_farm_code=scenario.FARM_CODE,
            dry_run=dry_run,
        )
    )
    report("history_copy_dry_run" if dry_run else "history_copied", result=result)


def _incidents(args: argparse.Namespace, report: Reporter, *, dry_run: bool) -> None:
    scenario = _scenario(args)
    results: list[dict[str, Any]] = _run_async(
        apply_scenario(AsyncSessionLocal(), args.tenant_schema, scenario, dry_run=dry_run)
    )
    report("incidents_dry_run" if dry_run else "incidents_applied", results=results)


def _replay(
    args: argparse.Namespace,
    report: Reporter,
    steps: tuple[Step, ...] = DEMO_BUILD_STEPS,
) -> bool:
    """Replay in chunks. Returns False when a chunk failed."""
    chunk = timedelta(days=args.chunk_days)
    day = args.start
    totals: dict[str, dict[str, int]] = {}
    while day <= args.end:
        last = min(day + chunk - timedelta(days=1), args.end)
        result = replay(
            tenant_schema=args.tenant_schema,
            start=day,
            end=last,
            steps=steps,
        )
        for name, counts in result.totals().items():
            bucket = totals.setdefault(name, {})
            for key, value in counts.items():
                bucket[key] = bucket.get(key, 0) + value
        if result.failed_steps:
            failed = result.failed_steps[0]
            report(
                "replay_failed",
                chunk_from=day.isoformat(),
                chunk_to=last.isoformat(),
                step=failed.name,
                at=failed.at.isoformat(),
                error=(failed.error or "")[:1500],
                restart_from=day.isoformat(),
            )
            return False
        report(
            "replay_progress",
            chunk_from=day.isoformat(),
            chunk_to=last.isoformat(),
            chunk_totals=result.totals(),
        )
        day = last + timedelta(days=1)
    report("replay_finished", start=args.start.isoformat(), end=args.end.isoformat(), totals=totals)
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    try:
        ensure_build_tenant(args.tenant_schema)
    except ReplayNotAllowedError as exc:
        logger.error("refused: %s", exc)
        return 2

    report = Reporter(_run_async(_tenant_id(args.tenant_schema)), args.mode)
    report("started", scenario=args.scenario, start=str(args.start), end=str(args.end))
    try:
        if args.mode in ("copy-history-dry-run", "copy-history"):
            _copy(args, report, dry_run=args.mode == "copy-history-dry-run")
        if args.mode == "incidents-dry-run":
            _incidents(args, report, dry_run=True)
        if args.mode in ("incidents", "all", "rebuild"):
            _incidents(args, report, dry_run=False)
        if args.mode in ("reset", "rebuild"):
            cleared = _run_async(reset_build_tenant(AsyncSessionLocal(), args.tenant_schema))
            report("reset", cleared=cleared)
        if args.mode == "irrigation":
            cleared = _run_async(
                clear_irrigation(AsyncSessionLocal(), args.tenant_schema, args.start, args.end)
            )
            report("irrigation_cleared", cleared=cleared)
            irrigation = tuple(
                step
                for step in scenario_steps(_scenario(args))
                if step.name in {s.name for s in IRRIGATION_STEPS}
            )
            if not _replay(args, report, irrigation):
                return 1
        elif args.mode in _REPLAYS and not _replay(args, report, scenario_steps(_scenario(args))):
            return 1
    except Exception as exc:
        report(
            "crashed",
            error=f"{type(exc).__name__}: {exc}"[:500],
            traceback=traceback.format_exc()[-3000:],
        )
        raise
    report("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
