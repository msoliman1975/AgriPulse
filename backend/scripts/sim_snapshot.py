#!/usr/bin/env python3
"""Extract or apply a simulation snapshot.

Two commands, deliberately separate so the expensive, customer-touching half
runs rarely and the cheap half runs every simulation:

    extract  --source tenant_bashier --out snap.json [--farms 2]
    load     --target tenant_sim_abc --in  snap.json [--as-of 2026-08-13]

``extract`` reads a real tenant and writes a sanitised file: no customer names,
no notes, and every row identifier remapped. ``load`` applies that file to an
empty tenant schema, shifting every timestamp by one offset so the newest
observation lands the day before ``--as-of``.

Run extract once, keep the file (object storage), and load it for every run.
Re-reading a live customer tenant per run is what would make the seed drift
under the harness without anyone noticing.

This is a CLI rather than an endpoint on purpose: it reads one tenant and
writes another wholesale, which is not authority that should exist behind an
HTTP route.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.simulation.snapshot import (
    SnapshotError,
    extract,
    load,
)
from app.shared.db.session import AsyncSessionLocal


async def _extract(args: argparse.Namespace) -> int:
    factory = AsyncSessionLocal()
    async with factory() as session:
        snapshot = await extract(session, source_schema=args.source, farm_limit=args.farms)
        await session.rollback()

    Path(args.out).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    rows = {n: len(p["rows"]) for n, p in snapshot["tables"].items() if p["rows"]}
    print(f"wrote {args.out}")
    print(f"  farms={snapshot['farm_count']} blocks={snapshot['block_count']}")
    print(f"  latest observation: {snapshot['latest_observed_at']}")
    for name, count in sorted(rows.items()):
        print(f"  {name:32} {count:>8}")
    missing = [n for n, p in snapshot["tables"].items() if p.get("missing")]
    if missing:
        print(f"  absent from source: {', '.join(sorted(missing))}")
    return 0


async def _load(args: argparse.Namespace) -> int:
    snapshot: dict[str, Any] = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    as_of = (
        datetime.fromisoformat(args.as_of).replace(tzinfo=UTC) if args.as_of else datetime.now(UTC)
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        report = await load(session, target_schema=args.target, snapshot=snapshot, as_of=as_of)

    print(f"loaded into {report['target_schema']}  (shift {report['offset_days']} days)")
    for name, count in sorted(report["tables"].items()):
        print(f"  {name:32} {count:>8}")
    # Drift is printed loudly rather than buried: a column the snapshot carried
    # and the target no longer has means the seed no longer means what it did.
    if report["dropped_columns"]:
        print("\n  COLUMNS DROPPED (source/target schema drift):")
        for name, columns in sorted(report["dropped_columns"].items()):
            print(f"    {name}: {', '.join(columns)}")
    if report["missing_in_source"]:
        print(f"\n  absent from snapshot: {', '.join(report['missing_in_source'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="read a real tenant into a sanitised file")
    ex.add_argument("--source", required=True, help="source tenant schema")
    ex.add_argument("--out", required=True, help="file to write")
    ex.add_argument(
        "--farms",
        type=int,
        default=2,
        help="how many farms to carry (default 2 — a run needs no more)",
    )
    ex.set_defaults(fn=_extract)

    ld = sub.add_parser("load", help="apply a snapshot to an empty tenant schema")
    ld.add_argument("--target", required=True, help="target tenant schema")
    ld.add_argument("--in", dest="infile", required=True, help="snapshot file")
    ld.add_argument("--as-of", help="ISO date the tenant should look current as of")
    ld.set_defaults(fn=_load)

    args = parser.parse_args()
    try:
        return asyncio.run(args.fn(args))
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
