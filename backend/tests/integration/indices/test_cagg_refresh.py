"""Backfilled index history must become visible without hand-run SQL.

`block_index_daily` / `block_index_weekly` are continuous aggregates whose
refresh policies use rolling windows (3 days / 21 days, tenant migration
0003). A historical backfill writes rows far outside those windows, so their
invalidations are never processed. And because the views are real-time
aggregates (migration 0004), buckets OLDER than the materialization threshold
are served from the materialized store alone — so backfilled history reads as
simply absent, even though `block_index_aggregates` holds every row.

That is exactly what happened in production: 47,852 raw rows spanning 2.5
years, and a daily aggregate that covered a single day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.indices import tasks as indices_tasks
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def tenant_with_old_index_rows(admin_session: Any) -> dict[str, Any]:
    """A tenant holding index rows well outside the refresh-policy window."""
    slug = f"cagg-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'CG', 'CG', "
            "ST_GeomFromText('POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,"
            "31.2 30.0))', 4326))"
        ),
        {"id": str(farm_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) VALUES (:id, :fid, "
            "'CB', 'CB', ST_GeomFromText('POLYGON((31.201 30.001,31.205 30.001,"
            "31.205 30.005,31.201 30.005,31.201 30.001))', 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id)},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()

    # 400 days back — far outside the 3-day daily / 21-day weekly policies.
    base = datetime.now(UTC) - timedelta(days=400)
    for i in range(10):
        await admin_session.execute(
            text(
                "INSERT INTO block_index_aggregates "
                "(time, block_id, index_code, product_id, mean, valid_pixel_count, "
                " total_pixel_count, stac_item_id) "
                "VALUES (:t, :b, 'ndvi', :p, :m, 100, 100, :s)"
            ),
            {
                "t": base + timedelta(days=i * 5),
                "b": str(block_id),
                "p": str(product_id),
                "m": 0.4 + i / 100,
                "s": f"test-scene-{i}",
            },
        )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"schema": schema, "block_id": block_id, "since": base - timedelta(days=1)}


async def _daily_rows(session: Any, env: dict[str, Any]) -> int:
    await session.rollback()
    await session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    n = (
        await session.execute(
            text("SELECT count(*) FROM block_index_daily " "WHERE block_id = :b AND day >= :since"),
            {"b": str(env["block_id"]), "since": env["since"]},
        )
    ).scalar_one()
    await session.execute(text("SET search_path TO public"))
    return int(n)


async def _set_materialized_only(session: Any, schema: str, on: bool) -> None:
    """Read the view WITHOUT its real-time part.

    In production these are real-time aggregates, so what broke was the
    materialized store being empty for backfilled buckets while the
    materialization threshold had moved past them — history served from an
    empty store. A fresh test DB has never materialized anything, so its
    real-time part still covers the raw rows and hides the difference.
    Toggling `materialized_only` asserts the thing that actually matters:
    whether the refresh put those buckets into the materialized store.
    """
    await session.rollback()
    conn = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
    await conn.execute(
        text(
            f'ALTER MATERIALIZED VIEW "{schema}".block_index_daily '
            f"SET (timescaledb.materialized_only = {'true' if on else 'false'})"
        )
    )


@pytest.mark.asyncio
async def test_refresh_materializes_backfilled_history(
    admin_session: Any, tenant_with_old_index_rows: dict[str, Any]
) -> None:
    """The regression: the buckets were never materialized, so readers saw nothing."""
    env = tenant_with_old_index_rows
    await _set_materialized_only(admin_session, env["schema"], True)
    try:
        assert (
            await _daily_rows(admin_session, env) == 0
        ), "history outside the rolling refresh window must start unmaterialized"

        await indices_tasks._refresh_index_caggs_for_tenant_async(env["schema"])

        assert (
            await _daily_rows(admin_session, env) == 10
        ), "refresh must materialize every backfilled bucket"
    finally:
        await _set_materialized_only(admin_session, env["schema"], False)


@pytest.mark.asyncio
async def test_refresh_reports_both_views(tenant_with_old_index_rows: dict[str, Any]) -> None:
    result = await indices_tasks._refresh_index_caggs_for_tenant_async(
        tenant_with_old_index_rows["schema"]
    )
    assert result["refreshed"] == ["block_index_daily", "block_index_weekly"], result


@pytest.mark.asyncio
async def test_refresh_rejects_a_suspicious_schema_name() -> None:
    """The view name is interpolated, so the schema must be validated."""
    with pytest.raises(ValueError, match="Invalid tenant schema name"):
        await indices_tasks._refresh_index_caggs_for_tenant_async('public"; DROP TABLE x; --')


@pytest.mark.asyncio
async def test_sweep_enqueues_one_refresh_per_active_tenant(
    tenant_with_old_index_rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[str] = []
    monkeypatch.setattr(
        indices_tasks.refresh_index_caggs_for_tenant,
        "delay",
        lambda schema: queued.append(schema),
    )
    result = await indices_tasks._refresh_index_caggs_sweep_async()
    assert result["enqueued"] == result["tenants_scanned"] > 0
    assert tenant_with_old_index_rows["schema"] in queued
