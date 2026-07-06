"""One-shot historical backfill of raw imagery + weather for a single farm.

Queues Celery tasks that pull ~a year (or any window) of raw Sentinel-2
scenes and raw hourly weather observations for one farm, bypassing the
normal 90-day imagery floor and the 48h weather window. Indices are NOT
computed by default — this lands raw bands / STAC and raw observations
only; reproject later with ``imagery.compute_indices`` (per scene) and
``weather.backfill_weather_indices`` (per farm).

Run inside an api/worker pod (needs the app's broker URL + provider creds
in the environment). The farm defaults to ``agrosina-suez`` and is resolved
to its UUID by name (or code) within the tenant; pass ``--farm-id`` to
target a different farm directly, or ``--farm-name`` to look up another::

    python -m scripts.backfill_history \\
        --tenant-schema tenant_<hex> \\
        --from 2025-07-01 --to 2026-07-01

Idempotent: imagery dedups on (subscription_id, scene_id) and weather on
(time, farm_id, provider_code), so re-running only fills gaps. The imagery
backfill does NOT advance the live discovery watermark.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text

from app.core.settings import get_settings

logger = logging.getLogger("backfill_history")

_DEFAULT_FARM_NAME = "agrosina-suez"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant-schema", required=True, help="tenant_<hex>")
    p.add_argument(
        "--farm-id",
        type=UUID,
        default=None,
        help="Farm UUID. Overrides --farm-name when set.",
    )
    p.add_argument(
        "--farm-name",
        default=_DEFAULT_FARM_NAME,
        help=f"Farm name or code to resolve within the tenant (default: {_DEFAULT_FARM_NAME}).",
    )
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--provider-code", default="open_meteo", help="Weather provider code.")
    p.add_argument("--no-imagery", action="store_true", help="Skip the imagery backfill.")
    p.add_argument("--no-weather", action="store_true", help="Skip the weather backfill.")
    p.add_argument(
        "--with-indices",
        action="store_true",
        help="Also compute imagery indices during backfill (default: raw bands only).",
    )
    return p.parse_args()


def _resolve_farm_id(*, tenant_schema: str, query: str) -> UUID:
    """Look up a single farm UUID by name (or code) within the tenant schema.

    Case-insensitive. Raises SystemExit with a clear message on zero or
    multiple matches so an ambiguous run stops before enqueueing anything.
    """
    settings = get_settings()
    engine = create_engine(str(settings.database_sync_url), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{tenant_schema}", public'))
            rows = (
                conn.execute(
                    text(
                        "SELECT id::text AS id, name, code FROM farms "
                        "WHERE deleted_at IS NULL "
                        "AND (lower(name) = lower(:q) OR lower(code) = lower(:q)) "
                        "ORDER BY name"
                    ).bindparams(bindparam("q")),
                    {"q": query},
                )
                .mappings()
                .all()
            )
    finally:
        engine.dispose()

    if not rows:
        raise SystemExit(f"No farm matching name/code {query!r} in {tenant_schema}")
    if len(rows) > 1:
        listed = ", ".join(f"{r['name']} ({r['id']})" for r in rows)
        raise SystemExit(f"Ambiguous farm {query!r} — matches: {listed}. Pass --farm-id.")
    farm = rows[0]
    logger.info("resolved farm %r -> %s (%s)", query, farm["id"], farm["name"])
    return UUID(farm["id"])


def _day_bounds_iso(day: str, *, end: bool) -> str:
    """A YYYY-MM-DD to an inclusive UTC ISO-8601 datetime boundary."""
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    if end:
        d = d.replace(hour=23, minute=59, second=59)
    return d.isoformat()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    # Bind @shared_task decorators to a broker-configured Celery app BEFORE
    # importing the task modules — otherwise `.delay()` falls through to the
    # implicit default app (amqp://localhost) and the message is never
    # consumed. See workers/celery_factory.build_publisher.
    from workers.celery_factory import build_publisher

    build_publisher()

    from app.modules.imagery.tasks import backfill_farm_scenes
    from app.modules.weather.tasks import backfill_weather

    tenant = args.tenant_schema
    resolved = args.farm_id or _resolve_farm_id(tenant_schema=tenant, query=args.farm_name)
    farm_id = str(resolved)

    if not args.no_weather:
        r = backfill_weather.delay(
            farm_id, tenant, args.provider_code, args.from_date, args.to_date
        )
        logger.info(
            "queued weather.backfill_weather task=%s farm=%s %s..%s provider=%s",
            r.id,
            farm_id,
            args.from_date,
            args.to_date,
            args.provider_code,
        )

    if not args.no_imagery:
        r = backfill_farm_scenes.delay(
            farm_id,
            tenant,
            _day_bounds_iso(args.from_date, end=False),
            _day_bounds_iso(args.to_date, end=True),
            args.with_indices,
        )
        logger.info(
            "queued imagery.backfill_farm_scenes task=%s farm=%s %s..%s with_indices=%s",
            r.id,
            farm_id,
            args.from_date,
            args.to_date,
            args.with_indices,
        )

    logger.info("done — backfill tasks enqueued; watch worker logs for progress")
    return 0


if __name__ == "__main__":
    sys.exit(main())
