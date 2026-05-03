"""HTTP-level tests for GET /blocks/{id}/scenes and GET /api/v1/config."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from app.shared.db.ids import uuid7

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_subscription_crud import (
    _create_farm_and_block,
    _get_s2l2a_product_id,
)

pytestmark = [pytest.mark.integration]


async def _seed_jobs(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    subscription_id: UUID,
    n: int,
) -> list[UUID]:
    """Insert N succeeded ingestion jobs spanning N days into the past."""
    ids: list[UUID] = []
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for i in range(n):
        job_id = uuid7()
        scene_dt = base - timedelta(days=i)
        await admin_session.execute(
            text(
                f'INSERT INTO "{tenant_schema}".imagery_ingestion_jobs '
                "(id, subscription_id, block_id, product_id, scene_id, "
                " scene_datetime, status, stac_item_id, completed_at) "
                "VALUES (:id, :sub, :block, :prod, :scene, :sdt, 'succeeded', "
                "        :stac, :sdt)"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("sub", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("prod", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": job_id,
                "sub": subscription_id,
                "block": block_id,
                "prod": product_id,
                "scene": f"S2A_TEST_{i:03d}",
                "sdt": scene_dt,
                "stac": f"sentinel_hub/s2_l2a/S2A_TEST_{i:03d}/abc",
            },
        )
        ids.append(job_id)
    await admin_session.commit()
    return ids


@pytest.mark.asyncio
async def test_list_scenes_returns_jobs_in_descending_datetime(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scenes-listing",
        name="Scenes Listing",
        contact_email="ops@scenes.test",
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
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        sub_id = UUID(sub_resp.json()["id"])

        await _seed_jobs(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=UUID(product_id),
            subscription_id=sub_id,
            n=5,
        )

        # Fetch with limit=2 to exercise pagination.
        resp = await client.get(f"/api/v1/blocks/{block_id}/scenes?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    items = body["items"]
    assert len(items) == 2
    # Newest first: S2A_TEST_000 (date 2026-05-01) is newest.
    assert items[0]["scene_id"] == "S2A_TEST_000"
    assert items[1]["scene_id"] == "S2A_TEST_001"
    assert body["next_cursor"] is not None

    # Round-trip the cursor for the next page.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client2:
        resp2 = await client2.get(
            f"/api/v1/blocks/{block_id}/scenes?limit=2" f"&cursor={body['next_cursor']}"
        )
    assert resp2.status_code == 200
    items2 = resp2.json()["items"]
    assert len(items2) == 2
    assert items2[0]["scene_id"] == "S2A_TEST_002"


@pytest.mark.asyncio
async def test_config_returns_tile_server_url_and_products(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="config-endpoint",
        name="Config Endpoint",
        contact_email="ops@config.test",
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
        resp = await client.get("/api/v1/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "tile_server_base_url" in body
    assert body["cloud_cover_visualization_max_pct"] == 60
    assert body["cloud_cover_aggregation_max_pct"] == 20
    products = body["products"]
    assert len(products) >= 1
    s2 = next((p for p in products if p["product_code"] == "s2_l2a"), None)
    assert s2 is not None
    assert "ndvi" in s2["supported_indices"]
