"""A farm carrying two products must answer each index from its own stream.

`landsat_c2_l2_st` (thermal: lst/cwsi/smi) and `s2_l2a` (the optical ten) are
disjoint index sets fetched on independent cadences — 24 h against ~5 days on
the reference farm. Both write into the same job tables, and both routes the
console's pixel layer reads used to order by `scene_datetime` alone.

That is a wrong answer wearing the shape of a right one. The caller turns a
row into a tile URL by appending `<index>.tif` to the key it derives from
`stac_item_id`, so being handed the newest job of the OTHER product yields a
key with no object behind it: every tile 404s and the block goes blank under a
timeline that says a pass was acquired. With thermal on the faster cadence,
that was most days of the week.

The strip had the mirror-image bug: it tested drawability against a hardcoded
`ndvi` aggregate, so a thermal pass — which writes lst/cwsi/smi and never
ndvi — was marked unprocessed forever, while a Sentinel-2 pass was offered as
drawable for `lst`, which it cannot draw.
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

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_farm_scene_assets_endpoint import _insert_job
from .test_subscription_crud import _create_farm_and_block, _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]


async def _get_thermal_product_id(session: AsyncSession) -> str:
    pid = (
        await session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 'landsat_c2_l2_st'")
        )
    ).scalar_one()
    return str(pid)


async def _insert_aggregate(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    index_code: str,
    at: datetime,
    stac_item_id: str,
) -> None:
    """One `block_index_aggregates` row — the proof a pass was computed.

    The strip reads these and nothing else to decide whether a date can be
    drawn, because `compute_indices` is the only writer.
    """
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant_schema}".block_index_aggregates '
            "(time, block_id, index_code, product_id, stac_item_id, mean, "
            " valid_pixel_count, total_pixel_count) "
            "VALUES (:at, :block, :code, :prod, :stac, :mean, 100, 100)"
        ).bindparams(
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "at": at,
            "block": block_id,
            "code": index_code,
            "prod": product_id,
            "stac": stac_item_id,
            "mean": 0.42,
        },
    )


@pytest.mark.asyncio
async def test_scene_assets_answer_each_index_from_its_own_product(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scene-assets-thermal",
        name="Scene Assets Thermal",
        contact_email="ops@thermal.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    app = build_app(
        make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            tenant_role=TenantRole.TENANT_ADMIN,
        )
    )
    optical_at = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    # The thermal pass is NEWER, which is the whole point: ordering by time
    # alone hands it to every caller, including the ones asking for ndvi.
    thermal_at = optical_at + timedelta(hours=3)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        optical_product = await _get_s2l2a_product_id(admin_session)
        thermal_product = await _get_thermal_product_id(admin_session)
        subscription = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_id}/imagery/subscriptions",
                    json={"product_id": optical_product},
                )
            ).json()["id"]
        )

        for product, scene, at in (
            (optical_product, "S2_PASS", optical_at),
            (thermal_product, "LS_PASS", thermal_at),
        ):
            await _insert_job(
                admin_session,
                tenant_schema=tenant.schema_name,
                block_id=UUID(block_id),
                product_id=UUID(product),
                subscription_id=subscription,
                scene_id=scene,
                scene_datetime=at,
                stac_item_id=f"prov/{scene}/{scene}/aoihash",
            )
        await admin_session.commit()

        bound = {"at": (optical_at + timedelta(hours=15)).isoformat()}
        optical = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets", params={**bound, "index": "ndvi"}
        )
        thermal = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets", params={**bound, "index": "lst"}
        )
        # No index named at all: the pre-existing contract, which is ndvi.
        legacy = await client.get(f"/api/v1/farms/{farm_id}/scene-assets", params=bound)

    assert optical.status_code == 200
    assert thermal.status_code == 200
    optical_items = optical.json()["items"]
    assert len(optical_items) == 1
    assert (
        "S2_PASS" in optical_items[0]["stac_item_id"]
    ), "ndvi must resolve to the Sentinel-2 pass even though the thermal one is newer"
    thermal_items = thermal.json()["items"]
    assert len(thermal_items) == 1
    assert "LS_PASS" in thermal_items[0]["stac_item_id"]
    assert legacy.json()["items"] == optical_items, "omitting index must keep the old behaviour"


@pytest.mark.asyncio
async def test_scene_assets_are_empty_for_an_index_no_product_produces(
    admin_session: AsyncSession,
) -> None:
    """An unknown index resolves to no product, and so to no rows.

    The failure mode being closed off is the opposite one: treating "no
    product filter" as "every product", which would hand back a raster for an
    index that cannot exist on it.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scene-assets-unknown",
        name="Scene Assets Unknown",
        contact_email="ops@unknown.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    app = build_app(
        make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            tenant_role=TenantRole.TENANT_ADMIN,
        )
    )
    at = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product = await _get_s2l2a_product_id(admin_session)
        subscription = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_id}/imagery/subscriptions",
                    json={"product_id": product},
                )
            ).json()["id"]
        )
        await _insert_job(
            admin_session,
            tenant_schema=tenant.schema_name,
            block_id=UUID(block_id),
            product_id=UUID(product),
            subscription_id=subscription,
            scene_id="S2_PASS",
            scene_datetime=at,
            stac_item_id="prov/S2_PASS/S2_PASS/aoihash",
        )
        await admin_session.commit()

        resp = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets", params={"index": "not_an_index"}
        )

    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["farm"] is None


@pytest.mark.asyncio
async def test_scene_strip_tests_drawability_against_the_index_asked_for(
    admin_session: AsyncSession,
) -> None:
    """A thermal pass is drawable for `lst` and invisible to `ndvi`.

    `computed_count` is what greys a date out. Hardcoded to `ndvi` it read
    zero for every thermal pass ever acquired — the strip is what SELECTS a
    pass, so an unselectable date means the index can never be drawn at all.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scene-strip-thermal",
        name="Scene Strip Thermal",
        contact_email="ops@strip.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    app = build_app(
        make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            tenant_role=TenantRole.TENANT_ADMIN,
        )
    )
    optical_at = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    thermal_at = datetime(2026, 5, 12, 8, 20, tzinfo=UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        optical_product = await _get_s2l2a_product_id(admin_session)
        thermal_product = await _get_thermal_product_id(admin_session)
        subscription = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_id}/imagery/subscriptions",
                    json={"product_id": optical_product},
                )
            ).json()["id"]
        )

        for product, scene, at, code in (
            (optical_product, "S2_PASS", optical_at, "ndvi"),
            (thermal_product, "LS_PASS", thermal_at, "lst"),
        ):
            stac = f"prov/{scene}/{scene}/aoihash"
            await _insert_job(
                admin_session,
                tenant_schema=tenant.schema_name,
                block_id=UUID(block_id),
                product_id=UUID(product),
                subscription_id=subscription,
                scene_id=scene,
                scene_datetime=at,
                stac_item_id=stac,
            )
            await _insert_aggregate(
                admin_session,
                tenant_schema=tenant.schema_name,
                block_id=UUID(block_id),
                product_id=UUID(product),
                index_code=code,
                at=at,
                stac_item_id=stac,
            )
        await admin_session.commit()

        ndvi = await client.get(f"/api/v1/farms/{farm_id}/scenes", params={"index": "ndvi"})
        lst = await client.get(f"/api/v1/farms/{farm_id}/scenes", params={"index": "lst"})

    assert ndvi.status_code == 200
    assert lst.status_code == 200
    ndvi_days = {i["scene_date"]: i for i in ndvi.json()["items"]}
    lst_days = {i["scene_date"]: i for i in lst.json()["items"]}

    assert set(ndvi_days) == {"2026-05-10"}, "the thermal pass is not an optical acquisition"
    assert ndvi_days["2026-05-10"]["computed_count"] == 1

    assert set(lst_days) == {"2026-05-12"}, "and the optical pass is not a thermal one"
    assert lst_days["2026-05-12"]["computed_count"] == 1, (
        "a thermal pass has no ndvi aggregate and never will — testing for one "
        "marked every thermal date unprocessed"
    )
