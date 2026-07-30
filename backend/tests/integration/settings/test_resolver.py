"""SettingsResolver — three-tier resolution tests.

Covers the precedence chain at the tenant tier:

  platform_defaults (seed migration 0020)
    → tenant_settings_overrides[tenant_id, key]

Plus the SettingNotFoundError surface and the cache invalidation
hook. Farm + LandUnit tier tests live with PR-Set4 (the migrations
that create those override tables).
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.keycloak import FakeKeycloakClient
from app.shared.settings import (
    SettingNotFoundError,
    SettingsRepository,
    SettingsResolver,
    invalidate_defaults_cache,
)

pytestmark = [pytest.mark.integration]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def _create_tenant(admin_session: AsyncSession):
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)
    return await service.create_tenant(
        slug=_slug("res"),
        name="Res",
        contact_email="ops@res.test",
        actor_user_id=None,
    )


async def _make_tenant(admin_session: AsyncSession) -> str:
    return (await _create_tenant(admin_session)).tenant_id


@pytest.fixture(autouse=True)
def _flush_cache() -> None:
    """Each test starts with a cold cache so writes from the previous
    test don't leak through the 60s TTL."""
    invalidate_defaults_cache()


@pytest.mark.asyncio
async def test_platform_default_returned_when_no_override(
    admin_session: AsyncSession,
) -> None:
    tenant_id = await _make_tenant(admin_session)
    resolver = SettingsResolver(public_session=admin_session)
    resolved = await resolver.get_tenant(tenant_id, "weather.default_cadence_hours")
    assert resolved.value == 3
    assert resolved.source == "platform"


@pytest.mark.asyncio
async def test_tenant_override_wins_over_platform(
    admin_session: AsyncSession,
) -> None:
    tenant_id = await _make_tenant(admin_session)
    repo = SettingsRepository(public_session=admin_session)
    await repo.upsert_tenant_override(
        tenant_id=tenant_id,
        key="weather.default_cadence_hours",
        value_json=json.dumps(6),
        actor_user_id=None,
    )
    resolver = SettingsResolver(public_session=admin_session)
    resolved = await resolver.get_tenant(tenant_id, "weather.default_cadence_hours")
    assert resolved.value == 6
    assert resolved.source == "tenant"


@pytest.mark.asyncio
async def test_unknown_key_raises(admin_session: AsyncSession) -> None:
    tenant_id = await _make_tenant(admin_session)
    resolver = SettingsResolver(public_session=admin_session)
    with pytest.raises(SettingNotFoundError):
        await resolver.get_tenant(tenant_id, "missing.key")


@pytest.mark.asyncio
async def test_delete_override_falls_back_to_platform(
    admin_session: AsyncSession,
) -> None:
    tenant_id = await _make_tenant(admin_session)
    repo = SettingsRepository(public_session=admin_session)
    key = "grid.anomaly_z_threshold"  # seeded 1.5 by migration 0026
    await repo.upsert_tenant_override(
        tenant_id=tenant_id,
        key=key,
        value_json=json.dumps(3.0),
        actor_user_id=None,
    )
    resolver = SettingsResolver(public_session=admin_session)
    assert (await resolver.get_tenant(tenant_id, key)).value == 3.0

    deleted = await repo.delete_tenant_override(tenant_id=tenant_id, key=key)
    assert deleted is True
    invalidate_defaults_cache()
    after = await resolver.get_tenant(tenant_id, key)
    assert after.value == 1.5
    assert after.source == "platform"


@pytest.mark.asyncio
async def test_platform_default_change_picked_up_after_invalidate(
    admin_session: AsyncSession,
) -> None:
    """The 60s in-process cache is the trade-off documented in the
    proposal. Admin writes invalidate it explicitly so the next read
    sees the new value without waiting."""
    tenant_id = await _make_tenant(admin_session)
    resolver = SettingsResolver(public_session=admin_session)
    key = "imagery.cloud_cover_threshold_pct"  # seeded 30 by migration 0020

    # Warm the cache with the seed default.
    initial = await resolver.get_tenant(tenant_id, key)
    assert initial.value == 30

    # Direct DB update bypassing the repo (simulating an out-of-band
    # change — the repo's update_default_value would call invalidate).
    await admin_session.execute(
        text(
            "UPDATE public.platform_defaults "
            "SET value = '45'::jsonb, updated_at = now() "
            "WHERE key = :key"
        ),
        {"key": key},
    )
    # Cache still serves the old value.
    cached = await resolver.get_tenant(tenant_id, key)
    assert cached.value == 30

    invalidate_defaults_cache()
    after = await resolver.get_tenant(tenant_id, key)
    assert after.value == 45

    # Reset for the next test (autouse flush_cache only clears the
    # in-process cache, not the DB row).
    await admin_session.execute(
        text("UPDATE public.platform_defaults SET value = '30'::jsonb WHERE key = :key"),
        {"key": key},
    )
    # Use the bind param to silence linter about unused PG_UUID import.
    _ = bindparam("x", type_=PG_UUID(as_uuid=True))


# ---- Tier column maps ------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_column_maps_reference_real_columns(
    admin_session: AsyncSession,
) -> None:
    """Every column the resolver maps a key onto must exist on its table.

    The block tier used to map `imagery.cloud_cover_threshold_pct` onto a
    `cloud_cover_threshold_pct` column of `imagery_aoi_subscriptions` —
    which is actually named `cloud_cover_max_pct`. Postgres raised
    UndefinedColumn on every read and a bare `except Exception` swallowed
    it, so the LandUnit tier silently never applied. Assert the mapping
    against the live schema so a rename can't reintroduce that.
    """
    from app.shared.settings.resolver import (
        _BLOCK_IMAGERY_COLUMNS,
        _FARM_IMAGERY_COLUMNS,
        _FARM_WEATHER_COLUMNS,
    )

    tenant = await _create_tenant(admin_session)
    schema = tenant.schema_name

    expected: dict[str, set[str]] = {
        "farm_weather_overrides": set(_FARM_WEATHER_COLUMNS.values()),
        "farm_imagery_overrides": set(_FARM_IMAGERY_COLUMNS.values()),
        "imagery_aoi_subscriptions": set(_BLOCK_IMAGERY_COLUMNS.values()),
    }

    for table, mapped in expected.items():
        rows = (
            await admin_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            )
        ).all()
        actual = {r.column_name for r in rows}
        assert actual, f"{schema}.{table} not found — did the tenant migration run?"
        missing = mapped - actual
        assert not missing, f"{table} is missing mapped column(s): {sorted(missing)}"
