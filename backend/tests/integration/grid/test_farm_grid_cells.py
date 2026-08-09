"""The farm-wide grid read, and the cell-list defect it was built beside.

Two things are guarded here.

**The N+1.** The map overlay draws every gridded block in a farm. It used
to get there with one ``/blocks/{id}/grid-cells`` per block — 36 requests
on the reference farm, each re-paying JWT verification, a connection out
of a 15-slot pool, a block lookup and two hypertable queries. The farm
route answers the whole overlay in one statement, so the test that matters
is not "is it fast" but **"does it return exactly what the fan-out
returned"** — a faster query that quietly drops a block or shifts a scene
time would be worse than the latency.

**The ``at IS NULL`` fan-out.** ``list_cells_with_values`` used to spell
its scene-time filter ``(:at IS NULL OR obs.time = :at)``. When ``at`` is
NULL that disjunct is TRUE for every row, so the LEFT JOIN matched the
cell's entire observation history and emitted one row per (cell, scene)
instead of one row per cell. ``at`` is NULL exactly when no *governed*
observation exists — which is the state a block is left in between a
rezone backfill and the settle sweep that widens the new config's valid
range. So the duplication is reachable, and it lands on the map as
repeated features carrying values from arbitrary past scenes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.grid.repository import GridRepository
from app.modules.grid.service import get_grid_service
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM_BOUNDARY = "POLYGON((31.20 30.00,31.30 30.00,31.30 30.10,31.20 30.10,31.20 30.00))"
# Three disjoint blocks, each big enough to hold several 40 m cells.
_BLOCK_BOUNDARIES = (
    "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))",
    "POLYGON((31.211 30.001,31.219 30.001,31.219 30.009,31.211 30.009,31.211 30.001))",
    "POLYGON((31.221 30.001,31.229 30.001,31.229 30.009,31.221 30.009,31.221 30.001))",
)


@pytest.fixture
async def gridded_farm(admin_session: Any) -> dict[str, Any]:
    """A farm with three gridded blocks.

    Deliberately uneven, because that is where a set-based rewrite breaks:
    block 0 has two scenes (so "latest" has to pick), block 1 has one, and
    block 2 has a grid but **no observations at all** — it must still come
    back with its cells so the overlay can draw it as "no data".
    """
    slug = f"farmgrid-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id = uuid4()
    block_ids = [uuid4() for _ in _BLOCK_BOUNDARIES]
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'FG', 'FG', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM_BOUNDARY},
    )
    for i, (bid, boundary) in enumerate(zip(block_ids, _BLOCK_BOUNDARIES, strict=True)):
        await admin_session.execute(
            text(
                "INSERT INTO blocks (id, farm_id, code, name, boundary) "
                "VALUES (:id, :fid, :code, :code, ST_GeomFromText(:b, 4326))"
            ),
            {"id": str(bid), "fid": str(farm_id), "code": f"FB{i}", "b": boundary},
        )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    service = get_grid_service(tenant_session=admin_session)
    for bid in block_ids:
        await service.upsert_config(
            block_id=bid, product_id=product_id, cell_size_m=Decimal("40"), created_by=None
        )
    await admin_session.commit()

    now = datetime.now(UTC)
    scenes = {
        block_ids[0]: [now - timedelta(days=14), now - timedelta(days=3)],
        block_ids[1]: [now - timedelta(days=9)],
        block_ids[2]: [],
    }
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    for bid, times in scenes.items():
        cells = (
            await admin_session.execute(
                text(
                    "SELECT gc.id FROM grid_cells gc "
                    "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                    "WHERE cfg.block_id = :b AND cfg.retired_at IS NULL"
                ),
                {"b": str(bid)},
            )
        ).all()
        assert cells, "every block must produce a non-empty grid"
        for t in times:
            for i, (cell_id,) in enumerate(cells):
                await admin_session.execute(
                    text(
                        "INSERT INTO block_grid_aggregates "
                        "(time, cell_id, block_id, index_code, product_id, mean, "
                        " valid_pixel_count, total_pixel_count, stac_item_id) "
                        "VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, :s)"
                    ),
                    {
                        "t": t,
                        "c": str(cell_id),
                        "b": str(bid),
                        "p": str(product_id),
                        "m": Decimal("0.40") + Decimal(i % 10) / 100,
                        "s": f"scene-{t.date()}",
                    },
                )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    return {
        "schema": schema,
        "farm_id": farm_id,
        "block_ids": block_ids,
        "product_id": product_id,
        "scenes": scenes,
    }


async def test_farm_read_matches_the_per_block_fan_out(
    admin_session: Any, gridded_farm: dict[str, Any]
) -> None:
    """The one-request read must equal the per-block reads it replaces.

    Compared cell-by-cell rather than by count: a set-based rewrite that
    joined the wrong scene time would keep the row count identical and
    silently repaint the whole map.
    """
    env = gridded_farm
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)

    farm = await service.get_farm_cells_with_values(farm_id=env["farm_id"], index_code="ndvi")
    assert {b.block_id for b in farm.blocks} == set(
        env["block_ids"]
    ), "every gridded block must appear, including the one with no observations"

    for block in farm.blocks:
        per_block = await service.get_cells_with_values(
            block_id=block.block_id,
            product_id=env["product_id"],
            index_code="ndvi",
            at=None,
        )
        assert block.at == per_block.at, f"scene time diverged for {block.block_id}"
        assert [c.cell_id for c in block.cells] == [c.cell_id for c in per_block.cells]
        assert [c.mean for c in block.cells] == [c.mean for c in per_block.cells]
        assert [c.time for c in block.cells] == [c.time for c in per_block.cells]
        assert [c.geometry for c in block.cells] == [c.geometry for c in per_block.cells]


async def test_farm_read_picks_the_latest_scene_per_block(
    admin_session: Any, gridded_farm: dict[str, Any]
) -> None:
    """Each block resolves its *own* latest scene, not the farm's.

    The blocks were seeded with different histories precisely so a query
    that resolved one scene time for the whole farm would fail here.
    """
    env = gridded_farm
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    service = get_grid_service(tenant_session=admin_session)

    farm = await service.get_farm_cells_with_values(farm_id=env["farm_id"], index_code="ndvi")
    by_block = {b.block_id: b for b in farm.blocks}

    for bid, times in env["scenes"].items():
        block = by_block[bid]
        if not times:
            assert block.at is None, "a block with no scenes has no scene time"
            assert block.cells, "it still returns cells, so the map draws 'no data' tiles"
            assert all(c.mean is None for c in block.cells)
        else:
            assert block.at == max(times)
            assert all(c.time == max(times) for c in block.cells if c.time is not None)
            assert any(c.mean is not None for c in block.cells)


async def test_valueless_read_returns_one_row_per_cell(
    admin_session: Any, gridded_farm: dict[str, Any]
) -> None:
    """``at=None`` must not fan the join out across the whole history.

    Simulates the post-rezone-backfill state directly: observations exist
    on the live config's own cells, but the config's valid range opens
    after them, so none is governed and ``get_latest_scene_time`` returns
    NULL. Under the old ``(:at IS NULL OR obs.time = :at)`` spelling the
    LEFT JOIN then matched every one of those rows.
    """
    env = gridded_farm
    block_id: UUID = env["block_ids"][0]
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))

    # Open the live config's valid range *after* every existing scene —
    # what a rezone does, minus the geometry churn.
    await admin_session.execute(
        text(
            "UPDATE grid_configs SET effective_from = now() "
            "WHERE block_id = :b AND retired_at IS NULL"
        ),
        {"b": str(block_id)},
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))

    repo = GridRepository(admin_session)
    latest = await repo.get_latest_scene_time(
        block_id=block_id, product_id=env["product_id"], index_code="ndvi"
    )
    assert latest is None, "no observation is governed once the range opens after them"

    n_cells = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM grid_cells gc "
                "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                "WHERE cfg.block_id = :b AND cfg.retired_at IS NULL"
            ),
            {"b": str(block_id)},
        )
    ).scalar_one()
    n_scenes = len(env["scenes"][block_id])
    assert n_scenes > 1, "the fixture needs multiple scenes for duplication to be visible"

    rows = await repo.list_cells_with_values(
        block_id=block_id, product_id=env["product_id"], index_code="ndvi", at=None
    )
    assert len(rows) == n_cells, (
        f"expected one row per cell, got {len(rows)} for {n_cells} cells "
        f"({n_scenes} scenes in history) — the join fanned out across history"
    )
    assert len({r["cell_id"] for r in rows}) == len(rows), "cell ids must be unique"
    assert all(
        r["mean"] is None and r["time"] is None for r in rows
    ), "with no scene resolved there is no value to report"
