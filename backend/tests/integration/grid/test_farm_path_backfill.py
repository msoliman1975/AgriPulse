"""A grid backfill must see a farm whose scenes are farm-wide.

The failure this pins, observed in production on 2026-08-27. A 36-block
farm was gridded. The apply fired ``grid.backfill_farm``. Every query the
backfill runs read ``imagery_ingestion_jobs``, which is keyed per block,
and that farm had been cut over to the farm-wide imagery path: 303
succeeded scenes in ``imagery_farm_ingestion_jobs`` and zero in the block
table. So the backfill enumerated nothing, logged ``scenes_queued=0``, and
returned success. Every grid cell stayed empty and the cell popup printed
"—" for every number, with no error anywhere in the stack.

The tests below are written against a farm that has ONLY farm-level
scenes, because that is the shape every count in this area was blind to.
A farm with block scenes is the case the existing suite already covers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.grid import tasks as grid_tasks
from app.modules.grid.backfill import (
    count_farm_backfill_candidates,
    count_farm_scene_candidates,
    count_unreplayable_scenes,
    list_backfill_jobs,
    list_farm_scene_backfill_jobs,
)
from app.modules.grid.service import get_grid_service
from app.modules.imagery import tasks as imagery_tasks
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
_BLOCK_A = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"
_BLOCK_B = "POLYGON((31.211 30.001,31.219 30.001,31.219 30.009,31.211 30.009,31.211 30.001))"

# The manifest shape every farm job in production carries. Checked on the
# live farm: all 303 succeeded rows are this list form and all 303 name a
# raw-bands object.
_ASSETS = ["s3://b/scene/ndvi.tif", "s3://b/scene/raw_bands.tif"]


@pytest.fixture
async def cutover_farm(admin_session: Any) -> dict[str, Any]:
    """A farm on the farm-wide imagery path, gridded, with no block jobs.

    Two blocks, because the farm-scene count must not multiply by them:
    one farm scene is replayed once and writes cells for every block, so
    counting it per block would report twice the work that will run.
    """
    slug = f"cut-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_a, block_b, sub_id = uuid4(), uuid4(), uuid4(), uuid4()
    product_id = UUID(
        str(
            (
                await admin_session.execute(
                    text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
                )
            ).scalar_one()
        )
    )

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'CUT', 'Cutover farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    for block_id, code, wkt in ((block_a, "BA", _BLOCK_A), (block_b, "BB", _BLOCK_B)):
        await admin_session.execute(
            text(
                "INSERT INTO blocks (id, farm_id, code, name, boundary) "
                "VALUES (:id, :farm, :code, :code, ST_GeomFromText(:wkt, 4326))"
            ),
            {"id": str(block_id), "farm": str(farm_id), "code": code, "wkt": wkt},
        )
        # Inserted raw, so no cells are materialised. These tests are about
        # the scene side of the count; whether geometry exists is a
        # different question with its own tests.
        await admin_session.execute(
            text(
                "INSERT INTO grid_configs (id, block_id, product_id, cell_size_m, utm_srid) "
                "VALUES (:id, :block, :product, 30, 32636)"
            ),
            {"id": str(uuid4()), "block": str(block_id), "product": str(product_id)},
        )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions "
            "  (id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": str(sub_id), "farm": str(farm_id), "product": str(product_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_a": block_a,
        "block_b": block_b,
        "product_id": product_id,
        "subscription_id": sub_id,
    }


async def _add_farm_scene(
    session: Any,
    env: dict[str, Any],
    *,
    assets: Any = _ASSETS,
    status: str = "succeeded",
    stac_item_id: str | None = "item",
    scene_datetime: datetime | None = None,
) -> UUID:
    job_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO imagery_farm_ingestion_jobs "
            "  (id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            "   status, stac_item_id, assets_written) "
            "VALUES (:id, :sub, :farm, :product, :scene, :dt, :st, :item, "
            "        CAST(:assets AS jsonb))"
        ),
        {
            "id": str(job_id),
            "sub": str(env["subscription_id"]),
            "farm": str(env["farm_id"]),
            "product": str(env["product_id"]),
            "scene": f"scene-{uuid4().hex[:8]}",
            "dt": scene_datetime or datetime.now(UTC),
            "st": status,
            "item": stac_item_id,
            "assets": None if assets is None else json.dumps(assets),
        },
    )
    return job_id


async def _seed(session: Any, env: dict[str, Any], count: int) -> None:
    """Insert ``count`` farm scenes, leaving the session on the schema.

    The search_path is set here and re-set after the commit. A commit ends
    the transaction the `SET` was scoped to, so the next statement runs
    against whatever schema the session had before — the failure mode this
    repo has hit repeatedly, and one that shows up as "relation does not
    exist" or, worse, as an empty result with no error at all.
    """
    await _use_schema(session, env)
    base = datetime.now(UTC)
    for i in range(count):
        await _add_farm_scene(session, env, scene_datetime=base - timedelta(days=i))
    await session.commit()
    await _use_schema(session, env)


async def _use_schema(session: Any, env: dict[str, Any]) -> None:
    await session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    # Asserted rather than assumed: a wrong search_path reads as missing
    # data, and a test that cannot see its own rows is worse than one that
    # fails outright.
    assert (await session.execute(text("SELECT current_schema()"))).scalar_one() == env["schema"]


@pytest.mark.asyncio
async def test_the_counts_see_farm_scenes_at_all(
    admin_session: Any, cutover_farm: dict[str, Any]
) -> None:
    """The shipped bug, stated as directly as it can be.

    Every number here was 0 before, for a farm holding five replayable
    scenes. The block-path enumeration is asserted empty in the same test,
    so the reading cannot be "the block query started matching".
    """
    await _seed(admin_session, cutover_farm, 5)
    await _use_schema(admin_session, cutover_farm)

    farm_jobs = await list_farm_scene_backfill_jobs(
        admin_session,
        farm_id=cutover_farm["farm_id"],
        product_id=cutover_farm["product_id"],
        since=None,
        limit=1000,
    )
    assert len(farm_jobs) == 5
    # The dispatcher keys on this, so a wrong value sends a farm scene to
    # the block task and it fails on a key that was never stored.
    assert {j["kind"] for j in farm_jobs} == {"farm"}

    block_jobs = await list_backfill_jobs(
        admin_session,
        block_id=cutover_farm["block_a"],
        product_id=cutover_farm["product_id"],
        since=None,
        limit=1000,
    )
    assert block_jobs == []

    assert (
        await count_farm_scene_candidates(
            admin_session,
            farm_id=cutover_farm["farm_id"],
            since=None,
            per_product_cap=1000,
        )
        == 5
    )
    # Two blocks, five farm scenes. Ten would mean the farm half was
    # counted per (block, product) like the block half.
    assert (
        await count_farm_backfill_candidates(
            admin_session, farm_id=cutover_farm["farm_id"], since=None, per_pair_cap=1000
        )
        == 5
    )


@pytest.mark.asyncio
async def test_only_replayable_scenes_are_counted(
    admin_session: Any, cutover_farm: dict[str, Any]
) -> None:
    """A scene with no stored bands cannot be recomputed by any path.

    It must not inflate the queued estimate, and it must be reported on its
    own, or "queued 2 of 5" reads as a budget truncation.
    """
    await _seed(admin_session, cutover_farm, 2)
    await _add_farm_scene(admin_session, cutover_farm, assets=["s3://b/scene/ndvi.tif"])
    await _add_farm_scene(admin_session, cutover_farm, stac_item_id=None)
    await _add_farm_scene(admin_session, cutover_farm, assets=None)
    # A failed scene is not history that went missing, so it counts nowhere.
    await _add_farm_scene(admin_session, cutover_farm, status="failed")
    await admin_session.commit()
    await _use_schema(admin_session, cutover_farm)
    assert (
        await count_farm_backfill_candidates(
            admin_session, farm_id=cutover_farm["farm_id"], since=None, per_pair_cap=1000
        )
        == 2
    )
    assert (
        await count_unreplayable_scenes(admin_session, farm_id=cutover_farm["farm_id"], since=None)
        == 3
    )


@pytest.mark.asyncio
async def test_the_farm_task_dispatches_the_farm_recompute(
    admin_session: Any, cutover_farm: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatch itself, not just the count.

    A count that is right while the fan-out still enqueues nothing would
    look fixed from the API and change nothing on the map, so the task's
    own calls are what is asserted here.
    """
    await _seed(admin_session, cutover_farm, 4)

    farm_calls: list[tuple[Any, ...]] = []
    block_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        imagery_tasks.recompute_farm_scene_indices,
        "delay",
        lambda *a, **k: farm_calls.append(a),
    )
    monkeypatch.setattr(
        imagery_tasks.compute_indices, "delay", lambda *a, **k: block_calls.append(a)
    )

    result = await grid_tasks._backfill_farm_async(
        tenant_schema=cutover_farm["schema"],
        farm_id=str(cutover_farm["farm_id"]),
        budget_scenes=None,
        since_iso=None,
    )

    assert result["scenes_queued"] == 4, result
    assert result["farm_scenes_queued"] == 4, result
    assert len(farm_calls) == 4
    assert block_calls == []
    # Two arguments, in the order the task declares them. The block task
    # takes three, and the two are easy to transpose.
    assert all(len(a) == 2 and a[1] == cutover_farm["schema"] for a in farm_calls), farm_calls


@pytest.mark.asyncio
async def test_a_budget_still_bounds_the_farm_pool(
    admin_session: Any, cutover_farm: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Farm scenes join the existing budget rather than escaping it.

    They are heavy-worker work like any other scene, so a farm asked for
    two must not receive nine because they arrived through a new pool.
    """
    await _seed(admin_session, cutover_farm, 9)
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        imagery_tasks.recompute_farm_scene_indices, "delay", lambda *a, **k: calls.append(a)
    )
    monkeypatch.setattr(imagery_tasks.compute_indices, "delay", lambda *a, **k: None)

    result = await grid_tasks._backfill_farm_async(
        tenant_schema=cutover_farm["schema"],
        farm_id=str(cutover_farm["farm_id"]),
        budget_scenes=2,
        since_iso=None,
    )
    assert result["scenes_queued"] == 2, result
    assert result["scenes_stranded"] == 7, result
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_block_request_falls_back_to_the_farms_own_scenes(
    admin_session: Any, cutover_farm: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-block route has the same blindness and the same fallback.

    Note the widening: a farm scene is replayed for the whole farm, so a
    block-scoped request recomputes every block. There is no narrower unit,
    and the alternative was to queue nothing and report success.
    """
    await _seed(admin_session, cutover_farm, 3)

    await _use_schema(admin_session, cutover_farm)
    counted = await get_grid_service(tenant_session=admin_session).count_backfill_scenes(
        block_id=cutover_farm["block_a"],
        product_id=cutover_farm["product_id"],
        since=None,
        limit=1000,
    )
    assert counted == 3

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        imagery_tasks.recompute_farm_scene_indices, "delay", lambda *a, **k: calls.append(a)
    )
    result = await grid_tasks._backfill_block_async(
        cutover_farm["schema"],
        str(cutover_farm["block_a"]),
        str(cutover_farm["product_id"]),
        200,
        None,
    )
    # The number the route reports and the number the task queues are the
    # same number. They were both 0, together, which is why neither looked
    # wrong next to the other.
    assert result["scenes_queued"] == counted == 3, result
    assert len(calls) == 3
