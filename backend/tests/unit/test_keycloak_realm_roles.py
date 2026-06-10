"""IH-4: realm roles are seeded, not auto-created.

The real client must refuse to assign a role that doesn't exist (a typo
or an un-promoted realm) instead of silently creating it; the fake
mirrors that contract.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app.core.settings import Settings
from app.shared.keycloak.client import HttpxKeycloakAdminClient
from app.shared.keycloak.errors import KeycloakRequestError
from app.shared.keycloak.fakes import FakeKeycloakClient


def _client_with_transport(handler: object) -> HttpxKeycloakAdminClient:
    settings = Settings(
        keycloak_admin_client_secret="unit-secret",
        keycloak_provisioning_enabled=True,
    )
    client = HttpxKeycloakAdminClient(settings)
    # Swap in a mock transport and pre-prime the bearer token so no real
    # network call is made.
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    client._token = "unit-token"
    client._token_expires_at = time.monotonic() + 9999
    return client


@pytest.mark.asyncio
async def test_assign_realm_role_raises_when_role_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/roles/TenantOwner"):
            return httpx.Response(404, text="role not found")
        return httpx.Response(200, json={})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(KeycloakRequestError) as excinfo:
            await client._assign_realm_role("user-1", "TenantOwner")
        assert excinfo.value.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_assign_realm_role_succeeds_when_role_exists() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET" and request.url.path.endswith("/roles/TenantOwner"):
            return httpx.Response(200, json={"id": "role-uuid", "name": "TenantOwner"})
        if request.url.path.endswith("/role-mappings/realm"):
            return httpx.Response(204)
        return httpx.Response(200, json={})

    client = _client_with_transport(handler)
    try:
        await client._assign_realm_role("user-1", "TenantOwner")
    finally:
        await client.aclose()
    # No POST /roles (create) was ever issued — only lookup + mapping.
    assert not any(c == "POST /admin/realms/agripulse/roles" for c in calls)


@pytest.mark.asyncio
async def test_fake_rejects_unknown_realm_role() -> None:
    fake = FakeKeycloakClient()
    group_id = await fake.ensure_group("acme")
    with pytest.raises(KeycloakRequestError):
        await fake.invite_user(
            email="x@acme.test",
            full_name="X",
            group_id=group_id,
            roles=("NotARealRole",),
        )


@pytest.mark.asyncio
async def test_fake_accepts_seeded_realm_role() -> None:
    fake = FakeKeycloakClient()
    group_id = await fake.ensure_group("acme")
    result = await fake.invite_user(
        email="x@acme.test",
        full_name="X",
        group_id=group_id,
        roles=("TenantOwner",),
    )
    assert "TenantOwner" in fake.users[result.keycloak_user_id].realm_roles
