"""The reset that clears a build tenant before a rebuild.

No database. The SQL is recorded rather than run, because the property
that matters is in the SQL text itself: every statement names the tenant
schema. With `public` on the search path, an unqualified table that is
not a tenant table would delete from every tenant at once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.settings import get_settings
from app.modules.demo_history.reset import reset_build_tenant
from app.modules.demo_history.runner import ReplayNotAllowedError

SCHEMA = "tenant_demobuild_x"


class _Result:
    rowcount = 3

    def scalar_one(self) -> datetime:
        return datetime(2026, 9, 29, 20, tzinfo=UTC)


class _Session:
    def __init__(self, seen: list[str]) -> None:
        self.seen = seen

    async def execute(self, stmt: Any, params: Any = None) -> _Result:
        self.seen.append(str(stmt))
        return _Result()

    def begin(self) -> _Session:
        return self

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _factory(seen: list[str]) -> Any:
    return lambda: _Session(seen)


@pytest.fixture
def _build_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_HISTORY_BUILD_SCHEMA_PREFIX", "tenant_demobuild")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_build_prefix")
async def test_every_write_names_the_tenant_schema() -> None:
    seen: list[str] = []
    counts = await reset_build_tenant(_factory(seen), SCHEMA)

    writes = [s for s in seen if s.lstrip().upper().startswith(("DELETE", "UPDATE"))]
    assert writes, "the reset wrote nothing"
    for stmt in writes:
        assert f"{SCHEMA}." in stmt, stmt
    assert counts["recommendations"] == 3
    assert "block_crops_stage_cleared" in counts


@pytest.mark.asyncio
@pytest.mark.usefixtures("_build_prefix")
async def test_inputs_are_never_cleared() -> None:
    seen: list[str] = []
    await reset_build_tenant(_factory(seen), SCHEMA)
    text = "\n".join(seen)
    for kept in (
        "block_index_aggregates",
        "block_grid_aggregates",
        "weather_observations",
        "blocks ",
        "farms ",
        "tree_parameter_overrides",
    ):
        assert f"DELETE FROM {SCHEMA}.{kept}" not in text


@pytest.mark.asyncio
async def test_a_tenant_that_is_not_a_build_tenant_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_HISTORY_BUILD_SCHEMA_PREFIX", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ReplayNotAllowedError):
            await reset_build_tenant(_factory([]), "tenant_customer")
    finally:
        get_settings.cache_clear()
