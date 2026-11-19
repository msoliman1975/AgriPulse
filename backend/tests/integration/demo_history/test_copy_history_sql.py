"""Copying one farm's history onto a build farm, against a real database.

Two tenants, the same block on both: the source has a grid, a scene, index
rows per block and per cell, baselines and weather; the target has only the
block and its subscription. The copy must land every row on the target's
own block, cells and farm, and a second copy must add nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.demo_history.copy_history import CopySource, copy_history
from app.modules.grid.service import get_grid_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.30 30.00,31.30 30.10,31.20 30.10,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"
_OTHER = "POLYGON((31.211 30.011,31.219 30.011,31.219 30.019,31.211 30.019,31.211 30.011))"
_SCENE = datetime(2025, 7, 1, 8, 30, tzinfo=UTC)


async def _tenant(admin_session: Any, farm_code: str, blocks: dict[str, str]) -> dict[str, Any]:
    slug = f"copy-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    schema = tenant.schema_name
    farm_id = uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, :code, :code, ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "code": farm_code, "b": _FARM},
    )
    block_ids: dict[str, UUID] = {}
    for code, boundary in blocks.items():
        block_ids[code] = uuid4()
        await admin_session.execute(
            text(
                "INSERT INTO blocks (id, farm_id, code, name, boundary) "
                "VALUES (:id, :f, :code, :code, ST_GeomFromText(:b, 4326))"
            ),
            {"id": str(block_ids[code]), "f": str(farm_id), "code": code, "b": boundary},
        )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    for block_id in block_ids.values():
        await admin_session.execute(
            text("INSERT INTO imagery_aoi_subscriptions (block_id, product_id) VALUES (:b, :p)"),
            {"b": str(block_id), "p": str(product_id)},
        )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"schema": schema, "farm_id": farm_id, "blocks": block_ids, "product_id": product_id}


async def _seed_source(admin_session: Any, src: dict[str, Any]) -> list[UUID]:
    schema, product = src["schema"], src["product_id"]
    block = src["blocks"]["M1"]
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await get_grid_service(tenant_session=admin_session).upsert_config(
        block_id=block, product_id=product, cell_size_m=Decimal("40"), created_by=None
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    cells = [
        UUID(str(r[0]))
        for r in await admin_session.execute(
            text(
                "SELECT gc.id FROM grid_cells gc JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                "WHERE cfg.block_id = :b"
            ),
            {"b": str(block)},
        )
    ]
    sub = (
        await admin_session.execute(
            text("SELECT id FROM imagery_aoi_subscriptions WHERE block_id = :b"),
            {"b": str(block)},
        )
    ).scalar_one()
    await admin_session.execute(
        text(
            "INSERT INTO imagery_ingestion_jobs "
            "(subscription_id, block_id, product_id, scene_id, scene_datetime, status) "
            "VALUES (:s, :b, :p, 'S2A_TEST', :t, 'succeeded')"
        ),
        {"s": str(sub), "b": str(block), "p": str(product), "t": _SCENE},
    )
    for cell in cells:
        await admin_session.execute(
            text(
                "INSERT INTO block_grid_aggregates "
                "(time, cell_id, block_id, index_code, product_id, mean, min, max, std_dev, "
                " valid_pixel_count, total_pixel_count, stac_item_id) "
                "VALUES (:t, :c, :b, 'ndvi', :p, 0.09, 0.07, 0.11, 0.01, 16, 16, 's')"
            ),
            {"t": _SCENE, "c": str(cell), "b": str(block), "p": str(product)},
        )
    await admin_session.execute(
        text(
            "INSERT INTO block_index_aggregates "
            "(time, block_id, index_code, product_id, mean, min, max, p10, p50, p90, std_dev, "
            " valid_pixel_count, total_pixel_count, stac_item_id) "
            "VALUES (:t, :b, 'ndvi', :p, 0.09, 0.07, 0.11, 0.08, 0.09, 0.10, 0.01, 100, 100, 's')"
        ),
        {"t": _SCENE, "b": str(block), "p": str(product)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_index_baselines "
            "(block_id, index_code, day_of_year, baseline_mean, baseline_std, sample_count, "
            " years_observed) VALUES (:b, 'ndvi', 182, 0.09, 0.012, 9, 3)"
        ),
        {"b": str(block)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO weather_observations (time, farm_id, provider_code, air_temp_c) "
            "VALUES (:t, :f, 'open_meteo', 31.5)"
        ),
        {"t": _SCENE, "f": str(src["farm_id"])},
    )
    await admin_session.execute(
        text(
            "INSERT INTO weather_derived_daily (farm_id, date, temp_min_c, temp_max_c, temp_mean_c) "
            "VALUES (:f, :d, 22, 39, 30.5)"
        ),
        {"f": str(src["farm_id"]), "d": _SCENE.date()},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return cells


async def _count(schema: str, sql: str, **params: Any) -> int:
    async with AsyncSessionLocal()() as s, s.begin():
        return int((await s.execute(text(sql.replace("{s}", f'"{schema}"')), params)).scalar_one())


@pytest.mark.asyncio
async def test_history_lands_on_the_target_blocks_once(admin_session: Any) -> None:
    src = await _tenant(admin_session, "SRC", {"M1": _BLOCK, "O1": _OTHER})
    dst = await _tenant(admin_session, "DST", {"M1": _BLOCK})
    cells = await _seed_source(admin_session, src)
    source = CopySource(schema=src["schema"], farm_code="SRC", block_prefix="M")

    dry = await copy_history(
        AsyncSessionLocal(),
        source=source,
        target_schema=dst["schema"],
        target_farm_code="DST",
        dry_run=True,
    )
    assert dry["tables"]["block_grid_aggregates"] == len(cells)
    assert await _count(dst["schema"], "SELECT count(*) FROM {s}.grid_cells") == 0

    first = await copy_history(
        AsyncSessionLocal(), source=source, target_schema=dst["schema"], target_farm_code="DST"
    )
    assert first["blocks"] == ["M1"]
    assert first["tables"]["grid_configs"] == 1
    assert first["tables"]["grid_cells"] == len(cells)
    assert first["tables"]["block_grid_aggregates"] == len(cells)
    assert first["tables"]["block_index_aggregates"] == 1
    assert first["tables"]["block_index_baselines"] == 1
    assert first["tables"]["imagery_ingestion_jobs"] == 1
    assert first["tables"]["weather_observations"] == 1
    assert first["tables"]["weather_derived_daily"] == 1

    target_block = dst["blocks"]["M1"]
    # Every cell row points at the target's own block and cells.
    assert await _count(
        dst["schema"],
        "SELECT count(*) FROM {s}.block_grid_aggregates a "
        "JOIN {s}.grid_cells c ON c.id = a.cell_id "
        "JOIN {s}.grid_configs g ON g.id = c.grid_config_id AND g.block_id = a.block_id "
        "WHERE a.block_id = :b",
        b=str(target_block),
    ) == len(cells)
    assert (
        await _count(
            dst["schema"],
            "SELECT count(*) FROM {s}.imagery_ingestion_jobs j "
            "JOIN {s}.imagery_aoi_subscriptions s ON s.id = j.subscription_id AND s.block_id = j.block_id "
            "WHERE j.block_id = :b",
            b=str(target_block),
        )
        == 1
    )
    assert (
        await _count(
            dst["schema"],
            "SELECT count(*) FROM {s}.weather_observations WHERE farm_id = :f",
            f=str(dst["farm_id"]),
        )
        == 1
    )
    # Nobody from the source tenant is named on the copied grid.
    assert (
        await _count(
            dst["schema"], "SELECT count(*) FROM {s}.grid_configs WHERE created_by IS NOT NULL"
        )
        == 0
    )

    second = await copy_history(
        AsyncSessionLocal(), source=source, target_schema=dst["schema"], target_farm_code="DST"
    )
    assert set(second["tables"].values()) - {len(cells)} == {0}
    assert second["tables"]["cells_mapped"] == len(cells)
    assert second["tables"]["grid_configs"] == 0
    assert second["tables"]["block_grid_aggregates"] == 0
