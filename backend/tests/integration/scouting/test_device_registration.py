"""Device registration as the persona that actually registers devices.

The device endpoints shipped gated on a bare ``notification.write_inbox`` with
no ``farm_id_param``. Every role grants that capability, so the gate looked
correct — but capability resolution runs PlatformRole -> TenantRole -> FarmScope
and the farm branch is only consulted when a farm_id is supplied. A Scout holds
no tenant role, so the check fell through to a deny and **every registration
403'd**.

That failed silently in three layers at once: the app treats a failed
registration as non-fatal (the visit list is the source of truth), the scouting
integration suite never mounted the notifications router, and the device tests
used a tenant-roled user. The visible symptom would have been a scout who signs
in, works normally, and simply never gets pushed.

So these tests mount the notifications router and drive it as a farm-scoped-only
Scout — the same shape the rest of this package guards.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import install_exception_handlers
from app.modules.notifications.router import router as notifications_router
from tests.integration.farms.conftest import StubAuth
from tests.integration.scouting.conftest import ScoutingFixture

pytestmark = [pytest.mark.integration]

_TOKEN = "fake-fcm-token-for-the-scout-handset"


def _devices_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(notifications_router)
    app.add_middleware(StubAuth, context=context)
    return app


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=_devices_app(context)), base_url="http://test")


@pytest.mark.asyncio
async def test_scout_can_register_and_list_their_handset(scouting_env: ScoutingFixture) -> None:
    async with _client(scouting_env.scout_context) as client:
        resp = await client.post(
            f"/api/v1/devices:register?farm_id={scouting_env.farm_id}",
            json={"token": _TOKEN, "platform": "android"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["user_id"] == str(scouting_env.scout_user_id)
        # The token is never echoed back — it is a push credential, not an id.
        assert _TOKEN not in resp.text

        listed = await client.get(f"/api/v1/devices?farm_id={scouting_env.farm_id}")
        assert listed.status_code == 200, listed.text
        assert [row["user_id"] for row in listed.json()] == [str(scouting_env.scout_user_id)]


@pytest.mark.asyncio
async def test_scout_registration_without_a_farm_is_denied(scouting_env: ScoutingFixture) -> None:
    """Pins *why* the client sends farm_id, so removing it fails loudly here.

    Without a farm there is no scope in which a Scout's capability can resolve.
    A tenant-roled caller still passes without one, which is why the omission
    went unnoticed.
    """
    async with _client(scouting_env.scout_context) as client:
        resp = await client.post(
            "/api/v1/devices:register",
            json={"token": _TOKEN, "platform": "android"},
        )
        assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_revoking_signs_the_handset_out(scouting_env: ScoutingFixture) -> None:
    async with _client(scouting_env.scout_context) as client:
        await client.post(
            f"/api/v1/devices:register?farm_id={scouting_env.farm_id}",
            json={"token": _TOKEN, "platform": "android"},
        )
        revoked = await client.delete(f"/api/v1/devices/{_TOKEN}?farm_id={scouting_env.farm_id}")
        assert revoked.status_code == 204, revoked.text

        listed = await client.get(f"/api/v1/devices?farm_id={scouting_env.farm_id}")
        assert listed.json() == []

        # A second revoke 404s rather than reporting success: a sign-out that
        # silently did nothing is how a handset keeps receiving a farm's work.
        again = await client.delete(f"/api/v1/devices/{_TOKEN}?farm_id={scouting_env.farm_id}")
        assert again.status_code == 404, again.text
