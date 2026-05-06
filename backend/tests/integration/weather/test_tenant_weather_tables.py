"""Integration test: tenant migration 0005 creates weather_subscriptions,
the observations + forecasts hypertables, and weather_derived_daily.

We don't run the migration directly — `tenancy.create_tenant` runs the
full tenant migration chain (0001 → 0002 → 0003 → 0004 → 0005) as part
of bootstrap. Each test creates a fresh tenant and inspects its schema.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tenant(admin_session: AsyncSession, slug: str) -> str:
    """Create a fresh tenant; return its schema name."""
    from app.modules.tenancy.service import get_tenant_service

    service = get_tenant_service(admin_session)
    result = await service.create_tenant(
        slug=slug,
        name=f"Weather Test {slug}",
        contact_email=f"ops@{slug}.test",
        actor_user_id=uuid4(),
    )
    return result.schema_name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weather_tables_present(admin_session: AsyncSession) -> None:
    schema = await _create_tenant(admin_session, "weather-tables")
    rows = (
        await admin_session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name IN ("
                "'weather_subscriptions','weather_observations',"
                "'weather_forecasts','weather_derived_daily')"
            ),
            {"s": schema},
        )
    ).all()
    names = {r[0] for r in rows}
    assert names == {
        "weather_subscriptions",
        "weather_observations",
        "weather_forecasts",
        "weather_derived_daily",
    }


@pytest.mark.asyncio
async def test_observations_and_forecasts_are_hypertables(
    admin_session: AsyncSession,
) -> None:
    schema = await _create_tenant(admin_session, "weather-hypertables")
    rows = (
        await admin_session.execute(
            text(
                "SELECT hypertable_name, num_dimensions "
                "FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = :s "
                "AND hypertable_name IN ('weather_observations','weather_forecasts')"
            ),
            {"s": schema},
        )
    ).all()
    by_name = {r.hypertable_name: r.num_dimensions for r in rows}
    assert by_name == {
        # time + farm_id space partition.
        "weather_observations": 2,
        "weather_forecasts": 2,
    }


@pytest.mark.asyncio
async def test_observations_unique_for_idempotency(
    admin_session: AsyncSession,
) -> None:
    """UNIQUE (time, farm_id, provider_code) is the per-(hour, farm) key."""
    schema = await _create_tenant(admin_session, "weather-obs-uq")
    row = (
        await admin_session.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) AS constraint_def "
                "FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = 'uq_weather_observations_time_farm_provider'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    assert "time" in row.constraint_def
    assert "farm_id" in row.constraint_def
    assert "provider_code" in row.constraint_def


@pytest.mark.asyncio
async def test_forecasts_unique_keeps_all_issuances(
    admin_session: AsyncSession,
) -> None:
    """UNIQUE (time, farm_id, provider_code, forecast_issued_at) preserves
    every issuance — locked Slice-4 decision: keep all forecast snapshots.
    """
    schema = await _create_tenant(admin_session, "weather-fc-uq")
    row = (
        await admin_session.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) AS constraint_def "
                "FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = "
                "'uq_weather_forecasts_time_farm_provider_issued'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    assert "time" in row.constraint_def
    assert "farm_id" in row.constraint_def
    assert "provider_code" in row.constraint_def
    assert "forecast_issued_at" in row.constraint_def


@pytest.mark.asyncio
async def test_subscription_unique_per_block_provider(
    admin_session: AsyncSession,
) -> None:
    """Partial UNIQUE (block_id, provider_code) WHERE is_active = TRUE."""
    schema = await _create_tenant(admin_session, "weather-sub-uq")
    row = (
        await admin_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s "
                "AND indexname = 'uq_weather_subscriptions_block_provider_active'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    assert "is_active" in row.indexdef.lower()


@pytest.mark.asyncio
async def test_subscription_cascades_when_block_deleted(
    admin_session: AsyncSession,
) -> None:
    """fk_weather_subscriptions_block_id_blocks is ON DELETE CASCADE."""
    schema = await _create_tenant(admin_session, "weather-sub-cascade")
    row = (
        await admin_session.execute(
            text(
                "SELECT confdeltype FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = 'fk_weather_subscriptions_block_id_blocks'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    raw = row.confdeltype
    # 'c' = ON DELETE CASCADE in pg_constraint.
    assert (raw.decode() if isinstance(raw, bytes | bytearray) else raw) == "c"


@pytest.mark.asyncio
async def test_derived_daily_pk_is_farm_date(admin_session: AsyncSession) -> None:
    """Composite PK (farm_id, date) per data_model § 8.4."""
    schema = await _create_tenant(admin_session, "weather-derived-pk")
    row = (
        await admin_session.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) AS constraint_def "
                "FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = 'pk_weather_derived_daily'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    assert "farm_id" in row.constraint_def
    assert "date" in row.constraint_def


@pytest.mark.asyncio
async def test_derived_daily_cascades_when_farm_deleted(
    admin_session: AsyncSession,
) -> None:
    """fk_weather_derived_daily_farm_id_farms is ON DELETE CASCADE."""
    schema = await _create_tenant(admin_session, "weather-derived-cascade")
    row = (
        await admin_session.execute(
            text(
                "SELECT confdeltype FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = 'fk_weather_derived_daily_farm_id_farms'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    raw = row.confdeltype
    assert (raw.decode() if isinstance(raw, bytes | bytearray) else raw) == "c"


@pytest.mark.asyncio
async def test_compression_policies_attached(admin_session: AsyncSession) -> None:
    """Both hypertables have a compression policy registered.

    Observations: 30-day cutoff. Forecasts: 14-day cutoff. The exact
    interval comparison is brittle across TimescaleDB versions, so we
    just assert each hypertable carries one policy job.
    """
    schema = await _create_tenant(admin_session, "weather-compress")
    rows = (
        await admin_session.execute(
            text(
                "SELECT j.hypertable_name AS name "
                "FROM timescaledb_information.jobs j "
                "WHERE j.proc_name = 'policy_compression' "
                "AND j.hypertable_schema = :s "
                "AND j.hypertable_name IN "
                "('weather_observations','weather_forecasts')"
            ),
            {"s": schema},
        )
    ).all()
    names = {r.name for r in rows}
    assert names == {"weather_observations", "weather_forecasts"}
