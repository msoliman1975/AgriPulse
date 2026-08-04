"""TEL-1: the `public.usage_events` hypertable is real and behaves.

Runs against the real TimescaleDB container, not a mock. That is deliberate on
two counts:

1. The batch-insert path binds timestamps and UUIDs. Passing `.isoformat()`
   strings through a `CAST` is the bug family behind #331 / #332 / #335, and it
   only ever reproduces against a real asyncpg connection. `test_batch_insert_*`
   binds real `datetime` / `UUID` objects and would fail loudly if someone
   "helpfully" stringifies them later.
2. `test_delete_from_compressed_chunk` settles an open question early rather
   than at TEL-6b: telemetry must not survive a tenant purge, the table
   compresses at 14 days, and whether `DELETE` works on a compressed chunk
   depends on the TimescaleDB version. Better to learn that here.

None of these are skipped. Five of six backfill tests were `skip`ped, which is
how #331 shipped broken.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

_TABLE = "public.usage_events"

_EXPECTED_INDEXES = {
    "ix_usage_events_tenant_time",
    "ix_usage_events_user_time",
    "ix_usage_events_name_time",
    "ix_usage_events_feature_time",
    "ix_usage_events_session",
    "ix_usage_events_correlation",
}

_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, session_id, user_id, tenant_id, actor_role,
        is_platform_staff, event_name, feature, route, farm_id,
        outcome, duration_ms, correlation_id, locale, props
    ) VALUES (
        :time, :id, :session_id, :user_id, :tenant_id, :actor_role,
        :is_platform_staff, :event_name, :feature, :route, :farm_id,
        :outcome, :duration_ms, :correlation_id, :locale, CAST(:props AS jsonb)
    )
    ON CONFLICT (time, id) DO NOTHING
    """
)
# `props` is bound as a JSON *string* with an explicit CAST. That is the correct
# wire form for jsonb — unlike the date/uuid case in #331, where a string bind
# through a CAST was the bug. Postfix `:props::jsonb` would not survive text().


def _event(
    *,
    when: datetime,
    tenant_id: UUID,
    event_id: UUID | None = None,
    session_id: UUID | None = None,
) -> dict[str, object]:
    """One bind-parameter set. Real datetime/UUID objects, never strings."""
    return {
        "time": when,
        "id": event_id or uuid4(),
        "session_id": session_id or uuid4(),
        "user_id": uuid4(),
        "tenant_id": tenant_id,
        "actor_role": "Agronomist",
        "is_platform_staff": False,
        "event_name": "page_view",
        "feature": "insights",
        "route": "/insights/:farmId",
        "farm_id": uuid4(),
        "outcome": "ok",
        "duration_ms": 4200,
        "correlation_id": uuid4(),
        "locale": "ar",
        "props": '{"index_code": "NDVI"}',
    }


# --- shape -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_a_hypertable(admin_session: AsyncSession) -> None:
    row = (
        await admin_session.execute(
            text(
                """
                SELECT hypertable_schema, hypertable_name
                  FROM timescaledb_information.hypertables
                 WHERE hypertable_schema = 'public'
                   AND hypertable_name = 'usage_events'
                """
            )
        )
    ).one_or_none()
    assert row is not None, (
        "usage_events is not a hypertable — create_hypertable() did not run. "
        "Without it there is no compression, no retention, and no chunk pruning."
    )


@pytest.mark.asyncio
async def test_constraint_names_are_not_convention_doubled(
    admin_session: AsyncSession,
) -> None:
    """The names must be literal, not `ck_usage_events_ck_usage_events_outcome`.

    The metadata naming convention templates `%(constraint_name)s`, so declaring
    a constraint inside `op.create_table` with an explicit name doubles it —
    0030, 0036 and tenant/0054 all carry scar tissue from this. 0049 uses raw
    ALTER TABLE to dodge it; this asserts the dodge worked.
    """
    names = {
        r[0]
        for r in await admin_session.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                 WHERE conrelid = 'public.usage_events'::regclass
                """
            )
        )
    }
    assert "uq_usage_events_time_id" in names, names
    assert "ck_usage_events_outcome" in names, names
    doubled = {n for n in names if "usage_events_ck_" in n or "usage_events_uq_" in n}
    assert not doubled, f"naming convention doubled these constraint names: {doubled}"


@pytest.mark.asyncio
async def test_all_indexes_exist(admin_session: AsyncSession) -> None:
    found = {
        r[0]
        for r in await admin_session.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                "AND tablename='usage_events'"
            )
        )
    }
    missing = _EXPECTED_INDEXES - found
    assert not missing, f"missing indexes: {sorted(missing)}"


@pytest.mark.asyncio
async def test_compression_and_retention_policies_exist(
    admin_session: AsyncSession,
) -> None:
    """Retention is enforced by a policy, not by intent."""
    procs = {
        r[0]
        for r in await admin_session.execute(
            text(
                """
                SELECT proc_name FROM timescaledb_information.jobs
                 WHERE hypertable_schema = 'public'
                   AND hypertable_name = 'usage_events'
                """
            )
        )
    }
    assert "policy_compression" in procs, procs
    assert "policy_retention" in procs, procs


@pytest.mark.asyncio
async def test_outcome_check_rejects_unknown_value(admin_session: AsyncSession) -> None:
    tenant_id = uuid4()
    bad = _event(when=datetime.now(UTC), tenant_id=tenant_id)
    bad["outcome"] = "sort-of-fine"
    with pytest.raises(Exception, match="ck_usage_events_outcome"):
        await admin_session.execute(_INSERT, bad)
    await admin_session.rollback()


# --- write path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_insert_binds_real_objects(admin_session: AsyncSession) -> None:
    """executemany with real datetime/UUID binds — the #331 regression guard."""
    tenant_id = uuid4()
    now = datetime.now(UTC)
    batch = [_event(when=now - timedelta(seconds=i), tenant_id=tenant_id) for i in range(50)]

    await admin_session.execute(_INSERT, batch)
    await admin_session.commit()

    row = (
        await admin_session.execute(
            text(
                "SELECT count(*), min(props->>'index_code') "
                "FROM public.usage_events WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
    ).one()
    assert row[0] == 50
    assert row[1] == "NDVI", "props did not round-trip as jsonb"


@pytest.mark.asyncio
async def test_duplicate_beacon_is_a_noop(admin_session: AsyncSession) -> None:
    """A resent beacon must not double-count. (time, id) is the conflict target."""
    tenant_id = uuid4()
    event_id, session_id = uuid4(), uuid4()
    when = datetime.now(UTC)
    payload = _event(when=when, tenant_id=tenant_id, event_id=event_id, session_id=session_id)

    await admin_session.execute(_INSERT, payload)
    await admin_session.execute(_INSERT, dict(payload))  # same (time, id)
    await admin_session.commit()

    n = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.usage_events WHERE id = :i"),
            {"i": event_id},
        )
    ).scalar_one()
    assert n == 1, "duplicate (time, id) was inserted twice — idempotency is broken"


# --- purge completeness ----------------------------------------------------


@pytest.mark.asyncio
async def test_delete_from_compressed_chunk(admin_session: AsyncSession) -> None:
    """Telemetry must not survive a tenant purge — including once compressed.

    The table compresses at 14 days, so purging any tenant older than a
    fortnight means deleting from a compressed chunk. If this ever fails, an old
    tenant cannot be fully purged and the decision in the plan is unenforceable;
    the fallback is an explicit `decompress_chunk` before the delete.

    `compress_chunk` runs on its own AUTOCOMMIT connection: it cannot be relied
    on inside the caller's transaction, and a failure mid-transaction would
    abort the session and take the assertions with it.
    """
    from app.shared.db.session import get_engine

    tenant_id = uuid4()
    old = datetime.now(UTC) - timedelta(days=90)
    await admin_session.execute(
        _INSERT, [_event(when=old - timedelta(minutes=i), tenant_id=tenant_id) for i in range(5)]
    )
    await admin_session.commit()

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        compressed = list(
            await conn.execute(
                text(
                    "SELECT compress_chunk(c, if_not_compressed => TRUE) "
                    "FROM show_chunks('public.usage_events', "
                    "older_than => INTERVAL '30 days') AS c"
                )
            )
        )
    assert compressed, (
        "no chunk older than 30 days to compress — the fixture rows did not land "
        "where expected, so this test would pass vacuously"
    )

    # The actual question: can purge delete these rows now?
    await admin_session.execute(
        text("DELETE FROM public.usage_events WHERE tenant_id = :t"), {"t": tenant_id}
    )
    await admin_session.commit()

    remaining = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.usage_events WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()
    assert remaining == 0, (
        "rows survived a DELETE on a compressed chunk — a tenant older than the "
        "14-day compression threshold cannot be fully purged. Add an explicit "
        "decompress_chunk to the purge engine, or drop compression on this table."
    )
