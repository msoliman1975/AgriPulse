"""GET /api/v1/blocks/{id}/indices/{code}/timeseries.

We seed `block_index_aggregates` directly (skipping the rasterio
pipeline), refresh the daily continuous aggregate to make the rows
visible, and assert the endpoint returns them in ascending bucket
order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.imagery.conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from tests.integration.imagery.test_subscription_crud import (
    _create_farm_and_block,
    _get_s2l2a_product_id,
)

pytestmark = [pytest.mark.integration]


async def _seed_aggregates(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    n_days: int,
    index_code: str = "ndvi",
) -> None:
    """Insert one row per day for ``n_days`` days ending today."""
    today = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    for i in range(n_days):
        scene_dt = today - timedelta(days=i)
        await admin_session.execute(
            text(
                f'INSERT INTO "{tenant_schema}".block_index_aggregates '
                "(time, block_id, index_code, product_id, "
                ' mean, "min", "max", p10, p50, p90, std_dev, '
                " valid_pixel_count, total_pixel_count, "
                " stac_item_id) "
                "VALUES (:time, :block, :code, :prod, "
                "        :mean, :min, :max, :p10, :p50, :p90, :std, "
                "        100, 100, :stac)"
            ).bindparams(
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("prod", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "time": scene_dt,
                "block": block_id,
                "code": index_code,
                "prod": product_id,
                # Vary the mean across days so the chart actually has shape.
                "mean": Decimal(f"0.{50 + i:02d}00"),
                "min": Decimal("0.4000"),
                "max": Decimal("0.7000"),
                "p10": Decimal("0.4500"),
                "p50": Decimal(f"0.{50 + i:02d}00"),
                "p90": Decimal("0.6500"),
                "std": Decimal("0.0500"),
                "stac": f"sentinel_hub/s2_l2a/SCENE_{i:03d}/abc",
            },
        )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_timeseries_daily_returns_seeded_buckets(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="timeseries-daily",
        name="Timeseries Daily",
        contact_email="ops@timeseries.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)

        await _seed_aggregates(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=UUID(product_id),
            n_days=5,
        )

        # Daily granularity — 5 buckets returned.
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/indices/ndvi/timeseries" "?granularity=daily"
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["block_id"] == block_id
    assert body["index_code"] == "ndvi"
    assert body["granularity"] == "daily"
    points = body["points"]
    # With materialized_only=false, the live hypertable rows merge in
    # immediately — five days, five buckets.
    assert len(points) == 5
    means = [float(p["mean"]) for p in points]
    # Buckets are in ascending bucket-date order. Seeded data: i=0 is
    # most-recent day with mean 0.50, i=4 is oldest with mean 0.54.
    # Oldest day appears first → means descend across the response.
    assert means == sorted(means, reverse=True)


@pytest.mark.asyncio
async def test_timeseries_filters_by_window(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="timeseries-window",
        name="Timeseries Window",
        contact_email="ops@window.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        await _seed_aggregates(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=UUID(product_id),
            n_days=10,
        )

        # Pull a 3-day window ending 2026-05-01.
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/indices/ndvi/timeseries"
            "?granularity=daily&from=2026-04-29T00:00:00Z&to=2026-05-01T23:59:59Z"
        )
    assert resp.status_code == 200, resp.text
    points = resp.json()["points"]
    assert len(points) == 3


@pytest.mark.asyncio
async def test_timeseries_unknown_index_returns_empty(
    admin_session: AsyncSession,
) -> None:
    """No row for an unknown index code → empty points, not 404."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="timeseries-empty",
        name="Timeseries Empty",
        contact_email="ops@empty.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _farm_id, block_id = await _create_farm_and_block(client)
        resp = await client.get(f"/api/v1/blocks/{block_id}/indices/ndvi/timeseries")
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"] == []
