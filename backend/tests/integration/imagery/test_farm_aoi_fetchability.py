"""What happens to a farm the provider cannot return in one request?

Sentinel Hub's Process API caps output at 2500 px per side — 25 km at 10 m.
`fetch_farm_aoi` is not only "fetch the farm as one AOI": it is also what
excludes that farm's blocks from the block sweep. So a farm left switched ON
while too large to fetch received **no imagery from either path**, and the only
trace was an overdue row in integration health.

Three things close that:

  * the write is refused, with the measurement, rather than accepted;
  * a farm that becomes too large later (its boundary is redrawn) falls back to
    the block path by itself on the next poll;
  * the read says which path a farm is on and, when it is stuck on blocks, why.

The size is measured on read rather than stored, because a boundary can be
redrawn at any time and a stored verdict would go stale with nothing to notice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery import tasks as imagery_tasks
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
from .test_farm_aoi_ingestion import SCENE, _FakeProvider
from .test_subscription_crud import _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]

# ~48 km x 33 km at this latitude: 4800 x 3300 px at the product's 10 m, both
# sides over the 2500 limit. A farm this size is not hypothetical — it is what
# an estate drawn as one boundary looks like.
_HUGE = "POLYGON((31.0 30.0,31.5 30.0,31.5 30.3,31.0 30.3,31.0 30.0))"
# Comfortably inside the limit.
_SMALL = "POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))"


async def _setup(admin_session: AsyncSession, slug: str, *, boundary_wkt: str) -> dict[str, Any]:
    """Tenant + farm of the given size + one block with a block subscription."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    schema = tenant.schema_name
    product_id = UUID(await _get_s2l2a_product_id(admin_session))

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'AOI', 'AOI farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": boundary_wkt},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) VALUES (:id, :fid, 'B1', "
            "'B1', ST_GeomFromText('POLYGON((31.201 30.001,31.205 30.001,31.205 30.005,"
            "31.201 30.005,31.201 30.001))', 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_aoi_subscriptions (block_id, product_id, cadence_hours, "
            "is_active) VALUES (:bid, :pid, 24, TRUE)"
        ),
        {"bid": str(block_id), "pid": str(product_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_id": block_id,
        "product_id": product_id,
        "app": build_app(context),
    }


def _client(env: dict[str, Any]) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=env["app"]), base_url="http://test")


async def _add_farm_subscription(
    admin_session: AsyncSession, env: dict[str, Any], *, fetch_farm_aoi: bool
) -> UUID:
    sub_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{env["schema"]}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, :fetch)"
        ),
        {
            "id": sub_id,
            "farm": env["farm_id"],
            "product": env["product_id"],
            "fetch": fetch_farm_aoi,
        },
    )
    await admin_session.commit()
    return sub_id


async def _fetch_flag(admin_session: AsyncSession, schema: str, sub_id: UUID) -> bool:
    return bool(
        (
            await admin_session.execute(
                text(
                    f'SELECT fetch_farm_aoi FROM "{schema}".imagery_farm_subscriptions '
                    "WHERE id = :id"
                ),
                {"id": sub_id},
            )
        ).scalar_one()
    )


async def _due_block_count(session: AsyncSession, schema: str) -> int:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = await ImageryRepository(session).list_active_subscriptions_due(
        default_cadence_hours=24, now=datetime.now(UTC)
    )
    await session.execute(text("SET search_path TO public"))
    return len(rows)


@pytest.mark.asyncio
async def test_a_normal_farm_reports_itself_fetchable(
    admin_session: AsyncSession,
) -> None:
    env = await _setup(admin_session, "aoi-fit-small", boundary_wkt=_SMALL)
    await _add_farm_subscription(admin_session, env, fetch_farm_aoi=False)

    async with _client(env) as client:
        rows = (await client.get(f"/api/v1/farms/{env['farm_id']}/imagery/subscriptions")).json()

    assert len(rows) == 1
    assert rows[0]["farm_aoi_fetchable"] is True
    assert rows[0]["farm_aoi_max_px"] == 2500
    # Measured, not assumed: a fetchable farm still reports its size.
    assert rows[0]["farm_aoi_width_px"] <= 2500


@pytest.mark.asyncio
async def test_an_oversized_farm_reports_why_it_cannot_be_fetched(
    admin_session: AsyncSession,
) -> None:
    env = await _setup(admin_session, "aoi-fit-huge", boundary_wkt=_HUGE)
    await _add_farm_subscription(admin_session, env, fetch_farm_aoi=False)

    async with _client(env) as client:
        rows = (await client.get(f"/api/v1/farms/{env['farm_id']}/imagery/subscriptions")).json()

    assert rows[0]["farm_aoi_fetchable"] is False
    # The numbers are the point: without them the refusal reads as arbitrary.
    assert rows[0]["farm_aoi_width_px"] > 2500
    assert rows[0]["farm_aoi_height_px"] > 2500


@pytest.mark.asyncio
async def test_switching_an_oversized_farm_over_is_refused(
    admin_session: AsyncSession,
) -> None:
    """422 at the write, not a stopped farm discovered days later."""
    env = await _setup(admin_session, "aoi-fit-refuse", boundary_wkt=_HUGE)
    sub_id = await _add_farm_subscription(admin_session, env, fetch_farm_aoi=False)

    async with _client(env) as client:
        resp = await client.patch(
            f"/api/v1/farms/{env['farm_id']}/imagery/subscriptions/{sub_id}",
            json={"fetch_farm_aoi": True},
        )

    assert resp.status_code == 422, resp.text
    assert "one request" in resp.json()["detail"]
    # And the refusal did not half-apply.
    assert await _fetch_flag(admin_session, env["schema"], sub_id) is False


@pytest.mark.asyncio
async def test_a_fetchable_farm_can_still_be_switched_over(
    admin_session: AsyncSession,
) -> None:
    """The guard must refuse the impossible, not the ordinary."""
    env = await _setup(admin_session, "aoi-fit-allow", boundary_wkt=_SMALL)
    sub_id = await _add_farm_subscription(admin_session, env, fetch_farm_aoi=False)

    async with _client(env) as client:
        resp = await client.patch(
            f"/api/v1/farms/{env['farm_id']}/imagery/subscriptions/{sub_id}",
            json={"fetch_farm_aoi": True},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["fetch_farm_aoi"] is True
    assert await _fetch_flag(admin_session, env["schema"], sub_id) is True


@pytest.mark.asyncio
async def test_a_farm_that_grew_too_large_falls_back_to_its_blocks(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this whole file exists for.

    A farm already switched over, then redrawn bigger, could not be fetched —
    and its blocks stayed excluded from the block sweep because the exclusion
    keys on the flag alone. Discovery now switches the farm back so the blocks
    resume on the very next sweep.
    """
    env = await _setup(admin_session, "aoi-fit-fallback", boundary_wkt=_HUGE)
    # Switched over directly in SQL, the way the cutover is driven — the API
    # would now refuse it, which is exactly the state this repairs.
    sub_id = await _add_farm_subscription(admin_session, env, fetch_farm_aoi=True)

    # While the farm is switched on, its blocks are NOT swept: this is the
    # state in which the farm was receiving nothing from either path.
    assert await _due_block_count(admin_session, env["schema"]) == 0

    imagery_tasks.set_provider_factory(lambda: _FakeProvider((SCENE,)))
    monkeypatch.setattr(imagery_tasks.acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        result = await imagery_tasks._discover_farm_scenes_async(sub_id, env["schema"])
    finally:
        imagery_tasks.reset_provider_factory()

    assert result == {"discovered": 0, "queued": 0, "skipped_cloud": 0}
    assert await _fetch_flag(admin_session, env["schema"], sub_id) is False
    # The blocks are due again, which is the whole point of switching it back.
    assert await _due_block_count(admin_session, env["schema"]) == 1


@pytest.mark.asyncio
async def test_a_fetchable_farm_is_left_switched_on(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback must fire on the size check, not on every discovery."""
    env = await _setup(admin_session, "aoi-fit-stayon", boundary_wkt=_SMALL)
    sub_id = await _add_farm_subscription(admin_session, env, fetch_farm_aoi=True)

    imagery_tasks.set_provider_factory(lambda: _FakeProvider((SCENE,)))
    monkeypatch.setattr(imagery_tasks.acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        result = await imagery_tasks._discover_farm_scenes_async(sub_id, env["schema"])
    finally:
        imagery_tasks.reset_provider_factory()

    assert result["queued"] == 1
    assert await _fetch_flag(admin_session, env["schema"], sub_id) is True
