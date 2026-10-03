"""Integration tests for /api/v1/admin/health-definitions (public 0095).

Covers:
  * a tenant user can neither read nor write either tier;
  * the platform row exists after the migration and reads the code defaults;
  * a platform PUT that leaves a key out is refused, and a full one bumps
    the version and is what the next read returns;
  * a crop PUT on a path the catalogue lacks is a 404, not a row that
    reaches no block;
  * a crop PUT writes a row, a second one bumps its version, `{}` removes it;
  * a variety reads its crop's row as inherited, naming the crop.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/health-definitions"


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _tenant_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_role=TenantRole.TENANT_ADMIN,
        platform_role=None,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


@pytest.mark.asyncio
async def test_tenant_user_cannot_read_or_write() -> None:
    async with _tenant_client() as client:
        assert (await client.get(f"{_BASE}/platform")).status_code == 403
        assert (await client.get(f"{_BASE}/crops")).status_code == 403
        r = await client.put(f"{_BASE}/crops/mango", json={"definition": {}})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_platform_row_reads_the_code_defaults() -> None:
    async with _platform_client() as client:
        r = await client.get(f"{_BASE}/platform")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["definition"]["stale_after_hours"] >= 1
    assert set(body["definition"]) == {
        "severity_map",
        "counted_statuses",
        "snoozed_as",
        "cell_critical_share",
        "recommendation_floor",
        "stale_after_hours",
        "no_tree_coverage",
    }
    assert body["rollup"]["cell_rollup"] in ("worst", "share", "most_common")


@pytest.mark.asyncio
async def test_platform_put_needs_every_key_and_bumps_the_version() -> None:
    async with _platform_client() as client:
        before = (await client.get(f"{_BASE}/platform")).json()
        partial = {"stale_after_hours": 60}
        r = await client.put(f"{_BASE}/platform", json={"definition": partial})
        assert r.status_code == 422, r.text

        changed: dict[str, Any] = {**before["definition"], "stale_after_hours": 60}
        r = await client.put(f"{_BASE}/platform", json={"definition": changed, "notes": "test"})
        assert r.status_code == 200, r.text
        assert r.json()["definition"]["stale_after_hours"] == 60
        assert r.json()["version"] == before["version"] + 1

        restore = {"definition": before["definition"], "notes": before["notes"]}
        assert (await client.put(f"{_BASE}/platform", json=restore)).status_code == 200


@pytest.mark.asyncio
async def test_crop_put_on_an_unknown_path_is_404() -> None:
    async with _platform_client() as client:
        r = await client.put(
            f"{_BASE}/crops/no_such_crop.at_all",
            json={"definition": {"stale_after_hours": 12}},
        )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_crop_row_write_bump_inherit_and_remove() -> None:
    async with _platform_client() as client:
        before = (await client.get(f"{_BASE}/crops/mango")).json()
        own_before = before["own"]

        r = await client.put(f"{_BASE}/crops/mango", json={"definition": {"stale_after_hours": 30}})
        assert r.status_code == 200, r.text
        first = r.json()["own"]["version"]
        r = await client.put(f"{_BASE}/crops/mango", json={"definition": {"stale_after_hours": 31}})
        assert r.json()["own"]["version"] == first + 1

        varieties = (await client.get(f"{_BASE}/crops/mango.anything")).json()
        assert varieties["inherited"]["stale_after_hours"] == {"value": 31, "source": "mango"}

        r = await client.put(f"{_BASE}/crops/mango", json={"definition": {}})
        assert r.status_code == 200, r.text
        assert r.json()["own"] is None
        assert r.json()["inherited"]["stale_after_hours"]["source"] == "platform"

        if own_before is not None:
            restore = {"definition": own_before["definition"], "notes": own_before["notes"]}
            assert (await client.put(f"{_BASE}/crops/mango", json=restore)).status_code == 200
