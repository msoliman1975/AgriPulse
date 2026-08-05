"""Downgrade/upgrade roundtrip for tenant migrations 0055 + 0056.

0055 rewrites the two integration-health views and 0056 re-chunks the
aggregate hypertables. Both have hand-written `downgrade()` bodies (0055
carries a verbatim copy of the pre-0055 view SQL), and nothing else in the
suite exercises a tenant downgrade — a typo in either would only surface
during an incident rollback, which is the worst possible time to find it.

Also asserts the thing the rewrite is *for*: that the new views are
value-identical to the ones they replace. The rewrite trades
`COUNT(DISTINCT ...)` over a fanned-out join for `count(*)` over
pre-aggregated branches, which is only safe because each attempt/job row
belongs to exactly one block. This pins that equivalence on real rows
rather than on the argument for it.
"""

from __future__ import annotations

from argparse import Namespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.bootstrap import ALEMBIC_INI
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_HEALTH_COLUMNS = (
    "block_id, farm_id, block_name, weather_active_subs, weather_last_sync_at, "
    "weather_last_failed_at, imagery_active_subs, imagery_last_sync_at, "
    "imagery_failed_24h, weather_failed_24h, weather_running_count, "
    "imagery_running_count, weather_overdue_count, imagery_overdue_count"
)


def _alembic(schema: str) -> Config:
    cfg = Config(str(ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


async def _seed_ingestion_history(session: AsyncSession, *, schema: str) -> UUID:
    """A farm/block with enough attempts + jobs to make the old view fan out.

    The counts matter: the legacy view's row count is
    attempts x attempts x jobs, so >1 of each is what distinguishes a
    correct rewrite from one that happens to agree on trivial data.
    """
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'F1', 'F1', "
            "ST_GeomFromText('MULTIPOLYGON(((31.2 30.0, 31.21 30.0, 31.21 30.01, "
            "31.2 30.01, 31.2 30.0)))', 4326))"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) VALUES "
            "(:id, :fid, 'B1', 'B1', ST_GeomFromText('POLYGON((31.2 30.0, 31.201 30.0, "
            "31.201 30.001, 31.2 30.001, 31.2 30.0))', 4326))"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": block_id, "fid": farm_id},
    )

    weather_sub, imagery_sub = uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO weather_subscriptions (id, block_id, provider_code, "
            " cadence_hours, is_active, last_successful_ingest_at, last_attempted_at) "
            "VALUES (:id, :b, 'open_meteo', 3, true, now() - interval '10 hours', now())"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("b", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": weather_sub, "b": block_id},
    )
    for i, status in enumerate(("succeeded", "failed", "running", "failed")):
        await session.execute(
            text(
                "INSERT INTO weather_ingestion_attempts (id, subscription_id, block_id, "
                " farm_id, provider_code, status, started_at) "
                "VALUES (:id, :s, :b, :f, 'open_meteo', :st, "
                "        now() - make_interval(hours => :h))"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("s", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("f", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": uuid4(),
                "s": weather_sub,
                "b": block_id,
                "f": farm_id,
                "st": status,
                "h": i,
            },
        )

    product_id = (
        await session.execute(text("SELECT id FROM public.imagery_products LIMIT 1"))
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO imagery_aoi_subscriptions (id, block_id, product_id, "
            " cadence_hours, is_active, last_attempted_at) "
            "VALUES (:id, :b, :p, 24, true, now() - interval '2 hours')"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": imagery_sub, "b": block_id, "p": product_id},
    )
    for i, status in enumerate(("succeeded", "failed", "pending", "running", "failed")):
        await session.execute(
            text(
                "INSERT INTO imagery_ingestion_jobs (id, subscription_id, block_id, "
                " product_id, scene_id, scene_datetime, status, requested_at) "
                "VALUES (:id, :s, :b, :p, :scene, now() - make_interval(hours => :h), "
                "        :st, now() - make_interval(hours => :h))"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("s", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": uuid4(),
                "s": imagery_sub,
                "b": block_id,
                "p": product_id,
                "scene": f"S{i}",
                "st": status,
                "h": i,
            },
        )
    await session.commit()
    return block_id


async def _health_rows(session: AsyncSession, *, schema: str) -> list[tuple]:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = (
        await session.execute(
            text(f"SELECT {_HEALTH_COLUMNS} FROM v_block_integration_health ORDER BY block_id")
        )
    ).all()
    # Release the read locks: the alembic DDL below runs on a *different*
    # connection, and DROP VIEW would block on this transaction's
    # AccessShareLock until the test times out.
    await session.commit()
    return [tuple(r) for r in rows]


@pytest.mark.asyncio
async def test_rewritten_views_match_the_originals_and_roundtrip(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="health-roundtrip", name="health-roundtrip", contact_email="ops@rt.test"
    )
    schema = tenant.schema_name

    await _seed_ingestion_history(admin_session, schema=schema)
    after_upgrade = await _health_rows(admin_session, schema=schema)
    assert after_upgrade, "seed produced no health rows"

    cfg = _alembic(schema)

    # Down to 0054: both migrations' downgrade() bodies have to parse and
    # leave the legacy views in place.
    command.downgrade(cfg, "0054")
    legacy = await _health_rows(admin_session, schema=schema)

    # The whole point of the rewrite: same values, different plan.
    assert legacy == after_upgrade, "rewritten views disagree with the originals"

    # And back up — a downgrade you can't re-upgrade from is a trap.
    command.upgrade(cfg, "head")
    after_reupgrade = await _health_rows(admin_session, schema=schema)
    assert after_reupgrade == after_upgrade


@pytest.mark.asyncio
async def test_chunk_settings_applied_and_reverted(admin_session: AsyncSession) -> None:
    """0056 moves new chunks to 30 days / 1 space partition, and back."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="chunk-roundtrip", name="chunk-roundtrip", contact_email="ops@cr.test"
    )
    schema = tenant.schema_name

    async def dims() -> dict[str, int | None]:
        await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        rows = (
            await admin_session.execute(
                text(
                    "SELECT d.column_name, d.time_interval, d.num_partitions "
                    "FROM timescaledb_information.dimensions d "
                    "WHERE d.hypertable_schema = :s "
                    "  AND d.hypertable_name = 'block_index_aggregates'"
                ),
                {"s": schema},
            )
        ).all()
        out: dict[str, int | None] = {}
        for column_name, time_interval, num_partitions in rows:
            if column_name == "time":
                out["days"] = None if time_interval is None else time_interval.days
            else:
                out["partitions"] = num_partitions
        # See _health_rows: alembic runs on another connection and would
        # block on this transaction's locks.
        await admin_session.commit()
        return out

    assert await dims() == {"days": 30, "partitions": 1}

    cfg = _alembic(schema)
    command.downgrade(cfg, "0055")
    assert await dims() == {"days": 7, "partitions": 4}

    command.upgrade(cfg, "head")
    assert await dims() == {"days": 30, "partitions": 1}
