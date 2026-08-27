"""The welcome email must hand the user back to the app.

`execute-actions-email` only honours `redirect_uri` when the request
also names a client that has it registered. Without `client_id` the
action token defaults to `account`, Keycloak drops the redirect, and an
invited owner is left on a Keycloak page after setting the password.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.shared.keycloak.client import HttpxKeycloakAdminClient


def _client(handler: object, **overrides: object) -> HttpxKeycloakAdminClient:
    settings = Settings(
        keycloak_admin_client_secret="unit-secret",
        keycloak_provisioning_enabled=True,
        **overrides,  # type: ignore[arg-type]
    )
    client = HttpxKeycloakAdminClient(settings)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    client._token = "unit-token"
    client._token_expires_at = time.monotonic() + 9999
    return client


@pytest.mark.asyncio
async def test_password_reset_email_carries_redirect_and_client() -> None:
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.url.query.decode()))
        return httpx.Response(204)

    client = _client(
        handler,
        keycloak_invite_redirect_url="https://app.agripulse.cloud/",
        keycloak_invite_client_id="agripulse-api",
    )
    try:
        await client._send_password_reset("user-1")
    finally:
        await client.aclose()

    assert seen["redirect_uri"] == ["https://app.agripulse.cloud/"]
    assert seen["client_id"] == ["agripulse-api"]


@pytest.mark.asyncio
async def test_password_reset_email_sends_no_params_without_redirect() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.query.decode())
        return httpx.Response(204)

    client = _client(handler, keycloak_invite_redirect_url="")
    try:
        await client._send_password_reset("user-1")
    finally:
        await client.aclose()

    # A client_id on its own would change nothing and only widens the
    # action token's audience, so it is omitted with the redirect.
    assert seen == [""]
