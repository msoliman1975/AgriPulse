"""Integration test: tenant migration 0003 creates subscriptions, jobs,
the indices hypertable, the daily / weekly continuous aggregates, and
attaches the per-tenant pgstac.items RLS policy.

We don't run the migration directly — `tenancy.create_tenant` runs the
full tenant migration chain (0001 → 0002 → 0003) as part of bootstrap.
Each test creates a fresh tenant and inspects its schema.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
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
        name=f"Imagery Test {slug}",
        contact_email=f"ops@{slug}.test",
        actor_user_id=uuid4(),
    )
    return result.schema_name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_imagery_subscription_and_jobs_tables_present(
    admin_session: AsyncSession,
) -> None:
    schema = await _create_tenant(admin_session, "imagery-tables")
    rows = (
        await admin_session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name IN ("
                "'imagery_aoi_subscriptions','imagery_ingestion_jobs',"
                "'block_index_aggregates')"
            ),
            {"s": schema},
        )
    ).all()
    names = {r[0] for r in rows}
    assert names == {
        "imagery_aoi_subscriptions",
        "imagery_ingestion_jobs",
        "block_index_aggregates",
    }


@pytest.mark.asyncio
async def test_block_index_aggregates_is_hypertable(
    admin_session: AsyncSession,
) -> None:
    schema = await _create_tenant(admin_session, "imagery-hypertable")
    row = (
        await admin_session.execute(
            text(
                "SELECT num_dimensions FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = :s "
                "AND hypertable_name = 'block_index_aggregates'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None, "block_index_aggregates must be a TimescaleDB hypertable"
    # Time + space partition.
    assert row.num_dimensions == 2


@pytest.mark.asyncio
async def test_block_index_aggregates_unique_for_idempotency(
    admin_session: AsyncSession,
) -> None:
    """The composite UNIQUE on (time, block_id, index_code, product_id)
    is the per-scene idempotency key — Q5 in the PR-A plan.
    """
    schema = await _create_tenant(admin_session, "imagery-idempotency")
    row = (
        await admin_session.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) AS constraint_def "
                "FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = "
                "'uq_block_index_aggregates_time_block_index_product'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    assert "time" in row.constraint_def
    assert "block_id" in row.constraint_def
    assert "index_code" in row.constraint_def
    assert "product_id" in row.constraint_def


@pytest.mark.asyncio
async def test_continuous_aggregates_present(admin_session: AsyncSession) -> None:
    schema = await _create_tenant(admin_session, "imagery-caggs")
    rows = (
        await admin_session.execute(
            text(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = :s "
                "AND view_name IN ('block_index_daily','block_index_weekly')"
            ),
            {"s": schema},
        )
    ).all()
    names = {r[0] for r in rows}
    assert names == {"block_index_daily", "block_index_weekly"}


@pytest.mark.asyncio
async def test_pgstac_items_rls_policy_attached(admin_session: AsyncSession) -> None:
    """RLS is enabled on pgstac.items and the per-tenant policy exists."""
    schema = await _create_tenant(admin_session, "imagery-rls")

    rls_enabled = (
        await admin_session.execute(
            text(
                "SELECT relrowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'pgstac' AND c.relname = 'items'"
            )
        )
    ).scalar_one()
    assert rls_enabled is True

    policy_count = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname = 'pgstac' AND tablename = 'items' "
                "AND policyname = :p"
            ),
            {"p": f"tenant_isolation_{schema}"},
        )
    ).scalar_one()
    assert policy_count == 1


@pytest.mark.asyncio
async def test_subscription_unique_per_block_product(
    admin_session: AsyncSession,
) -> None:
    """uq_imagery_aoi_subscriptions_block_product_active prevents duplicates
    on (block_id, product_id) where is_active = TRUE.
    """
    schema = await _create_tenant(admin_session, "imagery-uniqueness")
    row = (
        await admin_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s "
                "AND indexname = "
                "'uq_imagery_aoi_subscriptions_block_product_active'"
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
    """The FK on imagery_aoi_subscriptions.block_id is ON DELETE CASCADE."""
    schema = await _create_tenant(admin_session, "imagery-cascade")
    row = (
        await admin_session.execute(
            text(
                "SELECT confdeltype FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :s "
                "AND c.conname = "
                "'fk_imagery_aoi_subscriptions_block_id_blocks'"
            ),
            {"s": schema},
        )
    ).one_or_none()
    assert row is not None
    # Postgres encodes ON DELETE CASCADE as 'c'. The asyncpg driver
    # returns "char"-typed columns as bytes; normalize before comparing.
    raw = row.confdeltype
    assert (raw.decode() if isinstance(raw, bytes | bytearray) else raw) == "c"


@pytest.mark.asyncio
async def test_session_set_app_tenant_collection_prefix(
    admin_session: AsyncSession,
) -> None:
    """The session middleware sets `app.tenant_collection_prefix` on
    every tenant-scoped session — exercised by spinning up a tenant
    session manually and reading the GUC back.
    """
    schema = await _create_tenant(admin_session, "imagery-guc")

    from app.shared.db.session import AsyncSessionLocal, _set_search_path

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_search_path(session, schema)
        prefix = (
            await session.execute(
                text("SELECT current_setting('app.tenant_collection_prefix', TRUE)")
            )
        ).scalar_one()
        tenant_id_setting = (
            await session.execute(text("SELECT current_setting('app.current_tenant_id', TRUE)"))
        ).scalar_one()
    assert prefix == f"{schema}__%"
    assert tenant_id_setting == schema


# Suppress unused import in mypy strict if applicable.
_ = bindparam
