"""End-to-end tests for the PR-R2 weather-risk read endpoints.

  GET /api/v1/farms/{farm_id}/blocks/{block_id}/weather-risk/{code}/timeseries
  GET /api/v1/farms/{farm_id}/weather-risk/summary

Both farm-scoped and gated on `weather_risk.read`. Rows are seeded directly
into `weather_risk_daily` so the test doesn't depend on the compute task.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_farm_and_block,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


async def _seed_risk(
    admin_session: AsyncSession,
    schema: str,
    block_id: UUID,
    *,
    risk_code: str,
    days: list[tuple[int, int, str]],
) -> None:
    """Seed ``(offset_back, score, level)`` rows for one block + risk_code."""
    today = datetime.now(UTC).date()
    for offset_back, score, level in days:
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".weather_risk_daily '
                f"(block_id, date, risk_code, score, level, inputs) "
                f"VALUES (:bid, :d, :code, :score, :level, '{{}}'::jsonb)"
            ),
            {
                "bid": block_id,
                "d": today - timedelta(days=offset_back),
                "code": risk_code,
                "score": score,
                "level": level,
            },
        )
    await admin_session.commit()


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, str, str, Any]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"WR api {slug}", contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await create_farm_and_block(client)
    return tenant, farm_id, block_id, app


@pytest.mark.asyncio
async def test_timeseries_returns_block_risk_series(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id, app = await _bootstrap(admin_session, "wr-api-ts")
    await _seed_risk(
        admin_session,
        tenant.schema_name,
        UUID(block_id),
        risk_code="powdery_mildew",
        days=[(2, 30, "low"), (1, 55, "moderate"), (0, 80, "high")],
    )

    url = f"/api/v1/farms/{farm_id}/blocks/{block_id}/weather-risk/powdery_mildew/timeseries"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(url)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["farm_id"] == farm_id
    assert body["block_id"] == block_id
    assert body["risk_code"] == "powdery_mildew"
    points = body["points"]
    assert [p["date"] for p in points] == sorted(p["date"] for p in points)
    assert [p["score"] for p in points] == [30, 55, 80]
    assert points[-1]["level"] == "high"


@pytest.mark.asyncio
async def test_summary_latest_per_block_per_pathogen(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id, app = await _bootstrap(admin_session, "wr-api-summary")
    await _seed_risk(
        admin_session,
        tenant.schema_name,
        UUID(block_id),
        risk_code="powdery_mildew",
        days=[(1, 40, "moderate"), (0, 82, "high")],
    )
    await _seed_risk(
        admin_session,
        tenant.schema_name,
        UUID(block_id),
        risk_code="fruit_fly",
        days=[(0, 12, "low")],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-risk/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["farm_id"] == farm_id
    by_code = {r["risk_code"]: r for r in body["risks"]}
    # Only the latest row per pathogen.
    assert by_code["powdery_mildew"]["score"] == 82
    assert by_code["powdery_mildew"]["level"] == "high"
    assert by_code["fruit_fly"]["score"] == 12
    assert all(r["block_id"] == block_id for r in body["risks"])


@pytest.mark.asyncio
async def test_timeseries_isolated_across_farms(admin_session: AsyncSession) -> None:
    """A block's risk is not readable under another farm's id (join scope)."""
    tenant, farm_id, block_id, app = await _bootstrap(admin_session, "wr-api-iso")
    await _seed_risk(
        admin_session,
        tenant.schema_name,
        UUID(block_id),
        risk_code="anthracnose",
        days=[(0, 70, "high")],
    )
    # A second farm in the same tenant — querying block_id under farm2 is empty.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm2_id, _ = await create_farm_and_block(client, slug="2")
        resp = await client.get(
            f"/api/v1/farms/{farm2_id}/blocks/{block_id}/weather-risk/anthracnose/timeseries"
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["points"] == []


@pytest.mark.asyncio
async def test_weather_risk_endpoints_require_capability(admin_session: AsyncSession) -> None:
    """A user with no weather_risk.read on the farm is denied."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="wr-api-rbac", name="WR api rbac", contact_email="ops@rbac.test"
    )
    admin_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=admin_id)
    admin_ctx = make_context(
        user_id=admin_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app_admin = build_app(admin_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=app_admin), base_url="http://test"
    ) as client:
        farm_id, _ = await create_farm_and_block(client)

    nobody = make_context(
        user_id=uuid4(),
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(),
    )
    app_nobody = build_app(nobody)
    async with AsyncClient(
        transport=ASGITransport(app=app_nobody), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-risk/summary")
    assert resp.status_code in (403, 404), resp.text
