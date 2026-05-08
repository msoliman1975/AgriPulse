"""Keycloak admin-API client used by tenancy + IAM provisioning paths.

Public surface:

  - `KeycloakAdminClient`  — Protocol modules depend on
  - `get_keycloak_client` — factory; returns the real httpx client when
                            `Settings.keycloak_provisioning_enabled=True`,
                            otherwise a no-op fallback so dev/test envs
                            without Keycloak admin creds still work.
  - `FakeKeycloakClient`   — in-memory implementation for tests.
  - `KeycloakError`        — base exception class for the module.
"""

from app.shared.keycloak.client import (
    HttpxKeycloakAdminClient,
    KeycloakAdminClient,
    NoopKeycloakClient,
    get_keycloak_client,
    set_keycloak_client,
)
from app.shared.keycloak.errors import (
    KeycloakError,
    KeycloakNotConfiguredError,
    KeycloakRequestError,
)
from app.shared.keycloak.fakes import FakeKeycloakClient

__all__ = [
    "FakeKeycloakClient",
    "HttpxKeycloakAdminClient",
    "KeycloakAdminClient",
    "KeycloakError",
    "KeycloakNotConfiguredError",
    "KeycloakRequestError",
    "NoopKeycloakClient",
    "get_keycloak_client",
    "set_keycloak_client",
]
