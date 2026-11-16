"""Harvest records on Postgres (build plan 3.5): tenant 0111, the defaults,
the pick numbering, RBAC on the block's farm and the soft delete."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.harvest.router import router as harvest_router
from app.shared.auth.context import FarmRole, FarmScope
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.plans.test_board_endpoints import _bootstrap_two_blocks

pytestmark = [pytest.mark.integration]


def _client(context: Any) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(harvest_router)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _as(role: FarmRole, admin: Any, farm_id: str) -> Any:
    return make_context(
        user_id=uuid4(),
        tenant_id=admin.tenant_id,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=role),),
    )


@pytest.mark.asyncio
async def test_picks_take_their_defaults_and_number_themselves(
    admin_session: AsyncSession,
) -> None:
    admin, farm_id, block_id, other_block = await _bootstrap_two_blocks(
        admin_session, f"hv-{uuid4().hex[:6]}"
    )
    async with _client(admin) as c:
        crops = (await c.get("/api/v1/crops")).json()
        olive = next(x for x in crops if x["code"] == "olive")
        r = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={"crop_id": olive["id"], "season_label": "2026", "planting_date": "2018-02-01"},
        )
        assert r.status_code == 201, r.text
        assignment = r.json()["id"]

        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-01", "weight_kg": "1250.50", "price_per_kg": "12.5"},
        )
        assert r.status_code == 201, r.text
        first = r.json()
        assert first["pick_no"] == 1
        assert first["season_label"] == "2026"
        assert first["block_crop_id"] == assignment
        assert first["currency"] == "EGP"  # the tenant's default_currency
        assert first["farm_id"] == farm_id
        assert first["revenue"] == "15631.25"

        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-08", "weight_kg": "900", "label": "Second pick"},
        )
        assert r.status_code == 201, r.text
        second = r.json()
        assert second["pick_no"] == 2
        assert second["revenue"] is None

        # A pick number already used in the season.
        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-09", "weight_kg": "1", "pick_no": 1},
        )
        assert r.status_code == 409, r.text
        r = await c.patch(f"/api/v1/harvest-lots/{second['id']}", json={"pick_no": 1})
        assert r.status_code == 409, r.text
        # An assignment from another block.
        r = await c.post(
            f"/api/v1/blocks/{other_block}/harvest-lots",
            json={"harvested_on": "2026-10-09", "weight_kg": "1", "block_crop_id": assignment},
        )
        assert r.status_code == 409, r.text

        # Price arrives later: revenue follows.
        r = await c.patch(f"/api/v1/harvest-lots/{second['id']}", json={"price_per_kg": "10"})
        assert r.status_code == 200, r.text
        assert r.json()["revenue"] == "9000.00"

        listed = (await c.get(f"/api/v1/blocks/{block_id}/harvest-lots")).json()
        assert [x["pick_no"] for x in listed] == [2, 1]

        r = await c.delete(f"/api/v1/harvest-lots/{first['id']}")
        assert r.status_code == 204, r.text
        listed = (await c.get(f"/api/v1/blocks/{block_id}/harvest-lots")).json()
        assert [x["id"] for x in listed] == [second["id"]]
        # The number is free again once its pick is gone.
        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-10", "weight_kg": "5", "pick_no": 1},
        )
        assert r.status_code == 201, r.text

        # Without an assignment that day the season is the harvest year.
        r = await c.post(
            f"/api/v1/blocks/{other_block}/harvest-lots",
            json={"harvested_on": "2027-03-03", "weight_kg": "7"},
        )
        assert r.status_code == 201, r.text
        assert (r.json()["season_label"], r.json()["block_crop_id"]) == ("2027", None)


@pytest.mark.asyncio
async def test_roles_on_the_blocks_farm(admin_session: AsyncSession) -> None:
    admin, farm_id, block_id, _ = await _bootstrap_two_blocks(
        admin_session, f"hr-{uuid4().hex[:6]}"
    )
    async with _client(admin) as c:
        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-01", "weight_kg": "10"},
        )
        assert r.status_code == 201, r.text
        lot = r.json()

    async with _client(_as(FarmRole.FARM_MANAGER, admin, farm_id)) as c:
        r = await c.patch(f"/api/v1/harvest-lots/{lot['id']}", json={"weight_kg": "11"})
        assert r.status_code == 200, r.text

    # An agronomist reads but cannot write.
    async with _client(_as(FarmRole.AGRONOMIST, admin, farm_id)) as c:
        assert (await c.get(f"/api/v1/blocks/{block_id}/harvest-lots")).status_code == 200
        r = await c.post(
            f"/api/v1/blocks/{block_id}/harvest-lots",
            json={"harvested_on": "2026-10-02", "weight_kg": "1"},
        )
        assert r.status_code == 404, r.text
        assert (await c.delete(f"/api/v1/harvest-lots/{lot['id']}")).status_code == 404

    # A scout has no harvest access at all: the block answers like a missing one.
    async with _client(_as(FarmRole.SCOUT, admin, farm_id)) as c:
        assert (await c.get(f"/api/v1/blocks/{block_id}/harvest-lots")).status_code == 404

    # A manager of another farm sees nothing.
    async with _client(_as(FarmRole.FARM_MANAGER, admin, str(uuid4()))) as c:
        assert (await c.get(f"/api/v1/blocks/{block_id}/harvest-lots")).status_code == 404
