"""GET /farms/{farm_id}/scenes must count BOTH acquisition paths.

A farm with ``fetch_farm_aoi`` writes one row per pass to
``imagery_farm_ingestion_jobs`` and *nothing* to ``imagery_ingestion_jobs``.
The strip read only the block table, so a cut-over farm's timeline collapsed
to whatever block-path jobs it happened to have from before the cutover —
while its indices kept landing and the Insights trend chart kept drawing
months of them.

That is the worst shape this bug can take. The strip is what SELECTS a pass:
a date that is never offered cannot be clicked, so the pixel map draws
nothing on a farm whose farm raster and block aggregates are both present and
correct. #462 fixed the same defect in five observer reads; these are the
console's.
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
from .test_farm_scene_assets_endpoint import _insert_job
from .test_subscription_crud import (
    _create_farm_and_block,
    _get_s2l2a_product_id,
    _square_polygon,
)

pytestmark = [pytest.mark.integration]


async def _farm_subscription(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    farm_id: UUID,
    product_id: UUID,
) -> UUID:
    """A farm cut over to fetching its own AOI."""
    sub_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant_schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": sub_id, "farm": farm_id, "product": product_id},
    )
    return sub_id


async def _insert_farm_job(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    farm_id: UUID,
    product_id: UUID,
    subscription_id: UUID,
    scene_id: str,
    scene_datetime: datetime,
    status: str = "succeeded",
    cloud_cover_pct: float | None = None,
    stac_item_id: str | None = None,
) -> None:
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant_schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, "
            " scene_datetime, status, cloud_cover_pct, stac_item_id, completed_at) "
            "VALUES (:id, :sub, :farm, :prod, :scene, :sdt, :status, :cc, :stac, :sdt)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("sub", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid7(),
            "sub": subscription_id,
            "farm": farm_id,
            "prod": product_id,
            "scene": scene_id,
            "sdt": scene_datetime,
            "status": status,
            "cc": cloud_cover_pct,
            "stac": stac_item_id,
        },
    )


async def _insert_aggregate(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
    product_id: UUID,
    at: datetime,
    index_code: str = "ndvi",
    valid_pixel_count: int = 100,
    total_pixel_count: int = 100,
) -> None:
    """What `_write_block_aggregates_from_farm` leaves behind.

    Measured off the farm-wide raster, so it carries the FARM's
    ``stac_item_id`` and the farm job's ``scene_datetime`` — which is exactly
    why the strip can find it without a block job existing.

    The two pixel counts default to "everything readable". They are what the
    strip's ``no_reading_pct`` is measured from, so a test about cloud over
    part of a farm sets them apart.
    """
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant_schema}".block_index_aggregates '
            "(time, block_id, index_code, product_id, mean, "
            " valid_pixel_count, total_pixel_count, stac_item_id) "
            "VALUES (:at, :block, :code, :prod, 0.5, :valid, :total, :stac)"
        ).bindparams(
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("prod", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "at": at,
            "block": block_id,
            "code": index_code,
            "prod": product_id,
            "valid": valid_pixel_count,
            "total": total_pixel_count,
            "stac": "sentinel_hub/s2_l2a/FARMPASS/farmaoihash",
        },
    )


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, AsyncClient]:
    """A tenant with an admin context and an UNOPENED client.

    The client is handed back before its first request so the caller owns the
    `async with` — httpx refuses to enter a client that has already been
    used, so creating the farm here would close the door behind us.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    client = AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")
    return tenant.schema_name, client


@pytest.mark.asyncio
async def test_a_cut_over_farm_gets_its_whole_timeline(
    admin_session: AsyncSession,
) -> None:
    """The regression: farm-path passes, and NOT ONE block job anywhere.

    Before the fix this farm's strip was empty, so the console could not
    offer a single date to draw — on a farm with three good passes and
    indices computed for every one of them.
    """
    schema, client = await _setup(admin_session, "strip-cutover")
    base = datetime(2026, 6, 10, 8, 30, tzinfo=UTC)

    async with client:
        farm_id, block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        # A second block, so "blocks in this pass" is a number that can be
        # wrong in an interesting way rather than trivially 1.
        block_b = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B-STRIP-2", "boundary": _square_polygon(31.205, 30.005)},
            )
        ).json()["id"]
        sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        for n in range(3):
            at = base - timedelta(days=n * 5)
            await _insert_farm_job(
                admin_session,
                tenant_schema=schema,
                farm_id=UUID(farm_id),
                product_id=UUID(product_id),
                subscription_id=sub,
                scene_id=f"FARM_{n}",
                scene_datetime=at,
                stac_item_id=f"sentinel_hub/s2_l2a/FARM_{n}/farmaoihash",
            )
            # The farm surface is measured against every block, so both
            # blocks carry an aggregate at the farm job's instant.
            for block in (block_a, block_b):
                await _insert_aggregate(
                    admin_session,
                    tenant_schema=schema,
                    block_id=UUID(block),
                    product_id=UUID(product_id),
                    at=at,
                )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["scene_date"] for i in items] == ["2026-06-10", "2026-06-05", "2026-05-31"]
    newest = items[0]
    # Two blocks, because that is the ground one farm acquisition covered —
    # not 1, which is merely how many rows the farm table wrote.
    assert newest["block_count"] == 2
    assert newest["succeeded_count"] == 2
    assert newest["skipped_cloud_count"] == 0
    # Drawable: the strip enables the button on this, and it is the whole
    # reason the day is worth offering.
    assert newest["computed_count"] == 2


@pytest.mark.asyncio
async def test_a_cloud_skipped_farm_pass_reads_as_cloudy_not_unprocessed(
    admin_session: AsyncSession,
) -> None:
    """The two tables do not share a status vocabulary.

    A block job skips as ``skipped_cloud``; a farm job simply as ``skipped``,
    and cloud is the only reason the farm path ever skips one. Folding it
    into ``skipped_cloud_count`` is what lets the strip render "☁ 91%".
    Leaving it out would leave succeeded=0 AND skipped=0, which the frontend
    reads as *unprocessed* — a greyed-out day that has lost the reason why.
    """
    schema, client = await _setup(admin_session, "strip-cloud")
    at = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)

    async with client:
        farm_id, _block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=sub,
            scene_id="FARM_CLOUDY",
            scene_datetime=at,
            status="skipped",
            cloud_cover_pct=91.0,
            stac_item_id=None,
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["succeeded_count"] == 0
    assert row["skipped_cloud_count"] == 1, "farm 'skipped' must fold into the cloud bucket"
    assert row["computed_count"] == 0
    assert round(float(row["cloud_cover_pct"])) == 91


@pytest.mark.asyncio
async def test_a_farm_pass_with_no_indices_is_offered_as_undrawable(
    admin_session: AsyncSession,
) -> None:
    """Acquired but never computed is the state a raw backfill leaves.

    ``computed_count`` is the only honest answer to "can this pass be
    drawn?", and it has to stay 0 for a farm pass whose indices never ran —
    otherwise the console offers a date that paints nothing.
    """
    schema, client = await _setup(admin_session, "strip-raw")
    at = datetime(2026, 6, 14, 9, 0, tzinfo=UTC)

    async with client:
        farm_id, _block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=sub,
            scene_id="FARM_RAW",
            scene_datetime=at,
            stac_item_id="sentinel_hub/s2_l2a/FARM_RAW/farmaoihash",
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["succeeded_count"] == 1, "one live block, and the farm pass covered it"
    assert row["computed_count"] == 0, "no aggregates — nothing to draw"


@pytest.mark.asyncio
async def test_the_cutover_day_takes_the_larger_path_not_their_sum(
    admin_session: AsyncSession,
) -> None:
    """Both paths can write the same day exactly once — on the cutover.

    Summing them would report more blocks acquired than the farm has, which
    is the one number a grower can check by eye.
    """
    schema, client = await _setup(admin_session, "strip-both")
    at = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)

    async with client:
        farm_id, block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        block_sub = UUID(
            (
                await client.post(
                    f"/api/v1/blocks/{block_a}/imagery/subscriptions",
                    json={"product_id": product_id},
                )
            ).json()["id"]
        )
        await _insert_job(
            admin_session,
            tenant_schema=schema,
            block_id=UUID(block_a),
            product_id=UUID(product_id),
            subscription_id=block_sub,
            scene_id="BLOCK_PASS",
            scene_datetime=at,
            stac_item_id="sentinel_hub/s2_l2a/BLOCK_PASS/blockaoihash",
        )
        farm_sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=farm_sub,
            scene_id="FARM_PASS",
            scene_datetime=at,
            stac_item_id="sentinel_hub/s2_l2a/FARM_PASS/farmaoihash",
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["block_count"] == 1, "one block, however many paths acquired it"
    assert row["succeeded_count"] == 1


@pytest.mark.asyncio
async def test_a_block_path_farm_is_unchanged(
    admin_session: AsyncSession,
) -> None:
    """The farm branch must not perturb the farms that have not cut over.

    Every farm on the platform is still on the block path, so this is the
    case the fix is most likely to break and least likely to be noticed
    breaking.
    """
    schema, client = await _setup(admin_session, "strip-blocks")
    at = datetime(2026, 6, 18, 9, 0, tzinfo=UTC)

    async with client:
        farm_id, block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        block_b = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B-STRIP-B", "boundary": _square_polygon(31.205, 30.005)},
            )
        ).json()["id"]
        for block, scene, status in (
            (block_a, "OK_A", "succeeded"),
            (block_b, "CLOUD_B", "skipped_cloud"),
        ):
            sub = UUID(
                (
                    await client.post(
                        f"/api/v1/blocks/{block}/imagery/subscriptions",
                        json={"product_id": product_id},
                    )
                ).json()["id"]
            )
            await _insert_job(
                admin_session,
                tenant_schema=schema,
                block_id=UUID(block),
                product_id=UUID(product_id),
                subscription_id=sub,
                scene_id=scene,
                scene_datetime=at,
                status=status,
                stac_item_id=(
                    f"sentinel_hub/s2_l2a/{scene}/aoihash" if status == "succeeded" else None
                ),
            )
        await _insert_aggregate(
            admin_session,
            tenant_schema=schema,
            block_id=UUID(block_a),
            product_id=UUID(product_id),
            at=at,
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["block_count"] == 2
    assert row["succeeded_count"] == 1
    assert row["skipped_cloud_count"] == 1
    assert row["computed_count"] == 1


@pytest.mark.asyncio
async def test_the_pixel_layer_still_resolves_for_a_cut_over_farm(
    admin_session: AsyncSession,
) -> None:
    """The sibling route needed no farm branch, and this is why.

    `/scene-assets` drives its per-block `items` off the block job table too,
    so a cut-over farm returns none — but it also carries `farm`, read from
    `farm_scene_rasters`, which the farm-AOI fetch writes with
    ``source='fetched'``. The frontend draws that INSTEAD of the per-block
    items, and `farmRasterForPass` accepts it unconditionally when there are
    no blocks to disagree about the pass.

    So the pixel layer was never the broken half. Pinning that here means a
    future change to either side has to keep it true.
    """
    schema, client = await _setup(admin_session, "strip-pixels")
    at = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)

    async with client:
        farm_id, _block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".farm_scene_rasters '
                "(farm_id, product_id, scene_datetime, scene_id, stac_item_id, "
                " aoi_hash, blocks_merged, indices, source) "
                "SELECT :farm, :prod, :at, 'FARM_PASS', "
                "       'sentinel_hub/s2_l2a/FARM_PASS/' || f.aoi_hash, "
                "       f.aoi_hash, NULL, '[\"ndvi\"]'::jsonb, 'fetched' "
                f'  FROM "{schema}".farms f WHERE f.id = :farm'
            ).bindparams(
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("prod", type_=PG_UUID(as_uuid=True)),
            ),
            {"farm": UUID(farm_id), "prod": UUID(product_id), "at": at},
        )
        await admin_session.commit()

        resp = await client.get(
            f"/api/v1/farms/{farm_id}/scene-assets",
            params={"at": (at + timedelta(hours=6)).isoformat()},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == [], "no block jobs — the per-block path has nothing"
    assert body["farm"] is not None, "the farm surface is what the layer draws"
    assert body["farm"]["stac_item_id"].startswith("sentinel_hub/s2_l2a/FARM_PASS/")


@pytest.mark.asyncio
async def test_a_partly_clouded_pass_reports_what_the_farm_lost(
    admin_session: AsyncSession,
) -> None:
    """A pass can succeed and still leave holes in the map.

    Green Farm [Demo-01] on 2026-08-18 is the case this was written for: the
    job succeeded, the scene-classification mask dropped 319 of the farm's
    5,037 pixels as cloud, and 84 of AG-R02-C02's 224 grid cells came back
    with no value. Every index has the same holes, because they share one
    mask. The strip said nothing about it and the day read as a plain "4".

    The job's own ``cloud_cover_pct`` cannot carry this. It is the STAC
    ``eo:cloud_cover`` of a whole Sentinel-2 tile, 110 km on a side, so on
    that farm it calls 2026-08-17 the cloudier day (13.24% against 6.50%)
    when 08-17 lost 2.04% of the farm and 08-18 lost 8.17%. It ranks the two
    backwards, which is why this reads the pixel counts instead.
    """
    schema, client = await _setup(admin_session, "strip-partly-cloudy")
    at = datetime(2026, 8, 18, 8, 51, tzinfo=UTC)

    async with client:
        farm_id, block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=sub,
            scene_id="FARM_PARTLY_CLOUDY",
            scene_datetime=at,
            # Low, and deliberately so: the tile figure and the farm's own
            # loss disagree, and the strip must follow the farm.
            cloud_cover_pct=6.5,
            stac_item_id="sentinel_hub/s2_l2a/FARM_PARTLY_CLOUDY/farmaoihash",
        )
        await _insert_aggregate(
            admin_session,
            tenant_schema=schema,
            block_id=UUID(block_a),
            product_id=UUID(product_id),
            at=at,
            valid_pixel_count=917,
            total_pixel_count=1000,
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["computed_count"] == 1, "the pass is drawable — most of the farm has a value"
    assert float(row["no_reading_pct"]) == 8.30, "83 of 1000 pixels carry no value"
    assert round(float(row["cloud_cover_pct"])) == 6, "the tile figure is kept, and disagrees"


@pytest.mark.asyncio
async def test_a_pass_that_never_computed_reports_no_loss_rather_than_zero(
    admin_session: AsyncSession,
) -> None:
    """Nothing was measured, so there is no share to report.

    Zero would read as "the whole farm has a value", which is the opposite of
    what an unprocessed pass means. Null is the honest answer, and
    ``computed_count`` is what the console greys the day out on.
    """
    schema, client = await _setup(admin_session, "strip-no-loss")
    at = datetime(2026, 8, 18, 8, 51, tzinfo=UTC)

    async with client:
        farm_id, _block_a = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub = await _farm_subscription(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
        )
        await _insert_farm_job(
            admin_session,
            tenant_schema=schema,
            farm_id=UUID(farm_id),
            product_id=UUID(product_id),
            subscription_id=sub,
            scene_id="FARM_UNCOMPUTED",
            scene_datetime=at,
            stac_item_id="sentinel_hub/s2_l2a/FARM_UNCOMPUTED/farmaoihash",
        )
        await admin_session.commit()

        resp = await client.get(f"/api/v1/farms/{farm_id}/scenes")

    assert resp.status_code == 200
    (row,) = resp.json()["items"]
    assert row["computed_count"] == 0
    assert row["no_reading_pct"] is None
