"""Beat sweep: `weather.discover_due_subscriptions` walks every active
tenant, finds (farm_id, provider_code) pairs whose oldest active
subscription is overdue, and enqueues `fetch_weather` once per pair.

The dedup contract (per Slice-4 locked decision: per-farm internally,
per-block externally) is the load-bearing assertion here — many
per-block subs on the same farm collapse to one fetch per cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.modules.weather import tasks as weather_tasks
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_farm_and_block,
    create_user_in_tenant,
    make_context,
    square_polygon,
)

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_due_sweep_dedupes_per_farm(admin_session: AsyncSession) -> None:
    """Two blocks on the same farm + one subscription each → one fetch enqueued."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-sweep-dedup",
        name="Weather Sweep Dedup",
        contact_email="ops@weather-sweep-dedup.test",
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
        farm_id, block_a = await create_farm_and_block(client, slug="A")

        # Add a second block on the SAME farm.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B-WX-A2",
                "boundary": square_polygon(31.22, 30.02),
            },
        )
        assert resp.status_code == 201, resp.text
        block_b = resp.json()["id"]

        for blk in (block_a, block_b):
            resp = await client.post(
                f"/api/v1/blocks/{blk}/weather/subscriptions",
                json={"provider_code": "open_meteo"},
            )
            assert resp.status_code == 201, resp.text

    # Both subs are brand-new (last_attempted_at = NULL) → both due. Dedup
    # collapses to ONE (farm_id, provider_code) pair.
    captured: list[tuple[Any, ...]] = []
    original_delay = weather_tasks.fetch_weather.delay

    def _capture(*args: object, **kwargs: object) -> None:
        captured.append(tuple(args))

    weather_tasks.fetch_weather.delay = _capture  # type: ignore[method-assign]
    try:
        result = await weather_tasks._discover_due_subscriptions_async()
    finally:
        weather_tasks.fetch_weather.delay = original_delay  # type: ignore[method-assign]

    # The sweep walks every active tenant, so other tests' tenants may
    # also have due rows. Filter to ours.
    ours = [c for c in captured if c[1] == tenant.schema_name]
    assert len(ours) == 1, f"expected 1 dedup'd enqueue, got {len(ours)}: {ours}"
    assert ours[0][2] == "open_meteo"
    assert result["enqueued"] >= 1


@pytest.mark.asyncio
async def test_due_sweep_skips_recently_attempted(admin_session: AsyncSession) -> None:
    """A subscription whose last_attempted_at is within cadence is not re-enqueued."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-sweep-skip",
        name="Weather Sweep Skip",
        contact_email="ops@weather-sweep-skip.test",
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
        _farm_id, block_id = await create_farm_and_block(client)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            # Long cadence so a recent attempt is definitely "not due"
            json={"provider_code": "open_meteo", "cadence_hours": 24},
        )
        sub_id = resp.json()["id"]

    # Mark the subscription as just-attempted.
    await admin_session.execute(
        text(
            f'UPDATE "{tenant.schema_name}".weather_subscriptions '
            "SET last_attempted_at = :now WHERE id = :id"
        ),
        {"now": datetime.now(UTC) - timedelta(minutes=5), "id": sub_id},
    )
    await admin_session.commit()

    captured: list[tuple[Any, ...]] = []
    original_delay = weather_tasks.fetch_weather.delay

    def _capture(*args: object, **kwargs: object) -> None:
        captured.append(tuple(args))

    weather_tasks.fetch_weather.delay = _capture  # type: ignore[method-assign]
    try:
        await weather_tasks._discover_due_subscriptions_async()
    finally:
        weather_tasks.fetch_weather.delay = original_delay  # type: ignore[method-assign]

    ours = [c for c in captured if c[1] == tenant.schema_name]
    assert ours == [], f"recently-attempted subs should not be due: {ours}"
