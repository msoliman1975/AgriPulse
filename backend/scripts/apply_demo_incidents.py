"""Apply a scripted incident set to a build tenant's demo farm.

Run once, after the backfill and before the replay, inside an api or
worker pod::

    DEMO_HISTORY_BUILD_SCHEMA_PREFIX=tenant_01a0eec1 \
    python -m scripts.apply_demo_incidents \
        --tenant-schema tenant_01a0eec13ae9703dbfa8a7cfafe11675 \
        --scenario ewais_grove

Each incident commits on its own, with its audit row. An incident that
already has an audit row is skipped, so running the script again after a
failure applies only what is left. `--dry-run` rolls every change back
and prints the row counts it would have moved.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys
from typing import Any

from app.modules.demo_history.incidents import apply_scenario
from app.modules.demo_history.runner import ReplayNotAllowedError, ensure_build_tenant
from app.shared.db.session import AsyncSessionLocal, dispose_engine

logger = logging.getLogger("apply_demo_incidents")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-schema", required=True)
    parser.add_argument(
        "--scenario",
        required=True,
        help="Module name under app.modules.demo_history.scenarios.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


async def _run(tenant_schema: str, scenario: Any, dry_run: bool) -> int:
    try:
        results = await apply_scenario(
            AsyncSessionLocal(), tenant_schema, scenario, dry_run=dry_run
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    verb = "would move" if dry_run else "moved"
    for r in results:
        if r["skipped"]:
            logger.info("%-28s already applied, skipped", r["code"])
        else:
            logger.info(
                "%-28s %s %d cell rows, %d block rows",
                r["code"],
                verb,
                r["cell_rows"],
                r["block_rows"],
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    try:
        ensure_build_tenant(args.tenant_schema)
    except ReplayNotAllowedError as exc:
        logger.error("refused: %s", exc)
        return 2
    scenario = importlib.import_module(f"app.modules.demo_history.scenarios.{args.scenario}")

    async def _main() -> int:
        try:
            return await _run(args.tenant_schema, scenario, args.dry_run)
        finally:
            await dispose_engine()

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
