"""`last_successful_ingest_at` is derived from the job rows, not remembered.

The column used to be a wall-clock stamp written by a discovery poll that
queued at least one job. A farm whose whole history arrived through
`imagery.backfill_scenes` therefore kept NULL for ever: the backfill passes
`bump_watermark=False`, and a live poll only stamped it when it created a
job, which a caught-up subscription never does.

Prod, 2026-08-25, Mango Republic: 216 succeeded Sentinel-2 jobs, newest
scene sensed on 20 August, watermark NULL. `_resolve_discovery_window` reads
NULL as a cold start, so that subscription asked the catalogue for a 90-day
window every day and read back 27 scenes it already held.

These tests pin the new contract: the value is the sensing time of the newest
scene the subscription has successfully ingested, and a poll heartbeat does
not write it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.repository import ImageryRepository
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

# Three passes and a fourth that did not land. The newest SUCCEEDED one is
# the answer; the newer failed one must not be.
_OLD = datetime(2026, 8, 10, 8, 41, tzinfo=UTC)
_MID = datetime(2026, 8, 15, 8, 41, tzinfo=UTC)
_NEWEST_OK = datetime(2026, 8, 20, 8, 41, tzinfo=UTC)
_NEWER_FAILED = datetime(2026, 8, 25, 8, 41, tzinfo=UTC)


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, UUID, UUID, UUID]:
    """Tenant + farm + block + one active block subscription.

    Returns ``(schema, farm_id, product_id, block_subscription_id)``.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        assert resp.status_code == 201, resp.text
        sub_id = resp.json()["id"]
    return tenant.schema_name, UUID(farm_id), UUID(product_id), UUID(sub_id)


async def _seed_block_jobs(
    session: AsyncSession, *, schema: str, sub_id: UUID, block_id: UUID, product_id: UUID
) -> None:
    for scene_time, status in (
        (_OLD, "succeeded"),
        (_MID, "succeeded"),
        (_NEWEST_OK, "succeeded"),
        (_NEWER_FAILED, "failed"),
    ):
        await session.execute(
            text(
                f'INSERT INTO "{schema}".imagery_ingestion_jobs '
                "(id, subscription_id, block_id, product_id, scene_id, "
                " scene_datetime, status) "
                "VALUES (:id, :sub, :block, :product, :scene, :at, :status)"
            ),
            {
                "id": uuid4(),
                "sub": sub_id,
                "block": block_id,
                "product": product_id,
                "scene": f"scene-{scene_time.date()}",
                "at": scene_time,
                "status": status,
            },
        )


async def _read_watermark(
    session: AsyncSession, *, schema: str, table: str, sub_id: UUID
) -> datetime | None:
    return (
        await session.execute(
            text(f'SELECT last_successful_ingest_at FROM "{schema}".{table} WHERE id = :id'),
            {"id": sub_id},
        )
    ).scalar_one()


async def _block_id_of(session: AsyncSession, *, schema: str, sub_id: UUID) -> UUID:
    return (
        await session.execute(
            text(f'SELECT block_id FROM "{schema}".imagery_aoi_subscriptions WHERE id = :id'),
            {"id": sub_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_block_watermark_is_the_newest_succeeded_scene(
    admin_session: AsyncSession,
) -> None:
    schema, _farm_id, product_id, sub_id = await _setup(admin_session, "watermark-block")
    block_id = await _block_id_of(admin_session, schema=schema, sub_id=sub_id)
    await _seed_block_jobs(
        admin_session, schema=schema, sub_id=sub_id, block_id=block_id, product_id=product_id
    )
    # The prod starting state: succeeded jobs, no watermark.
    assert (
        await _read_watermark(
            admin_session, schema=schema, table="imagery_aoi_subscriptions", sub_id=sub_id
        )
        is None
    )

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    got = await ImageryRepository(admin_session).refresh_ingest_watermark(subscription_id=sub_id)

    assert got == _NEWEST_OK, "the failed 25 August pass must not count as ingested"
    assert (
        await _read_watermark(
            admin_session, schema=schema, table="imagery_aoi_subscriptions", sub_id=sub_id
        )
        == _NEWEST_OK
    )


@pytest.mark.asyncio
async def test_a_poll_heartbeat_does_not_write_the_watermark(
    admin_session: AsyncSession,
) -> None:
    """`last_attempted_at` and the watermark answer different questions.

    Overdue keys off the poll clock; the discovery window keys off the scene
    clock. A poll that found nothing must move only the first one.
    """
    schema, _farm_id, product_id, sub_id = await _setup(admin_session, "watermark-heartbeat")
    block_id = await _block_id_of(admin_session, schema=schema, sub_id=sub_id)
    await _seed_block_jobs(
        admin_session, schema=schema, sub_id=sub_id, block_id=block_id, product_id=product_id
    )
    polled_at = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    repo = ImageryRepository(admin_session)
    await repo.refresh_ingest_watermark(subscription_id=sub_id)
    await repo.touch_subscription_attempt(subscription_id=sub_id, attempted_at=polled_at)

    row = (
        await admin_session.execute(
            text(
                "SELECT last_attempted_at, last_successful_ingest_at "
                f'FROM "{schema}".imagery_aoi_subscriptions WHERE id = :id'
            ),
            {"id": sub_id},
        )
    ).one()
    assert row.last_attempted_at == polled_at
    assert row.last_successful_ingest_at == _NEWEST_OK


@pytest.mark.asyncio
async def test_farm_watermark_is_the_newest_succeeded_scene(
    admin_session: AsyncSession,
) -> None:
    """The Mango Republic shape: a farm-AOI subscription filled by a backfill."""
    schema, farm_id, product_id, _block_sub = await _setup(admin_session, "watermark-farm")
    farm_sub_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": farm_sub_id, "farm": farm_id, "product": product_id},
    )
    for scene_time, status in (
        (_MID, "succeeded"),
        (_NEWEST_OK, "succeeded"),
        (_NEWER_FAILED, "skipped"),
    ):
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
                "(id, subscription_id, farm_id, product_id, scene_id, "
                " scene_datetime, status) "
                "VALUES (:id, :sub, :farm, :product, :scene, :at, :status)"
            ),
            {
                "id": uuid4(),
                "sub": farm_sub_id,
                "farm": farm_id,
                "product": product_id,
                "scene": f"farm-scene-{scene_time.date()}",
                "at": scene_time,
                "status": status,
            },
        )

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    got = await ImageryRepository(admin_session).refresh_farm_ingest_watermark(
        subscription_id=farm_sub_id
    )

    assert got == _NEWEST_OK, "a cloud-skipped pass is not an ingest"
    assert (
        await _read_watermark(
            admin_session, schema=schema, table="imagery_farm_subscriptions", sub_id=farm_sub_id
        )
        == _NEWEST_OK
    )
