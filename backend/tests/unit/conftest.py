"""Shared pytest fixtures.

Unit tests must not need a database or broker; integration tests start
testcontainers in `tests/integration/conftest.py`.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _safe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe app-affecting env vars so tests run with the in-code defaults.

    Production `APP_*` / `KEYCLOAK_*` env vars must never bleed into a
    test run.
    """
    for key in list(os.environ):
        if key.startswith(("APP_", "KEYCLOAK_", "DATABASE_", "REDIS_", "OTEL_", "CELERY_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "test")

    # Reset cached settings so the next get_settings() picks up the
    # cleaned environment.
    from app.core.settings import get_settings

    get_settings.cache_clear()
