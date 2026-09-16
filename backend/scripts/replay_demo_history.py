"""Replay one build tenant's past, one simulated day at a time.

Run inside an api or worker pod of the build environment, which is the only
environment where `DEMO_HISTORY_BUILD_SCHEMA_PREFIX` is set::

    python -m scripts.replay_demo_history \
        --tenant-schema tenant_demobuild_ab12 \
        --from 2026-01-01 --to 2026-06-30

The steps run in this process, not on the queue. A Celery worker is a
different process, so the moved clock does not travel with a queued
message and the rows would carry today's date instead.

Every step's counts are printed per day and summed at the end. Read the
summary first. A step whose totals are zero produced nothing for the whole
span, and that is the failure this work is most likely to have.

Never point this at a customer tenant. The runner refuses, but the setting
is the guard that matters: leave it empty everywhere else.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from app.modules.demo_history.runner import ReplayNotAllowedError, replay

logger = logging.getLogger("replay_demo_history")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-schema", required=True)
    parser.add_argument(
        "--from",
        dest="start",
        required=True,
        type=date.fromisoformat,
        help="First simulated day, YYYY-MM-DD, included.",
    )
    parser.add_argument(
        "--to",
        dest="end",
        required=True,
        type=date.fromisoformat,
        help="Last simulated day, YYYY-MM-DD, included and in the past.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Do not stop at the first failing step. Off by default.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print the summary only, not each day.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)

    try:
        report = replay(
            tenant_schema=args.tenant_schema,
            start=args.start,
            end=args.end,
            stop_on_error=not args.keep_going,
        )
    except ReplayNotAllowedError as exc:
        logger.error("refused: %s", exc)
        return 2

    if not args.quiet:
        for day in report.days:
            for step in day.steps:
                outcome = step.error if step.failed else json.dumps(dict(step.counts or {}))
                logger.info("%s  %-28s %s", day.day.isoformat(), step.name, outcome)

    logger.info("")
    logger.info("days replayed: %d of %d", len(report.days), (args.end - args.start).days + 1)
    for name, counts in sorted(report.totals().items()):
        logger.info("  %-28s %s", name, json.dumps(counts))

    failures = report.failed_steps
    if failures:
        logger.error("failed steps: %d", len(failures))
        for step in failures[:10]:
            logger.error("  %s %s %s", step.at.isoformat(), step.name, step.error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
