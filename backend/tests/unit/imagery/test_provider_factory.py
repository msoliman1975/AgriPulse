"""Unit tests for the imagery provider factory seam.

`_make_provider` dispatches on `public.imagery_providers.code` (supplied
by `_lookup_product`) so a second provider is a catalog row plus one
branch. Mirrors the weather module's factory, which has had the same
shape since PR-B.
"""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.modules.imagery import tasks as imagery_tasks
from app.modules.imagery.providers.sentinel_hub import SentinelHubProvider


def test_sentinel_hub_code_builds_the_sentinel_hub_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_HUB_CLIENT_ID", "test-client")
    monkeypatch.setenv("SENTINEL_HUB_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        provider = imagery_tasks._make_provider("sentinel_hub")
    finally:
        get_settings.cache_clear()

    assert isinstance(provider, SentinelHubProvider)
    assert provider.code == "sentinel_hub"


def test_unknown_code_raises_with_the_code_in_the_message() -> None:
    with pytest.raises(ValueError, match="landsat_ot_l1"):
        imagery_tasks._make_provider("landsat_ot_l1")


def test_reset_restores_the_real_factory() -> None:
    imagery_tasks.set_provider_factory(lambda _code: None)  # type: ignore[arg-type,return-value]
    try:
        assert imagery_tasks._provider_factory is not imagery_tasks._make_provider
    finally:
        imagery_tasks.reset_provider_factory()

    assert imagery_tasks._provider_factory is imagery_tasks._make_provider
