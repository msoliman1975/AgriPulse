"""GET /farms/{id}/latest-photo — the "current satellite photo" map layer.

The high-resolution base map is a vendor mosaic that was last refreshed in
2020 over parts of our farm belt. This route picks the newest pass we fetched
for the farm that is CLEAR over the farm, so the map can lay it on top.

Pinned here:
  * a pass clouded over the farm is skipped for an older clear one, judged by
    the farm's own valid/total pixels rather than the provider's tile figure;
  * a stitched surface is never offered, since it has no farm raw_bands.tif;
  * the band numbers come from the product's band list;
  * no clear pass answers ``photo: null`` rather than an error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_subscription_crud import _create_farm_and_block, _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]


async def _surface(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    block_id: str,
    product_id: str,
    scene: str,
    at: datetime,
    source: str,
    valid: int,
    total: int = 100,
) -> None:
    """One farm surface plus the block NDVI row measured off it."""
    params = {
        "farm": UUID(farm_id),
        "block": UUID(block_id),
        "prod": UUID(product_id),
        "at": at,
        "scene": scene,
        "source": source,
        "valid": valid,
        "total": total,
    }
    await session.execute(
        text(
            f'INSERT INTO "{schema}".farm_scene_rasters '
            "(farm_id, product_id, scene_datetime, scene_id, stac_item_id, "
            " aoi_hash, blocks_merged, indices, source) "
            "SELECT :farm, :prod, :at, :scene, "
            "       'sentinel_hub/s2_l2a/' || :scene || '/' || f.aoi_hash, "
            "       f.aoi_hash, CASE WHEN :source = 'fetched' THEN NULL ELSE 1 END, "
            "       '[\"ndvi\"]'::jsonb, :source "
            f'  FROM "{schema}".farms f WHERE f.id = :farm'
        ).bindparams(
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        params,
    )
    await session.execute(
        text(
            f'INSERT INTO "{schema}".block_index_aggregates '
            "(time, block_id, index_code, product_id, stac_item_id, mean, "
            " valid_pixel_count, total_pixel_count) "
            "SELECT :at, :block, 'ndvi', :prod, "
            "       'sentinel_hub/s2_l2a/' || :scene || '/' || f.aoi_hash, 0.4, "
            "       :valid, :total "
            f'  FROM "{schema}".farms f WHERE f.id = :farm'
        ).bindparams(
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        params,
    )


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, AsyncClient]:
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    return tenant.schema_name, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_latest_photo_skips_a_pass_clouded_over_the_farm(
    admin_session: AsyncSession,
) -> None:
    schema, client = await _setup(admin_session, "latest-photo-cloud")
    clear_at = datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
    async with client:
        farm_id, block_id = await _create_farm_and_block(client)
        product = await _get_s2l2a_product_id(admin_session)
        common = {
            "schema": schema,
            "farm_id": farm_id,
            "block_id": block_id,
            "product_id": product,
        }
        await _surface(
            admin_session, **common, scene="CLEAR", at=clear_at, source="fetched", valid=98
        )
        # Newer, but 40% of the farm under cloud: a white smear, not a photo.
        await _surface(
            admin_session,
            **common,
            scene="CLOUDY",
            at=clear_at + timedelta(days=5),
            source="fetched",
            valid=60,
        )
        # Newest and clear, but stitched: there is no farm raw_bands.tif.
        await _surface(
            admin_session,
            **common,
            scene="STITCHED",
            at=clear_at + timedelta(days=10),
            source="stitched",
            valid=100,
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/latest-photo")

    assert resp.status_code == 200, resp.text
    photo = resp.json()["photo"]
    assert photo is not None
    assert "/CLEAR/" in photo["stac_item_id"]
    assert photo["stac_item_id"].endswith(photo["aoi_hash"])
    assert datetime.fromisoformat(photo["scene_datetime"]) == clear_at
    # s2_l2a stores blue, green, red first: red is band 3.
    assert photo["rgb_band_indexes"] == [3, 2, 1]
    assert photo["clear_fraction"] == pytest.approx(0.98)
    west, south, east, north = photo["bounds"]
    assert west < east, "the farm's box, for the map source"
    assert south < north
    # The tile URL carries the asset as an encoded query value.
    asset = parse_qs(urlsplit(photo["tile_url"]).query)["url"]
    assert asset == [
        f"s3://{get_settings().s3_bucket_uploads}/{photo['stac_item_id']}/raw_bands.tif"
    ]


@pytest.mark.asyncio
async def test_latest_photo_is_null_without_a_clear_pass(admin_session: AsyncSession) -> None:
    schema, client = await _setup(admin_session, "latest-photo-none")
    async with client:
        farm_id, block_id = await _create_farm_and_block(client)
        product = await _get_s2l2a_product_id(admin_session)
        await _surface(
            admin_session,
            schema=schema,
            farm_id=farm_id,
            block_id=block_id,
            product_id=product,
            scene="CLOUDY",
            at=datetime(2026, 10, 1, 8, 30, tzinfo=UTC),
            source="fetched",
            valid=10,
        )
        await admin_session.commit()
        resp = await client.get(f"/api/v1/farms/{farm_id}/latest-photo")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"farm_id": farm_id, "photo": None}
