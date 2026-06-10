"""IH-5: tenant seed script — no-op guards (DB-free paths)."""

from __future__ import annotations

import pytest

from scripts import seed_tenant


@pytest.mark.asyncio
async def test_seed_noop_when_slug_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SEED_TENANT_SLUG", raising=False)

    # Guard: if the no-op check ever regresses, this would try to open a
    # DB session and blow up — assert it stays a clean early return.
    async def _boom(_slug: str) -> bool:
        raise AssertionError("_tenant_exists must not run when slug is empty")

    monkeypatch.setattr(seed_tenant, "_tenant_exists", _boom)

    await seed_tenant.seed()
    assert "nothing to seed" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_seed_noop_when_tenant_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SEED_TENANT_SLUG", "acme")

    async def _exists(_slug: str) -> bool:
        return True

    monkeypatch.setattr(seed_tenant, "_tenant_exists", _exists)

    await seed_tenant.seed()
    assert "already exists" in capsys.readouterr().out
