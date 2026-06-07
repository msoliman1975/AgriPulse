"""Apply (or remove) the TimescaleDB retention policy on every tenant's
``block_grid_aggregates`` hypertable.

This is the **opt-in switch** for per-cell grid-observation retention. The
default platform policy is *compress-only, keep everything* — so this
script is a no-op (it removes any retention policy) unless
``GRID_AGGREGATES_RETENTION_DAYS`` / settings is set to a day count.

Run as::

    # enable ~24-month retention across all tenants
    GRID_AGGREGATES_RETENTION_DAYS=730 python -m scripts.apply_grid_retention

    # show what would happen, no writes
    python -m scripts.apply_grid_retention --dry-run

    # turn retention back off (drop the policy; data already dropped stays
    # dropped — retention is irreversible for chunks past the window)
    python -m scripts.apply_grid_retention   # with the setting unset/None

Compression (``compress_after = 30 days``) is configured in migration
0034 and is independent of this — it keeps the *kept* window cheap whether
or not retention is on.

Idempotent and safe to re-run: ``add_retention_policy(..., if_not_exists
=> true)`` and ``remove_retention_policy(..., if_exists => true)``. See
docs/proposals/grid-aggregates-retention.md for the cost model and the
rationale behind compress-only being the default.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from app.core.settings import get_settings

logger = logging.getLogger("apply_grid_retention")

_TABLE = "block_grid_aggregates"


@dataclass(frozen=True, slots=True)
class TenantRecord:
    slug: str
    schema_name: str


def _list_tenants() -> list[TenantRecord]:
    url = str(get_settings().database_sync_url)
    engine = create_engine(url, future=True)
    try:
        stmt = text(
            """
            SELECT slug, schema_name
              FROM public.tenants
             WHERE deleted_at IS NULL
               AND status <> 'archived'
             ORDER BY created_at
            """
        )
        with engine.begin() as conn:
            rows = conn.execute(stmt).all()
    finally:
        engine.dispose()
    return [TenantRecord(slug=r.slug, schema_name=r.schema_name) for r in rows]


def _apply_one(tenant: TenantRecord, *, retention_days: int | None, dry_run: bool) -> str:
    """Add/remove the retention policy for one tenant. Returns an action word."""
    qualified = f"{tenant.schema_name}.{_TABLE}"
    if retention_days is None:
        action = "remove"
        sql = text("SELECT remove_retention_policy(:tbl, if_exists => true)")
        params = {"tbl": qualified}
    else:
        action = "add"
        # interval literal is built from a validated int, never user text.
        sql = text(
            f"SELECT add_retention_policy(:tbl, INTERVAL '{int(retention_days)} days',"
            " if_not_exists => true)"
        )
        params = {"tbl": qualified}

    if dry_run:
        logger.info("would %s retention on %s (days=%s)", action, qualified, retention_days)
        return action

    url = str(get_settings().database_sync_url)
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            # Skip tenants that don't have the table yet (pre-0034 schemas).
            exists = conn.execute(
                text("SELECT to_regclass(:tbl)"), {"tbl": qualified}
            ).scalar_one_or_none()
            if exists is None:
                logger.info("skip %s — no %s table", tenant.slug, _TABLE)
                return "skip"
            conn.execute(sql, params)
    finally:
        engine.dispose()
    logger.info("%s retention on %s (days=%s)", action, qualified, retention_days)
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List actions without executing.")
    parser.add_argument(
        "--only", help="Apply to just this tenant (by slug)."
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )

    retention_days = get_settings().grid_aggregates_retention_days
    if retention_days is None:
        logger.info(
            "GRID_AGGREGATES_RETENTION_DAYS is unset — compress-only policy; "
            "ensuring no retention policy is present (removing if any)."
        )

    tenants = _list_tenants()
    if args.only:
        tenants = [t for t in tenants if t.slug == args.only]
    if not tenants:
        logger.warning("no matching tenants")
        return 0

    failures = 0
    for tenant in tenants:
        try:
            _apply_one(tenant, retention_days=retention_days, dry_run=args.dry_run)
        except Exception as exc:
            logger.error("failed: %s — %s", tenant.slug, exc)
            failures += 1

    logger.info(
        "done: %d tenants, %d failed (retention_days=%s)",
        len(tenants),
        failures,
        retention_days,
    )
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
