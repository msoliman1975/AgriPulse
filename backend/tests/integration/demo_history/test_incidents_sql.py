"""Steered incidents against a real database.

The first cluster run of the Ewais Grove scenario failed on its first
statement: one date parameter was compared with the `time` column and
also used in day arithmetic, asyncpg typed it as a timestamp, and
`d - :start` became an interval that would not cast to numeric. The unit
tests could not see it, because they never send SQL. These tests do.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.demo_history.incidents import (
    Incident,
    Shift,
    already_applied,
    apply_incident,
    apply_scenario,
)
from app.modules.grid.service import get_grid_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.30 30.00,31.30 30.10,31.20 30.10,31.20 30.00))"
_BLOCK = "POLYGON((31.201 30.001,31.209 30.001,31.209 30.009,31.201 30.009,31.201 30.001))"

# Before the incident, on its ramp, at full strength, after it.
_DAYS = (date(2025, 7, 1), date(2025, 7, 7), date(2025, 7, 12), date(2025, 7, 25))
_INCIDENT = Incident(
    code="t_break",
    title="test break",
    blocks=("B01",),
    start=date(2025, 7, 5),
    full=date(2025, 7, 9),
    until=date(2025, 7, 15),
    gone=date(2025, 7, 20),
    shifts=(Shift("ndmi", -0.10), Shift("smi", 0.015, mode="set")),
)


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 8, 30, tzinfo=UTC)


@pytest.fixture
async def farm(admin_session: Any) -> dict[str, Any]:
    slug = f"incsql-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    schema = tenant.schema_name
    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'EWG-T', 'T', ST_GeomFromText(:b, 4326))"
        ),
        {"id": str(farm_id), "b": _FARM},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) "
            "VALUES (:id, :f, 'B01', 'B01', ST_GeomFromText(:b, 4326))"
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
    cells = [
        r[0]
        for r in (
            await admin_session.execute(
                text(
                    "SELECT gc.id FROM grid_cells gc "
                    "JOIN grid_configs cfg ON cfg.id = gc.grid_config_id "
                    "WHERE cfg.block_id = :b AND cfg.retired_at IS NULL"
                ),
                {"b": str(block_id)},
            )
        ).all()
    ]
    assert cells
    for day in _DAYS:
        for cell in cells:
            await admin_session.execute(
                text(
                    "INSERT INTO block_grid_aggregates "
                    "(time, cell_id, block_id, index_code, product_id, mean, min, max, "
                    " valid_pixel_count, total_pixel_count, stac_item_id) "
                    "VALUES (:t, :c, :b, 'ndmi', :p, -0.05, -0.08, -0.02, 100, 100, 's')"
                ),
                {"t": _at(day), "c": str(cell), "b": str(block_id), "p": str(product_id)},
            )
        for code, mean in (("ndmi", "-0.05"), ("smi", "0.30")):
            await admin_session.execute(
                text(
                    "INSERT INTO block_index_aggregates "
                    "(time, block_id, index_code, product_id, mean, min, max, p10, p50, p90, "
                    " valid_pixel_count, total_pixel_count, stac_item_id) "
                    "VALUES (:t, :b, :code, :p, :m, :m, :m, :m, :m, :m, 100, 100, 's')"
                ),
                {
                    "t": _at(day),
                    "b": str(block_id),
                    "code": code,
                    "p": str(product_id),
                    "m": Decimal(mean),
                },
            )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"schema": schema, "farm_id": farm_id, "block_id": block_id, "cells": cells}


async def _block_mean(schema: str, block_id: UUID, code: str, day: date) -> float:
    async with AsyncSessionLocal()() as s, s.begin():
        v = (
            await s.execute(
                text(
                    f'SELECT mean FROM "{schema}".block_index_aggregates '
                    "WHERE block_id = :b AND index_code = :c AND time = :t"
                ),
                {"b": str(block_id), "c": code, "t": _at(day)},
            )
        ).scalar_one()
    return float(v)


async def _cell_means(schema: str, block_id: UUID, day: date) -> set[float]:
    async with AsyncSessionLocal()() as s, s.begin():
        rows = await s.execute(
            text(
                f'SELECT DISTINCT mean FROM "{schema}".block_grid_aggregates '
                "WHERE block_id = :b AND index_code = 'ndmi' AND time = :t"
            ),
            {"b": str(block_id), "t": _at(day)},
        )
    return {float(r[0]) for r in rows}


@pytest.mark.asyncio
async def test_an_incident_moves_rows_by_its_ramp(farm: dict[str, Any]) -> None:
    schema, block_id = farm["schema"], farm["block_id"]
    async with AsyncSessionLocal()() as session:
        await session.begin()
        await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        counts = await apply_incident(session, farm["farm_id"], _INCIDENT)
        await session.commit()

    # 2 of the 4 days are inside the span, for every cell and both indices.
    assert counts["cell_rows"] == 2 * len(farm["cells"])
    assert counts["block_rows"] == 2 * 2

    # 2025-07-07 is two days into a four-day ramp: half strength.
    assert await _cell_means(schema, block_id, date(2025, 7, 7)) == {-0.10}
    assert await _block_mean(schema, block_id, "ndmi", date(2025, 7, 7)) == pytest.approx(-0.10)
    assert await _block_mean(schema, block_id, "smi", date(2025, 7, 7)) == pytest.approx(
        0.30 + (0.015 - 0.30) * 0.5
    )
    # Full strength: added -0.10, set to 0.015.
    assert await _cell_means(schema, block_id, date(2025, 7, 12)) == {-0.15}
    assert await _block_mean(schema, block_id, "smi", date(2025, 7, 12)) == pytest.approx(0.015)
    # Outside the span nothing moves.
    for day in (date(2025, 7, 1), date(2025, 7, 25)):
        assert await _cell_means(schema, block_id, day) == {-0.05}
        assert await _block_mean(schema, block_id, "smi", day) == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_a_scenario_applies_once(farm: dict[str, Any]) -> None:
    class Scenario:
        FARM_CODE = "EWG-T"
        INCIDENTS = (_INCIDENT,)

    first = await apply_scenario(AsyncSessionLocal(), farm["schema"], Scenario)
    second = await apply_scenario(AsyncSessionLocal(), farm["schema"], Scenario)

    assert first[0]["skipped"] is False
    assert second == [{"code": "t_break", "skipped": True}]
    assert await _cell_means(farm["schema"], farm["block_id"], date(2025, 7, 12)) == {-0.15}
    async with AsyncSessionLocal()() as s, s.begin():
        await s.execute(text(f'SET LOCAL search_path TO "{farm["schema"]}", public'))
        assert await already_applied(s, farm["farm_id"]) == {"t_break"}


@pytest.mark.asyncio
async def test_a_dry_run_changes_nothing(farm: dict[str, Any]) -> None:
    class Scenario:
        FARM_CODE = "EWG-T"
        INCIDENTS = (_INCIDENT,)

    result = await apply_scenario(AsyncSessionLocal(), farm["schema"], Scenario, dry_run=True)

    assert result[0]["cell_rows"] == 2 * len(farm["cells"])
    assert await _cell_means(farm["schema"], farm["block_id"], date(2025, 7, 12)) == {-0.05}
    async with AsyncSessionLocal()() as s, s.begin():
        await s.execute(text(f'SET LOCAL search_path TO "{farm["schema"]}", public'))
        assert await already_applied(s, farm["farm_id"]) == set()
