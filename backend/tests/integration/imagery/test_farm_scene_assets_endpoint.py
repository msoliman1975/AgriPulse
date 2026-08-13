"""HTTP-level tests for GET /farms/{farm_id}/scene-assets.

The console's pixel layer asks this route which raster belongs to which block
for the pass the timeline is parked on. Three properties matter and all three
are load-bearing for what ends up painted on screen:

  * one row per block, never one per job — the layer draws each block once;
  * the ``at`` bound resolves PER BLOCK, because blocks in different tiles are
    sensed minutes apart for what a grower calls one pass;
  * a job that did not succeed is not an asset, however recent it is.
"""

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
    _square_polygon,
)

pytestmark = [pytest.mark.integration]


async def _insert_job(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    subscription_id: UUID,
    scene_id: str,
    scene_datetime: datetime,
    status: str = "succeeded",
    stac_item_id: str | None = None,
) -> None:
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant_schema}".imagery_ingestion_jobs '
            "(id, subscription_id, block_id, product_id, scene_id, "
            " scene_datetime, status, stac_item_id, completed_at) "
            "VALUES (:id, :sub, :block, :prod, :scene, :sdt, :status, :stac, :sdt)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("sub", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid7(),
            "sub": subscription_id,
            "block": block_id,
            "prod": product_id,
            "scene": scene_id,
            "sdt": scene_datetime,
            "status": status,
            "stac": stac_item_id,
        },
    )


@pytest.mark.asyncio
async def test_scene_assets_return_one_row_per_block_honouring_the_bound(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scene-assets",
        name="Scene Assets",
        contact_email="ops@assets.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    base = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_a = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_a}/imagery/subscriptions",
                    json={"product_id": product_id},
                )
            ).json()["id"]
        )
        block_b = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B-IM-2", "boundary": _square_polygon(31.205, 30.005)},
            )
        ).json()["id"]
        sub_b = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_b}/imagery/subscriptions",
                    json={"product_id": product_id},
                )
            ).json()["id"]
        )

        # Block A: an older pass and a newer one.
        await _insert_job(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_a),
            product_id=UUID(product_id),
            subscription_id=sub_a,
            scene_id="OLD_A",
            scene_datetime=base - timedelta(days=5),
            stac_item_id="sentinel_hub/s2_l2a/OLD_A/aoihash",
        )
        await _insert_job(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_a),
            product_id=UUID(product_id),
            subscription_id=sub_a,
            scene_id="NEW_A",
            scene_datetime=base,
            stac_item_id="sentinel_hub/s2_l2a/NEW_A/aoihash",
        )
        # Block B is in another tile: sensed 4 minutes later on the same pass.
        # A single shared timestamp would drop it.
        await _insert_job(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_b),
            product_id=UUID(product_id),
            subscription_id=sub_b,
            scene_id="NEW_B",
            scene_datetime=base + timedelta(minutes=4),
            stac_item_id="sentinel_hub/s2_l2a/NEW_B/aoihash",
        )
        await admin_session.commit()

        # End of the acquisition day — what the timeline sends as `at`.
        # Passed as a param, never interpolated into the URL: an ISO string
        # carries a "+00:00" offset, and an unencoded "+" in a query string
        # decodes to a space, which the route correctly rejects as a 422.
        resp = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets",
            params={"at": (base + timedelta(hours=15)).isoformat()},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Nothing has been stitched for this farm, so the per-block path is what
    # answers. `farm` stays null until a farm raster exists, which is how the
    # cutover runs one farm at a time instead of all at once.
    assert body["farm"] is None
    items = {i["block_id"]: i for i in body["items"]}
    assert len(body["items"]) == 2, "one row per block, not one per job"
    assert items[block_a]["stac_item_id"].endswith("NEW_A/aoihash")
    assert items[block_b]["stac_item_id"].endswith("NEW_B/aoihash")
    # The legend squares this to turn a pixel count into an area.
    assert float(items[block_a]["resolution_m"]) > 0


@pytest.mark.asyncio
async def test_scene_assets_skip_jobs_that_wrote_nothing(
    admin_session: AsyncSession,
) -> None:
    """A cloud-skipped pass belongs on the timeline but has no raster.

    Serving its key would 404 every tile; serving the previous pass instead
    would contradict the date the user is parked on. The block is absent.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scene-assets-cloud",
        name="Scene Assets Cloud",
        contact_email="ops@cloud.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    at = datetime(2026, 5, 12, 9, 0, tzinfo=UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_id = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_id}/imagery/subscriptions",
                    json={"product_id": product_id},
                )
            ).json()["id"]
        )
        await _insert_job(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=UUID(product_id),
            subscription_id=sub_id,
            scene_id="CLOUDY",
            scene_datetime=at,
            status="skipped_cloud",
            stac_item_id=None,
        )
        await admin_session.commit()

        resp = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets",
            params={"at": (at + timedelta(hours=6)).isoformat()},
        )

    assert resp.status_code == 200
    assert resp.json()["items"] == []
