"""A farm subscription must fetch something.

`fetch_farm_aoi` false means "this farm is fetched one block at a time", and
the block sweep is driven by `imagery_aoi_subscriptions` and by nothing else.
Subscribing a farm that has no such rows therefore produced a subscription that
was active, listed, reported as per-block on the Farm tab — and fetched
nothing, ever.

Measured on prod: greenFarm_Test carried two active farm subscriptions
(`s2_l2a` and `landsat_c2_l2_st`), zero block subscriptions, zero jobs on
either path, and `last_attempted_at` NULL since the day it was created. The
only surface that noticed was the backfill console's pre-flight — "0
subscriptions ... this farm has no active imagery subscriptions" — which reads
as the pre-flight being broken when it is the one thing telling the truth.

So the path is resolved at the write, where the farm's shape is known.
"""

from __future__ import annotations

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
    create_user_in_tenant,
    make_context,
)
from .test_farm_aoi_fetchability import _HUGE, _SMALL
from .test_subscription_crud import _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]

_BLOCKS = (
    "POLYGON((31.201 30.001,31.203 30.001,31.203 30.003,31.201 30.003,31.201 30.001))",
    "POLYGON((31.204 30.001,31.206 30.001,31.206 30.003,31.204 30.003,31.204 30.001))",
)


async def _setup(
    admin_session: AsyncSession,
    slug: str,
    *,
    boundary_wkt: str = _SMALL,
    with_block_subs: bool = False,
    with_block_history: bool = False,
) -> dict[str, Any]:
    """A tenant with one farm, two blocks, and whatever imagery past it has."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    schema = tenant.schema_name
    product_id = UUID(await _get_s2l2a_product_id(admin_session))
    farm_id = uuid4()
    block_ids = [uuid4() for _ in _BLOCKS]

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'PATH', 'Path farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": boundary_wkt},
    )
    for i, (block_id, wkt) in enumerate(zip(block_ids, _BLOCKS, strict=True)):
        await admin_session.execute(
            text(
                "INSERT INTO blocks (id, farm_id, code, name, boundary) "
                "VALUES (:id, :fid, :code, :code, ST_GeomFromText(:wkt, 4326))"
            ),
            {"id": str(block_id), "fid": str(farm_id), "code": f"B{i + 1}", "wkt": wkt},
        )
        if with_block_subs:
            await admin_session.execute(
                text(
                    "INSERT INTO imagery_aoi_subscriptions "
                    "(block_id, product_id, cadence_hours, is_active) "
                    "VALUES (:bid, :pid, 24, TRUE)"
                ),
                {"bid": str(block_id), "pid": str(product_id)},
            )
        if with_block_history:
            # History implies a subscription that has since been revoked —
            # inactive, so it conflicts with nothing and the sweep ignores it,
            # while the jobs it produced stay on screen.
            revoked_id = uuid4()
            await admin_session.execute(
                text(
                    "INSERT INTO imagery_aoi_subscriptions "
                    "(id, block_id, product_id, cadence_hours, is_active) "
                    "VALUES (:id, :bid, :pid, 24, FALSE)"
                ),
                {"id": str(revoked_id), "bid": str(block_id), "pid": str(product_id)},
            )
            await admin_session.execute(
                text(
                    "INSERT INTO imagery_ingestion_jobs "
                    "(id, subscription_id, block_id, product_id, scene_id, "
                    " scene_datetime, status) "
                    "VALUES (:id, :sub, :bid, :pid, 'PAST', "
                    "        '2026-05-01T08:00:00Z', 'succeeded')"
                ),
                {
                    "id": str(uuid4()),
                    "sub": str(revoked_id),
                    "bid": str(block_id),
                    "pid": str(product_id),
                },
            )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return {
        "schema": schema,
        "farm_id": farm_id,
        "product_id": product_id,
        "app": build_app(context),
    }


async def _subscribe(env: dict[str, Any]) -> dict[str, Any]:
    """POST the farm subscription exactly as the Farm tab does — no flag."""
    async with AsyncClient(
        transport=ASGITransport(app=env["app"]), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/farms/{env['farm_id']}/imagery/subscriptions",
            json={"product_id": str(env["product_id"])},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _active_block_subs(admin_session: AsyncSession, env: dict[str, Any]) -> int:
    return int(
        (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{env["schema"]}".imagery_aoi_subscriptions s '
                    f'JOIN "{env["schema"]}".blocks b ON b.id = s.block_id '
                    "WHERE b.farm_id = :fid AND s.is_active AND s.deleted_at IS NULL"
                ),
                {"fid": env["farm_id"]},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_a_farm_with_no_blocks_subscribed_takes_the_whole_farm_path(
    admin_session: AsyncSession,
) -> None:
    """The greenFarm_Test case, which is what a NEW farm looks like.

    Nothing is reading a per-block series that a stitched surface would put a
    step in, and the boundary fits in one request — so the honest reading of
    "subscribe this farm" is the farm's own AOI.
    """
    env = await _setup(admin_session, "path-new-farm")
    body = await _subscribe(env)

    assert body["fetch_farm_aoi"] is True, "a subscription that fetches nothing is not a fix"
    assert body["is_active"] is True
    assert await _active_block_subs(admin_session, env) == 0, "no need to touch the blocks"


@pytest.mark.asyncio
async def test_a_farm_whose_blocks_are_already_subscribed_is_left_alone(
    admin_session: AsyncSession,
) -> None:
    """Per-block is a true statement here, so nothing may move.

    This is the case that must not become a silent cutover: flipping a farm
    with a running block sweep onto the farm path puts a ~0.7% step in every
    block's series.
    """
    env = await _setup(admin_session, "path-has-blocks", with_block_subs=True)
    body = await _subscribe(env)

    assert body["fetch_farm_aoi"] is False
    assert await _active_block_subs(admin_session, env) == 2, "no duplicates, no removals"


@pytest.mark.asyncio
async def test_a_farm_with_history_but_no_live_block_subs_gets_its_blocks_back(
    admin_session: AsyncSession,
) -> None:
    """Revoked subscriptions, months of history on screen.

    Moving this farm onto the farm path would step every series somebody is
    already reading, so the row's own words are honoured instead: the blocks
    are subscribed.
    """
    env = await _setup(admin_session, "path-has-history", with_block_history=True)
    body = await _subscribe(env)

    assert body["fetch_farm_aoi"] is False, "history is a reason NOT to cut over"
    assert await _active_block_subs(admin_session, env) == 2


@pytest.mark.asyncio
async def test_a_farm_too_large_to_fetch_whole_gets_its_blocks_subscribed(
    admin_session: AsyncSession,
) -> None:
    """48 km across: the provider cannot return this farm in one request.

    The farm path is not available at all here, so the only way the
    subscription can mean anything is per block.
    """
    env = await _setup(admin_session, "path-too-large", boundary_wkt=_HUGE)
    body = await _subscribe(env)

    assert body["fetch_farm_aoi"] is False
    assert body["farm_aoi_fetchable"] is False, "and the read says why"
    assert await _active_block_subs(admin_session, env) == 2
