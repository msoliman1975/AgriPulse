"""Rezoning a block must not make its observation history unreadable.

`grid_configs` records `retired_at` — *when an operator changed their mind* —
and every config-joined read path filters `retired_at IS NULL`. That conflates
transaction time with valid time: the moment a block is rezoned, the previous
geometry's aggregates stop being reachable by anything, even though the rows
are still physically present (and still being paid for).

Two read paths make it worse by not joining `grid_configs` at all:
`get_latest_scene_time` and `list_observed_indices` read
`block_grid_aggregates` raw, so they *do* see the orphaned rows. The two
groups therefore disagree immediately after a rezone:

1. `get_latest_scene_time` reports the **old** grid's last scene time.
2. `get_cells_with_values` resolves `at` to that time and LEFT JOINs the
   **new** cells — every `mean` comes back NULL, so the heatmap renders
   entirely as "no data".
3. `detect_block_anomalies` resolves the same `at`, then `list_cell_means`
   INNER JOINs the new cells — 0 rows, so the detector's `min_cells` guard
   returns None and **anomaly detection goes silently dead for that block**
   until the next scene lands.

These tests are the §2.2 regression guard from
`docs/proposals/bulk-grid-config-and-valid-time.md`. They are expected to
FAIL on `main` — that is the point; they prove the defect before the
valid-time migration fixes it. If they pass unmodified on `main`, §2.2 is
wrong and the plan needs revisiting before any of it is built.
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

# A block big enough that both 20 m and 40 m grids produce several cells,
# and small enough to stay under the 5000-cell ceiling.
_FARM_BOUNDARY = (
    "POLYGON((31.20 30.00,31.24 30.00,31.24 30.04,31.20 30.04,31.20 30.00))"
)
_BLOCK_BOUNDARY = (
    "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"
)


@pytest.fixture
async def gridded_block(admin_session: Any) -> dict[str, Any]:
    """A tenant with one block gridded at 20 m, holding one scene of NDVI."""
    slug = f"gridvt-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'GV', 'GV', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM_BOUNDARY},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :fid, 'GB', 'GB', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id), "b": _BLOCK_BOUNDARY},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    service = get_grid_service(tenant_session=admin_session)
    await service.upsert_config(
        block_id=block_id,
        product_id=product_id,
        cell_size_m=Decimal("20"),
        created_by=None,
    )
    await admin_session.commit()

    # One scene of NDVI observations, written against the 20 m cells.
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    scene_time = datetime.now(UTC) - timedelta(days=7)
    cells = (
        await admin_session.execute(
            text(
                "SELECT gc.id FROM grid_cells gc "
                "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                "WHERE cfg.block_id = :b AND cfg.retired_at IS NULL"
            ).bindparams(),
            {"b": str(block_id)},
        )
    ).all()
    assert cells, "fixture must produce a non-empty 20 m grid"
    for i, (cell_id,) in enumerate(cells):
        await admin_session.execute(
            text(
                "INSERT INTO block_grid_aggregates "
                "(time, cell_id, block_id, index_code, product_id, mean, "
                " valid_pixel_count, total_pixel_count, stac_item_id) "
                "VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, 'scene-old')"
            ),
            {
                "t": scene_time,
                "c": str(cell_id),
                "b": str(block_id),
                "p": str(product_id),
                "m": Decimal("0.50") + Decimal(i % 10) / 100,
            },
        )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    return {
        "schema": schema,
        "block_id": block_id,
        "product_id": product_id,
        "scene_time": scene_time,
        "cell_count": len(cells),
    }


async def _rezone(session: Any, env: dict[str, Any], cell_size: str) -> None:
    await session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    service = get_grid_service(tenant_session=session)
    await service.upsert_config(
        block_id=env["block_id"],
        product_id=env["product_id"],
        cell_size_m=Decimal(cell_size),
        created_by=None,
    )
    await session.commit()


async def test_history_stays_readable_after_rezone(
    admin_session: Any, gridded_block: dict[str, Any]
) -> None:
    """The core §2.2 guard: rezone, then read the pre-rezone scene.

    The scene predates the new geometry, so it must still be served from the
    geometry that actually produced it. On `main` the config-joined read
    returns the NEW cells with every value NULL, which is what renders the
    heatmap as an empty block.
    """
    env = gridded_block
    await _rezone(admin_session, env, "40")

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    repo = GridRepository(admin_session)

    latest = await repo.get_latest_scene_time(
        block_id=env["block_id"], product_id=env["product_id"], index_code="ndvi"
    )
    assert latest is not None, "the scene is still in block_grid_aggregates"

    rows = await repo.list_cells_with_values(
        block_id=env["block_id"],
        product_id=env["product_id"],
        index_code="ndvi",
        at=latest,
    )
    assert rows, "a resolved scene time must return cells"
    with_values = [r for r in rows if r["mean"] is not None]
    assert with_values, (
        "every cell came back NULL — the scene time resolved against the "
        "retired grid's rows while the cells came from the new grid. "
        "This is the all-'no data' heatmap."
    )


async def test_anomaly_detection_survives_rezone(
    admin_session: Any, gridded_block: dict[str, Any]
) -> None:
    """`list_cell_means` feeds the sweep; 0 rows means detection is dead.

    Unlike the heatmap path this INNER JOINs, so the failure is silent: the
    detector's `min_cells` guard just returns None and the block stops
    producing anomalies with no error anywhere.
    """
    env = gridded_block
    await _rezone(admin_session, env, "40")

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    repo = GridRepository(admin_session)

    latest = await repo.get_latest_scene_time(
        block_id=env["block_id"], product_id=env["product_id"], index_code="ndvi"
    )
    assert latest is not None

    means = await repo.list_cell_means(
        block_id=env["block_id"],
        product_id=env["product_id"],
        index_code="ndvi",
        at=latest,
    )
    assert means, (
        "0 cells with means at the latest scene time — the anomaly sweep "
        "would silently stop flagging this block"
    )


async def test_scene_time_and_observed_indices_agree_with_cell_reads(
    admin_session: Any, gridded_block: dict[str, Any]
) -> None:
    """The two un-joined read paths must not disagree with the joined ones.

    `get_latest_scene_time` and `list_observed_indices` read
    `block_grid_aggregates` without joining `grid_configs`. Either they see
    the same history the cell reads can serve, or they hand downstream code a
    scene time / index code that resolves to nothing.
    """
    env = gridded_block
    await _rezone(admin_session, env, "40")

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    repo = GridRepository(admin_session)

    observed = await repo.list_observed_indices(
        block_id=env["block_id"], product_id=env["product_id"]
    )
    for code in observed:
        latest = await repo.get_latest_scene_time(
            block_id=env["block_id"], product_id=env["product_id"], index_code=code
        )
        assert latest is not None
        rows = await repo.list_cell_means(
            block_id=env["block_id"],
            product_id=env["product_id"],
            index_code=code,
            at=latest,
        )
        assert rows, (
            f"{code!r} is reported as observed and resolves to a scene time, "
            "but no cell means can be read at it"
        )


async def test_new_scenes_land_on_the_new_geometry(
    admin_session: Any, gridded_block: dict[str, Any]
) -> None:
    """The other half of the contract — post-rezone scenes use the new grid.

    This one passes on `main`; it is here so the fix can't be implemented by
    simply reverting to "always read the newest geometry", which would break
    it in the opposite direction.
    """
    env = gridded_block
    await _rezone(admin_session, env, "40")

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    new_cells = (
        await admin_session.execute(
            text(
                "SELECT gc.id FROM grid_cells gc "
                "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                "WHERE cfg.block_id = :b AND cfg.retired_at IS NULL"
            ),
            {"b": str(env["block_id"])},
        )
    ).all()
    assert new_cells

    new_scene = datetime.now(UTC)
    for i, (cell_id,) in enumerate(new_cells):
        await admin_session.execute(
            text(
                "INSERT INTO block_grid_aggregates "
                "(time, cell_id, block_id, index_code, product_id, mean, "
                " valid_pixel_count, total_pixel_count, stac_item_id) "
                "VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, 'scene-new')"
            ),
            {
                "t": new_scene,
                "c": str(cell_id),
                "b": str(env["block_id"]),
                "p": str(env["product_id"]),
                "m": Decimal("0.60") + Decimal(i % 10) / 100,
            },
        )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    repo = GridRepository(admin_session)
    means = await repo.list_cell_means(
        block_id=env["block_id"],
        product_id=env["product_id"],
        index_code="ndvi",
        at=new_scene,
    )
    assert len(means) == len(new_cells)


async def test_rezone_does_not_silently_drop_the_old_cells(
    admin_session: Any, gridded_block: dict[str, Any]
) -> None:
    """The old geometry's rows survive the rezone — they are orphaned, not deleted.

    This documents *why* the fix is a read-path change rather than a data
    migration: nothing is lost, it has just become unreachable.
    """
    env = gridded_block
    before = env["cell_count"]
    await _rezone(admin_session, env, "40")

    await admin_session.execute(text(f'SET search_path TO "{env["schema"]}", public'))
    still_there = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM block_grid_aggregates "
                "WHERE block_id = :b AND index_code = 'ndvi' AND time = :t"
            ),
            {"b": str(env["block_id"]), "t": env["scene_time"]},
        )
    ).scalar_one()
    assert still_there == before
