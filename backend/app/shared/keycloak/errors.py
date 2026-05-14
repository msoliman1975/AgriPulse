"""Keycloak admin-client exceptions."""

from __future__ import annotations


class KeycloakError(Exception):
    """Base class for Keycloak admin-client failures."""


class KeycloakNotConfiguredError(KeycloakError):
    """The configured client cannot run because credentials are missing."""


class KeycloakRequestError(KeycloakError):
    """A Keycloak admin-API call returned a non-2xx response."""

    def __init__(self, status_code: int, body: str, *, operation: str) -> None:
        super().__init__(f"Keycloak {operation} failed: HTTP {status_code} body={body[:500]}")
        self.status_code = status_code
        self.body = body
        self.operation = operation
