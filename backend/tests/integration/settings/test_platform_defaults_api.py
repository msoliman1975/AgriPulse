"""Integration tests for /api/v1/admin/defaults.

This surface had no test coverage at all before: not the capability gate,
not the 404, not the schema check, not cache invalidation. It is the only
UI for `public.platform_defaults`, so a regression here is silent —
the page keeps rendering and Save keeps looking like it worked.

Covers:
  * platform.read gates the list; platform.manage_defaults gates writes;
  * an unknown key 404s rather than silently creating a row;
  * value_schema mismatches 400 (a string into a numeric key);
  * per-key constraints 400 (out-of-range, bad choice) — migration 0048's
    companion, since `platform_defaults` itself has no value CHECK;
  * a successful PUT persists, bumps updated_at/updated_by, and busts the
    resolver's 60s in-process cache;
  * the keys migration 0048 dropped are really gone.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.shared.auth.context import PlatformRole, TenantRole
from app.shared.settings import invalidate_defaults_cache

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]

# Survives migration 0048 and carries a constraint (0.1 .. 10.0).
_Z_KEY = "grid.anomaly_z_threshold"
_Z_SEED = 1.5
# Survives 0048, constrained to the enum the provider registry supports.
_PROVIDER_KEY = "weather.default_provider_code"

DROPPED_BY_0048 = (
    "weather.forecast_retention_days",
    "imagery.default_product_code",
    "email.from_address",
    "email.smtp_host",
    "webhook.signing_alg",
    "webhook.timeout_seconds",
    "alert.rate_limit_per_hour",
    "alert.channel_types_enabled",
)


@pytest.fixture(autouse=True)
def _flush_cache() -> None:
    invalidate_defaults_cache()


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _tenant_client() -> AsyncClient:
    """A tenant admin — holds no platform capability."""
    context = make_context(
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_role=TenantRole.TENANT_ADMIN,
        platform_role=None,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _restore(client: AsyncClient, key: str, value: object) -> None:
    r = await client.put(f"/api/v1/admin/defaults/{key}", json={"value": value})
    assert r.status_code == 200, r.text


# ---- Capability gate -------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_user_cannot_read_or_write_defaults() -> None:
    async with _tenant_client() as client:
        assert (await client.get("/api/v1/admin/defaults")).status_code == 403
        r = await client.put(f"/api/v1/admin/defaults/{_Z_KEY}", json={"value": 2.0})
        assert r.status_code == 403


# ---- Read ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_seeded_keys_with_constraints() -> None:
    async with _platform_client() as client:
        r = await client.get("/api/v1/admin/defaults")
        assert r.status_code == 200, r.text
        rows = {row["key"]: row for row in r.json()}

        assert _Z_KEY in rows
        z = rows[_Z_KEY]
        assert z["value_schema"] == "number"
        assert z["category"] == "alert"
        # The browser mirrors these bounds so bad values never round-trip.
        assert z["constraint"] == {"minimum": 0.1, "maximum": 10.0}

        assert rows[_PROVIDER_KEY]["constraint"] == {"choices": ["open_meteo"]}


@pytest.mark.asyncio
async def test_keys_dropped_by_migration_0048_are_gone() -> None:
    async with _platform_client() as client:
        keys = {row["key"] for row in (await client.get("/api/v1/admin/defaults")).json()}
        assert keys.isdisjoint(DROPPED_BY_0048), sorted(keys & set(DROPPED_BY_0048))


# ---- Write: rejections -----------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_key_404s_instead_of_creating_a_row() -> None:
    async with _platform_client() as client:
        r = await client.put("/api/v1/admin/defaults/nope.not.a.key", json={"value": 1})
        assert r.status_code == 404, r.text

        keys = {row["key"] for row in (await client.get("/api/v1/admin/defaults")).json()}
        assert "nope.not.a.key" not in keys


@pytest.mark.asyncio
async def test_wrong_json_type_is_rejected() -> None:
    async with _platform_client() as client:
        r = await client.put(f"/api/v1/admin/defaults/{_Z_KEY}", json={"value": "not-a-number"})
        assert r.status_code == 400, r.text
        assert r.json()["expected_schema"] == "number"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0.0, -3, 25])
async def test_out_of_range_number_is_rejected(bad: float) -> None:
    """`platform_defaults` has no value CHECK — the constraint registry is
    the only thing standing between an operator and a threshold that can
    never fire (or fires on every cell)."""
    async with _platform_client() as client:
        r = await client.put(f"/api/v1/admin/defaults/{_Z_KEY}", json={"value": bad})
        assert r.status_code == 400, r.text
        assert r.json()["constraint"] == {"minimum": 0.1, "maximum": 10.0}

        # And the stored value is untouched.
        rows = {row["key"]: row for row in (await client.get("/api/v1/admin/defaults")).json()}
        assert rows[_Z_KEY]["value"] != bad


@pytest.mark.asyncio
async def test_value_outside_the_choice_list_is_rejected() -> None:
    async with _platform_client() as client:
        r = await client.put(f"/api/v1/admin/defaults/{_PROVIDER_KEY}", json={"value": "banana"})
        assert r.status_code == 400, r.text
        assert r.json()["constraint"] == {"choices": ["open_meteo"]}


@pytest.mark.asyncio
async def test_non_integer_rejected_for_integer_only_key() -> None:
    async with _platform_client() as client:
        r = await client.put(
            "/api/v1/admin/defaults/imagery.cloud_cover_threshold_pct",
            json={"value": 30.5},
        )
        assert r.status_code == 400, r.text


# ---- Write: the happy path -------------------------------------------------


@pytest.mark.asyncio
async def test_save_persists_and_stamps_the_actor() -> None:
    actor = uuid4()
    context = make_context(user_id=actor, tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    transport = ASGITransport(app=build_app(context))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = {r["key"]: r for r in (await client.get("/api/v1/admin/defaults")).json()}[_Z_KEY]

        r = await client.put(f"/api/v1/admin/defaults/{_Z_KEY}", json={"value": 2.25})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["value"] == 2.25
        assert str(body["updated_by"]) == str(actor)
        assert body["updated_at"] >= before["updated_at"]
        # The response carries the constraint too, so the row the client
        # re-renders after a save is shaped like the one it listed.
        assert body["constraint"] == {"minimum": 0.1, "maximum": 10.0}

        # Durable, not just echoed back.
        after = {r["key"]: r for r in (await client.get("/api/v1/admin/defaults")).json()}[_Z_KEY]
        assert after["value"] == 2.25

        await _restore(client, _Z_KEY, _Z_SEED)


@pytest.mark.asyncio
async def test_save_busts_the_resolver_cache() -> None:
    """The resolver caches platform_defaults for 60s per process. Without
    the invalidate hook in the PUT handler, a save would appear to work
    and change nothing for up to a minute."""
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (typing only)

    from app.shared.db.session import get_admin_db_session

    async with _platform_client() as client:
        # Warm the cache through the resolver.
        gen = get_admin_db_session()
        session = await anext(gen)
        try:
            from app.shared.settings import SettingsResolver

            resolver = SettingsResolver(public_session=session)
            tenant_id = uuid4()
            # Unknown tenant resolves to the platform tier — that is the
            # value we care about here.
            warmed = await resolver.get_tenant(tenant_id, _Z_KEY)
            assert warmed.source == "platform"

            r = await client.put(f"/api/v1/admin/defaults/{_Z_KEY}", json={"value": 3.75})
            assert r.status_code == 200, r.text

            refreshed = await resolver.get_tenant(tenant_id, _Z_KEY)
            assert refreshed.value == 3.75, "PUT did not invalidate the defaults cache"
        finally:
            await gen.aclose()

        await _restore(client, _Z_KEY, _Z_SEED)
