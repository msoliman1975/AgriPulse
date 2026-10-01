"""Clear a build tenant's history so the replay can run again from scratch.

A replay that stops part way, or that ran against rows written by a live
sweep, cannot simply be resumed: the engine would open a second history
on top of the first. This deletes what the engine, the farm team step
and the forecast hindcast wrote, and keeps every input the replay reads:
imagery, index rows with their incidents applied, weather observations,
farms, blocks, crops, grids, settings and parameter overrides.

It runs only on a build tenant, behind the same guard as the replay.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.modules.demo_history.runner import ensure_build_tenant
from app.shared.db.session import sanitize_tenant_schema

# Order matters only for readability; every DELETE is in one transaction.
# Outputs of `recommendations.evaluate`, the team step and their trails.
_CLEARED: tuple[tuple[str, str], ...] = (
    ("decision_tree_eval_traces", "TRUE"),
    ("decision_tree_eval_runs", "TRUE"),
    ("decision_tree_block_verdicts", "TRUE"),
    ("recommendations_history", "TRUE"),
    ("recommendations", "TRUE"),
    ("alerts", "TRUE"),
    ("plan_activities", "TRUE"),
    ("in_app_inbox", "TRUE"),
    ("notification_dispatches", "TRUE"),
    ("growth_stage_logs", "TRUE"),
    ("irrigation_schedules", "TRUE"),
    # Hindcast issuances only. A real forecast was issued after the
    # tenant existed; a hindcast is dated in the replayed past.
    ("weather_forecasts", "forecast_issued_at < :created"),
    # Audit rows the replay wrote carry simulated, past times. The rows
    # written while the tenant was set up, and the incident markers that
    # keep incidents from applying twice, are newer and stay.
    ("audit_events", "time < :created AND event_type <> 'demo_history.incident_applied'"),
)


async def reset_build_tenant(session_factory: Any, tenant_schema: str) -> dict[str, int]:
    """Delete the build tenant's derived history. Returns rows per table."""
    ensure_build_tenant(tenant_schema)
    safe = sanitize_tenant_schema(tenant_schema)
    counts: dict[str, int] = {}
    async with session_factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        created: datetime = (
            await session.execute(
                text("SELECT created_at FROM public.tenants WHERE schema_name = :s"),
                {"s": tenant_schema},
            )
        ).scalar_one()
        for table, where in _CLEARED:
            result = await session.execute(
                # Schema-qualified: with `public` on the search path, an
                # unqualified name that is not a tenant table would delete
                # from every tenant at once.
                text(f"DELETE FROM {safe}.{table} WHERE {where}"),  # noqa: S608 - constants
                {"created": created},
            )
            counts[table] = int(getattr(result, "rowcount", 0) or 0)
        # The stage is recomputed each simulated morning, starting from none.
        result = await session.execute(
            text(
                f"UPDATE {safe}.block_crops SET growth_stage = NULL "  # noqa: S608 - constant
                "WHERE growth_stage IS NOT NULL"
            )
        )
        counts["block_crops_stage_cleared"] = int(getattr(result, "rowcount", 0) or 0)
    return counts
