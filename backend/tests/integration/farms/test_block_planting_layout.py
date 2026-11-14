"""A block's planting layout round-trips and its densities are derived (D23).

Tenant 0106 added row spacing, in-row spacing and plant count. As with the
Arabic names, three things can break independently: the create body reaching
the INSERT, the read projection returning the columns, and the PATCH allowlist
accepting them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from .test_arabic_names import _tenant_app
from .test_farms_crud import _square

pytestmark = [pytest.mark.integration]

_BLOCK = {
    "type": "Polygon",
    "coordinates": [[[31.2, 30.0], [31.201, 30.0], [31.201, 30.001], [31.2, 30.001], [31.2, 30.0]]],
}


@pytest.mark.asyncio
async def test_planting_layout_round_trips(admin_session: AsyncSession) -> None:
    app = await _tenant_app(admin_session, "planting-layout")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "FARM-PL", "name": "Layout", "boundary": _square(31.2, 30.0)},
        )
        assert resp.status_code == 201, resp.text
        farm_id = resp.json()["id"]

        # Created with the manual's 10 x 8 m Medjool layout.
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B-1",
                "boundary": _BLOCK,
                "row_spacing_m": "10",
                "in_row_spacing_m": "8",
                "plant_count": 100,
            },
        )
        assert resp.status_code == 201, resp.text
        block = resp.json()
        block_id = block["id"]
        assert Decimal(block["row_spacing_m"]) == Decimal("10")
        assert Decimal(block["in_row_spacing_m"]) == Decimal("8")
        assert block["plant_count"] == 100
        assert Decimal(block["plants_per_ha_from_spacing"]) == Decimal("125.0")
        area_m2 = Decimal(block["area_m2"])
        expected = (Decimal(100) * 10000 / area_m2).quantize(Decimal("0.1"))
        assert Decimal(block["plants_per_ha_from_count"]) == expected

        # The list projection selects its own columns.
        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks")
        assert resp.status_code == 200, resp.text
        row = {r["id"]: r for r in resp.json()["items"]}[block_id]
        assert row["plant_count"] == 100

        # PATCH changes the layout; a partial edit keeps the rest.
        resp = await c.patch(
            f"/api/v1/blocks/{block_id}", json={"row_spacing_m": "9", "in_row_spacing_m": "9"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Decimal(body["plants_per_ha_from_spacing"]) == Decimal("123.5")
        assert body["plant_count"] == 100

        # Clearing a spacing clears the derived density with it.
        resp = await c.patch(f"/api/v1/blocks/{block_id}", json={"in_row_spacing_m": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["plants_per_ha_from_spacing"] is None


@pytest.mark.asyncio
async def test_planting_layout_rejects_non_positive_spacing(admin_session: AsyncSession) -> None:
    app = await _tenant_app(admin_session, "planting-layout-bad")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "FARM-PB", "name": "Layout", "boundary": _square(31.3, 30.1)},
        )
        farm_id = resp.json()["id"]
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-1", "boundary": _BLOCK, "row_spacing_m": "0"},
        )
        assert resp.status_code == 422, resp.text
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-2", "boundary": _BLOCK, "plant_count": -1},
        )
        assert resp.status_code == 422, resp.text
