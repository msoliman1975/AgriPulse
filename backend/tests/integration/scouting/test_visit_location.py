"""The position a visit carries, and which of the three sources answered.

The field app turns this into walking directions. That makes the ordering a
correctness question rather than a presentation one: a cell-scoped visit routed
to the middle of its block sends a scout to the wrong corner of a field with no
error anywhere, and the pin looks exactly as confident either way.

`pin_point` is covered by the lifecycle tests. These cover the half that was
missing: the centre of the named grid cell, and the null that tells the app to
disable the control.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.scouting.conftest import ScoutingFixture, build_app

pytestmark = [pytest.mark.integration]


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _make_cell(
    session: AsyncSession, *, schema: str, block_id: str, lon: float, lat: float
) -> str:
    """One grid cell at a known centre, inserted straight into the tenant schema.

    The grid API builds cells from a block boundary and a cell size, which
    would put the centre wherever the maths lands. This test is about the
    centre reaching the client unchanged, so the row is written by hand and the
    expected coordinates are the ones that went in.
    """
    # `SET`, not `SET LOCAL`, and a commit at the end — the API runs on its own
    # connection and cannot see an uncommitted row. Same shape as the source-
    # counter tests, for the same reason.
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    config_id = uuid4()
    cell_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO grid_configs (id, block_id, product_id, cell_size_m, utm_srid) "
            "VALUES (:id, :block_id, :product_id, 20, 32636)"
        ),
        {"id": config_id, "block_id": UUID(block_id), "product_id": uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO grid_cells (id, grid_config_id, row_idx, col_idx, geom, centroid, area_m2) "
            "VALUES (:id, :config_id, 0, 0, "
            # A degenerate square around the centre: the polygon is never read
            # by anything under test, but the column is NOT NULL.
            "  ST_SetSRID(ST_MakeEnvelope(:lon - 0.001, :lat - 0.001, :lon + 0.001, :lat + 0.001), 4326), "
            "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 400)"
        ),
        {"id": cell_id, "config_id": config_id, "lon": lon, "lat": lat},
    )
    await session.commit()
    return str(cell_id)


async def _dispatch(env: ScoutingFixture, **overrides) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "block_id": env.block_id,
        "instruction": "Walk the patchy corner.",
        "due_within_hours": 48,
        "severity": "warning",
        **overrides,
    }
    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            f"/api/v1/scouting/visits:dispatch?farm_id={env.farm_id}", json=body
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_cell_scoped_visit_carries_the_cell_centre(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    cell_id = await _make_cell(
        admin_session, schema=env.schema, block_id=env.block_id, lon=31.6125, lat=30.6075
    )

    visit = await _dispatch(env, cell_id=cell_id)
    assert visit["cell_id"] == cell_id
    # GeoJSON, so longitude first. The app reads this pair through one helper
    # for exactly this reason.
    assert visit["cell_point"]["type"] == "Point"
    assert visit["cell_point"]["coordinates"] == [31.6125, 30.6075]

    # And the scout — the persona that actually reads it — sees the same thing
    # on both the read paths the app uses. The list is the one that matters:
    # it is a different SQL statement from the get, and only a shared column
    # list keeps them in step.
    async with _client(env.scout_context) as scout:
        got = await scout.get(f"/api/v1/scouting/visits/{visit['id']}?farm_id={env.farm_id}")
        assert got.status_code == 200, got.text
        assert got.json()["cell_point"]["coordinates"] == [31.6125, 30.6075]

        listed = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}&claimable=true")
        assert listed.status_code == 200, listed.text
        rows = {v["id"]: v for v in listed.json()}
        assert rows[visit["id"]]["cell_point"]["coordinates"] == [31.6125, 30.6075]


@pytest.mark.asyncio
async def test_block_scoped_visit_has_no_cell_point(scouting_env: ScoutingFixture) -> None:
    """No cell named, no cell centre — and the join must not drop the row.

    An INNER JOIN here would have made every block-scoped visit — which is most
    of them — vanish from the list entirely.
    """
    env = scouting_env
    visit = await _dispatch(env)

    assert visit["cell_id"] is None
    assert visit["cell_point"] is None

    async with _client(env.scout_context) as scout:
        listed = await scout.get(f"/api/v1/scouting/visits?farm_id={env.farm_id}&claimable=true")
        assert listed.status_code == 200, listed.text
        assert [v["id"] for v in listed.json()] == [visit["id"]]
