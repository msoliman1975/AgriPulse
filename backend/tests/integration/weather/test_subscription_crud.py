"""HTTP-level CRUD round-trip for weather subscriptions.

POST → GET → DELETE plus per-farm RBAC denial. The Celery side of the
pipeline is exercised in test_refresh_endpoint.py; this file just
verifies router + service + repository wiring.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_farm_and_block,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_subscription_full_crud_cycle(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-crud-1",
        name="Weather CRUD",
        contact_email="ops@weather-crud.test",
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
        _farm_id, block_id = await create_farm_and_block(client)

        # POST — create subscription
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo", "cadence_hours": 6},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        sub_id = body["id"]
        assert body["block_id"] == block_id
        assert body["provider_code"] == "open_meteo"
        assert body["cadence_hours"] == 6
        assert body["is_active"] is True

        # POST again — uniqueness violation surfaces as 409
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert resp.status_code == 409, resp.text

        # POST with unknown provider_code — 409 (catalog miss)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "does_not_exist"},
        )
        assert resp.status_code == 409, resp.text

        # GET — list
        resp = await client.get(f"/api/v1/blocks/{block_id}/weather/subscriptions")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == sub_id

        # DELETE — soft-revoke
        resp = await client.delete(f"/api/v1/blocks/{block_id}/weather/subscriptions/{sub_id}")
        assert resp.status_code == 204

        # GET after revoke — list excludes inactive by default
        resp = await client.get(f"/api/v1/blocks/{block_id}/weather/subscriptions")
        assert resp.status_code == 200
        assert resp.json() == []

        # GET with include_inactive=true
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/weather/subscriptions?include_inactive=true"
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["is_active"] is False


@pytest.mark.asyncio
async def test_revoke_idempotent(admin_session: AsyncSession) -> None:
    """Revoking an already-revoked subscription is a no-op (returns 204)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-idemp-revoke",
        name="Weather Idempotent Revoke",
        contact_email="ops@weather-idemp.test",
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
            json={"provider_code": "open_meteo"},
        )
        sub_id = resp.json()["id"]

        # First revoke succeeds
        resp = await client.delete(f"/api/v1/blocks/{block_id}/weather/subscriptions/{sub_id}")
        assert resp.status_code == 204

        # Second revoke is idempotent
        resp = await client.delete(f"/api/v1/blocks/{block_id}/weather/subscriptions/{sub_id}")
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_revoke_wrong_block_returns_404(admin_session: AsyncSession) -> None:
    """A subscription_id that doesn't belong to the path's block_id surfaces as 404."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-wrong-block",
        name="Weather Wrong Block",
        contact_email="ops@weather-wrong.test",
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
        _farm_id1, block_id1 = await create_farm_and_block(client, slug="A")
        _farm_id2, block_id2 = await create_farm_and_block(client, slug="B")

        resp = await client.post(
            f"/api/v1/blocks/{block_id1}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        sub_id = resp.json()["id"]

        # Path block doesn't own this subscription
        resp = await client.delete(f"/api/v1/blocks/{block_id2}/weather/subscriptions/{sub_id}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_create_or_refresh(admin_session: AsyncSession) -> None:
    """Viewer reads but cannot manage subscriptions or trigger refresh."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-viewer",
        name="Weather Viewer",
        contact_email="ops@weather-viewer.test",
    )

    admin_user = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=admin_user)
    admin_ctx = make_context(
        user_id=admin_user,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(admin_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await create_farm_and_block(client)

    viewer_user = uuid4()
    await create_user_in_tenant(
        admin_session,
        tenant_id=tenant.tenant_id,
        user_id=viewer_user,
        tenant_role="BillingAdmin",
    )
    viewer_ctx = make_context(
        user_id=viewer_user,
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.VIEWER),),
    )
    app = build_app(viewer_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert resp.status_code == 404, resp.text

        resp = await client.get(f"/api/v1/blocks/{block_id}/weather/subscriptions")
        assert resp.status_code == 200

        resp = await client.post(f"/api/v1/blocks/{block_id}/weather/refresh")
        assert resp.status_code == 404
