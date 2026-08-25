"""The Records tab: a Scout listing the observations they filed.

`GET /signals/observations` gated on `signal.read` with no farm to resolve
against, so the check stopped at the tenant tier. A Scout holds no tenant role
— that is the whole point of the persona — so the app's Records screen 403'd
for the only people who file records, while the sibling definitions list beside
it worked because it already passed `farm_id_param`.

Both directions are pinned here: a farm-scoped caller who names their farm gets
in, and one who names no farm still does not, because with no farm there is
nothing to scope the read to.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import install_exception_handlers
from app.modules.signals.router import router as signals_router
from tests.integration.farms.conftest import StubAuth
from tests.integration.scouting.conftest import ScoutingFixture

pytestmark = [pytest.mark.integration]


def _signals_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(signals_router)
    app.add_middleware(StubAuth, context=context)
    return app


@pytest.mark.asyncio
async def test_scout_can_list_observations_on_their_own_farm(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    async with AsyncClient(
        transport=ASGITransport(app=_signals_app(env.scout_context)), base_url="http://test"
    ) as client:
        named = await client.get(f"/api/v1/signals/observations?farm_id={env.farm_id}&limit=200")
        unnamed = await client.get("/api/v1/signals/observations?limit=200")

    assert named.status_code == 200, named.text
    assert isinstance(named.json(), list)
    # No farm named, no tenant role to fall back on — still denied.
    assert unnamed.status_code == 403, unnamed.text


@pytest.mark.asyncio
async def test_scout_cannot_read_a_farm_they_are_not_scoped_to(
    scouting_env: ScoutingFixture,
) -> None:
    """Naming a farm is not the same as holding it."""
    env = scouting_env
    # The agronomist's farm is the same one, so use a farm id nobody holds.
    stranger = "019fe30d-0000-7000-8000-000000000000"
    async with AsyncClient(
        transport=ASGITransport(app=_signals_app(env.scout_context)), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/signals/observations?farm_id={stranger}")
    assert resp.status_code == 403, resp.text
