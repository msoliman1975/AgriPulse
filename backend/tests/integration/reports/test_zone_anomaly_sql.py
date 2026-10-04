"""The zone-anomaly report's SQL against a real database.

Rewritten on 2026-10-04 after one call ran 10 to 18 minutes on a farm with
two years of history and starved the api pod's connection pool. The
rewrite finds the latest in-window scene first and reads only its cells.
These tests pin what the report returns, so the faster form cannot
quietly answer a different question.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.grid.service import get_grid_service
from app.modules.reports.service import _select_zone_anomaly_stats
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.30 30.00,31.30 30.10,31.20 30.10,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"

OLD = datetime(2025, 5, 1, 8, 30, tzinfo=UTC)
LATEST = datetime(2025, 6, 1, 8, 30, tzinfo=UTC)
AFTER = datetime(2025, 8, 1, 8, 30, tzinfo=UTC)


@pytest.fixture
async def farm(admin_session: Any) -> dict[str, Any]:
    slug = f"zone-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    schema = tenant.schema_name
    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'Z', 'Z', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :f, 'B1', 'B1', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(block_id), "f": str(farm_id), "b": _BLOCK},
    )
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'")
        )
    ).scalar_one()
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await get_grid_service(tenant_session=admin_session).upsert_config(
        block_id=block_id, product_id=product_id, cell_size_m=Decimal("40"), created_by=None
    )
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    # Backdate the grid so the seeded scenes fall inside its valid time.
    await admin_session.execute(
        text("UPDATE grid_configs SET effective_from = :t WHERE block_id = :b"),
        {"t": datetime(2025, 1, 1, tzinfo=UTC), "b": str(block_id)},
    )
    cells = [
        r[0]
        for r in (
            await admin_session.execute(
                text(
                    "SELECT gc.id FROM grid_cells gc "
                    "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                    "WHERE cfg.block_id = :b ORDER BY gc.row_idx, gc.col_idx"
                ),
                {"b": str(block_id)},
            )
        ).all()
    ]
    assert len(cells) >= 4
    for when in (OLD, LATEST, AFTER):
        for i, cell in enumerate(cells):
            mean = Decimal("0.40")
            # One clear low outlier on the latest in-window scene only. The
            # old scene's outlier is a different cell, and must not count.
            if when == LATEST and i == 0:
                mean = Decimal("0.05")
            if when == OLD and i == 1:
                mean = Decimal("0.05")
            await admin_session.execute(
                text(
                    "INSERT INTO block_grid_aggregates "
                    "(time, cell_id, block_id, index_code, product_id, mean, "
                    " valid_pixel_count, total_pixel_count, stac_item_id) "
                    "VALUES (:t, :c, :b, 'ndvi', :p, :m, 100, 100, 's')"
                ),
                {"t": when, "c": str(cell), "b": str(block_id), "p": str(product_id), "m": mean},
            )
    await admin_session.commit()
    return {"schema": schema, "farm_id": farm_id, "block_id": block_id, "cells": len(cells)}


@pytest.mark.asyncio
async def test_the_latest_scene_in_the_window_is_scored(
    admin_session: Any, farm: dict[str, Any]
) -> None:
    await admin_session.execute(text(f'SET search_path TO "{farm["schema"]}", public'))
    stats = await _select_zone_anomaly_stats(
        admin_session,
        farm_id=farm["farm_id"],
        index_code="ndvi",
        since=datetime(2025, 4, 1, tzinfo=UTC),
        until=datetime(2025, 6, 30, tzinfo=UTC),
    )

    row = stats[farm["block_id"]]
    # The August scene is after the window and must not be picked.
    assert row["scene_time"] == LATEST
    assert row["cell_count"] == farm["cells"]
    assert row["flagged"] == 1
    assert row["worst_z"] < 0


@pytest.mark.asyncio
async def test_a_window_with_no_scene_returns_nothing(
    admin_session: Any, farm: dict[str, Any]
) -> None:
    await admin_session.execute(text(f'SET search_path TO "{farm["schema"]}", public'))
    stats = await _select_zone_anomaly_stats(
        admin_session,
        farm_id=farm["farm_id"],
        index_code="ndvi",
        since=datetime(2024, 1, 1, tzinfo=UTC),
        until=datetime(2024, 12, 31, tzinfo=UTC),
    )
    assert stats == {}
