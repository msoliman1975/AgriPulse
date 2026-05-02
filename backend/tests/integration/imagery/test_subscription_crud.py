"""HTTP-level CRUD round-trip for imagery subscriptions.

POST → GET → DELETE plus per-farm RBAC denial. The Celery side of the
pipeline is exercised in test_ingestion_pipeline.py; this file just
verifies the router + service + repository wiring.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


def _square_polygon(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    """A small square polygon for block boundaries."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


def _multipoly(lon: float, lat: float, side: float = 0.01) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [lon, lat],
                    [lon + side, lat],
                    [lon + side, lat + side],
                    [lon, lat + side],
                    [lon, lat],
                ]
            ]
        ],
    }


async def _create_farm_and_block(
    client: AsyncClient,
) -> tuple[str, str]:
    """Create a farm + block via the farms router, return (farm_id, block_id)."""
    resp = await client.post(
        "/api/v1/farms",
        json={
            "code": "FARM-IM-1",
            "name": "Imagery Test Farm",
            "boundary": _multipoly(31.2, 30.0),
            "farm_type": "commercial",
            "tags": [],
        },
    )
    assert resp.status_code == 201, resp.text
    farm_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={
            "code": "B-IM-1",
            "boundary": _square_polygon(31.21, 30.01),
        },
    )
    assert resp.status_code == 201, resp.text
    block_id = resp.json()["id"]
    return farm_id, block_id


async def _get_s2l2a_product_id(session: AsyncSession) -> str:
    pid = (
        await session.execute(text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'"))
    ).scalar_one()
    return str(pid)


@pytest.mark.asyncio
async def test_subscription_full_crud_cycle(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-crud-1",
        name="Imagery CRUD",
        contact_email="ops@imagery-crud.test",
    )

    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)

        # POST — create subscription
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id, "cadence_hours": 24},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        sub_id = body["id"]
        assert body["block_id"] == block_id
        assert body["product_id"] == product_id
        assert body["cadence_hours"] == 24
        assert body["is_active"] is True

        # POST again — uniqueness violation surfaces as 409
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        assert resp.status_code == 409, resp.text

        # GET — list
        resp = await client.get(f"/api/v1/blocks/{block_id}/imagery/subscriptions")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == sub_id

        # DELETE — soft-revoke
        resp = await client.delete(f"/api/v1/blocks/{block_id}/imagery/subscriptions/{sub_id}")
        assert resp.status_code == 204

        # GET after revoke — list excludes inactive by default
        resp = await client.get(f"/api/v1/blocks/{block_id}/imagery/subscriptions")
        assert resp.status_code == 200
        assert resp.json() == []

        # GET with include_inactive=true
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions" "?include_inactive=true"
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["is_active"] is False


@pytest.mark.asyncio
async def test_viewer_cannot_create_subscription(admin_session: AsyncSession) -> None:
    """Per the gate criteria: Viewer can read but not manage subscriptions."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-viewer",
        name="Imagery Viewer",
        contact_email="ops@viewer.test",
    )

    # First, set up a farm + block as TenantAdmin.
    admin_user = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=admin_user)
    admin_ctx = make_context(
        user_id=admin_user,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(admin_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)

    # Now switch to a Viewer scoped to that farm.
    viewer_user = uuid4()
    await create_user_in_tenant(
        admin_session,
        tenant_id=tenant.tenant_id,
        user_id=viewer_user,
        # Tenant-role None — only farm-scope grant counts.
        tenant_role="BillingAdmin",  # tenant-scope role we don't grant via
    )
    viewer_ctx = make_context(
        user_id=viewer_user,
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=__import__("uuid").UUID(farm_id), role=FarmRole.VIEWER),),
    )
    app = build_app(viewer_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # POST — denied; surfaces as 404 to avoid leaking block existence
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        assert resp.status_code == 404, resp.text

        # GET — allowed; capability is `imagery.read`
        resp = await client.get(f"/api/v1/blocks/{block_id}/imagery/subscriptions")
        assert resp.status_code == 200

        # POST refresh — denied (Viewer lacks imagery.refresh)
        resp = await client.post(f"/api/v1/blocks/{block_id}/imagery/refresh")
        assert resp.status_code == 404


# Suppress unused-import warning when bindparam appears only via .conftest.
_ = (bindparam, PG_UUID)
