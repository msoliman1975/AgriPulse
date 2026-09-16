"""The Python clock and the SQL clock must report the same instant.

`app.shared.clock` moves the Python side. `public.app_now()` moves the SQL
side by reading the `agripulse.now` setting, which `app.shared.db.session`
writes on every transaction while a replay is running.

If the two disagree, a demo-history replay produces rows where some
columns are months old and others are today, and nothing raises an error.
These tests are what catches that.

One rule these tests exist to pin down: the clock is written when a
transaction begins, so a replay must enter `clock.simulate(...)` before
any statement opens one. Entering it half way through a transaction has
no effect on the SQL side, and `test_the_clock_must_be_set_before_the_
transaction_begins` records that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.shared import clock

pytestmark = pytest.mark.integration

AT = datetime(2025, 3, 4, 10, 0, tzinfo=UTC)

PROBE_TABLE = """
CREATE TABLE public.zz_clock_probe (
    id int PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT public.app_now(),
    updated_at timestamptz NOT NULL DEFAULT public.app_now()
)
"""

PROBE_TRIGGER = (
    "CREATE TRIGGER touch BEFORE UPDATE ON public.zz_clock_probe "
    "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
)


async def _scalar(session, sql: str, **params):  # type: ignore[no-untyped-def]
    return (await session.execute(text(sql), params)).scalar_one()


async def _make_probe_table(session) -> None:  # type: ignore[no-untyped-def]
    """Build the probe table and commit, so the next block starts clean.

    The commit matters. `agripulse.now` is written when a transaction
    begins, so the simulated block has to open its own.
    """
    await session.execute(text("DROP TABLE IF EXISTS public.zz_clock_probe"))
    await session.execute(text(PROBE_TABLE))
    await session.execute(text(PROBE_TRIGGER))
    await session.commit()


async def _drop_probe_table(session) -> None:  # type: ignore[no-untyped-def]
    await session.rollback()
    await session.execute(text("DROP TABLE IF EXISTS public.zz_clock_probe"))
    await session.commit()


async def test_app_now_returns_the_real_time_when_no_replay_is_running(
    admin_session,  # type: ignore[no-untyped-def]
) -> None:
    value = await _scalar(admin_session, "SELECT public.app_now()")
    assert abs((value - datetime.now(UTC)).total_seconds()) < 60


async def test_app_now_follows_the_simulated_clock(admin_session) -> None:  # type: ignore[no-untyped-def]
    with clock.simulate(AT):
        value = await _scalar(admin_session, "SELECT public.app_now()")
    assert value == AT


async def test_python_and_sql_agree_under_a_simulated_clock(
    admin_session,  # type: ignore[no-untyped-def]
) -> None:
    with clock.simulate(AT):
        in_sql = await _scalar(admin_session, "SELECT public.app_now()")
        in_python = clock.now()
    assert in_sql == in_python


async def test_no_public_column_still_defaults_to_the_fixed_clock(
    admin_session,  # type: ignore[no-untyped-def]
) -> None:
    """Migration 0089 must have reached every column, not most of them.

    A stored default is resolved when the column is created, so one that
    keeps calling `now()` writes today's date into a replayed row and
    reports no error.
    """
    result = await admin_session.execute(
        text(
            """
            SELECT c.relname || '.' || a.attname
              FROM pg_attrdef d
              JOIN pg_class c ON c.oid = d.adrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a
                ON a.attrelid = d.adrelid AND a.attnum = d.adnum
             WHERE n.nspname = 'public'
               AND pg_get_expr(d.adbin, d.adrelid) IN ('now()', 'pg_catalog.now()')
             ORDER BY 1
            """
        )
    )
    assert list(result.scalars().all()) == []


async def test_a_column_default_writes_the_simulated_time(admin_session) -> None:  # type: ignore[no-untyped-def]
    """The insert path: `created_at` comes from the column default."""
    await _make_probe_table(admin_session)
    try:
        with clock.simulate(AT):
            await admin_session.execute(text("INSERT INTO public.zz_clock_probe (id) VALUES (1)"))
            created = await _scalar(
                admin_session,
                "SELECT created_at FROM public.zz_clock_probe WHERE id = 1",
            )
        assert created == AT
    finally:
        await _drop_probe_table(admin_session)


async def test_the_update_trigger_writes_the_simulated_time(admin_session) -> None:  # type: ignore[no-untyped-def]
    """The update path: `public.set_updated_at` runs inside Postgres.

    This is the half a Python-only clock cannot reach.
    """
    later = AT + timedelta(days=30)
    await _make_probe_table(admin_session)
    try:
        with clock.simulate(AT):
            await admin_session.execute(text("INSERT INTO public.zz_clock_probe (id) VALUES (1)"))
            await admin_session.commit()

        with clock.simulate(later):
            await admin_session.execute(
                text("UPDATE public.zz_clock_probe SET id = 1 WHERE id = 1")
            )
            touched = await _scalar(
                admin_session,
                "SELECT updated_at FROM public.zz_clock_probe WHERE id = 1",
            )
            await admin_session.commit()
        assert touched == later
    finally:
        await _drop_probe_table(admin_session)


async def test_the_clock_must_be_set_before_the_transaction_begins(
    admin_session,  # type: ignore[no-untyped-def]
) -> None:
    """Entering `simulate` mid-transaction does not move the SQL side.

    This is a limit of the design, not a defect, and it is written down
    here so a replay is built the right way round. `agripulse.now` is
    written by an `after_begin` hook, which has already run by the time a
    later statement enters the block.
    """
    await _scalar(admin_session, "SELECT 1")  # opens the transaction

    with clock.simulate(AT):
        in_sql = await _scalar(admin_session, "SELECT public.app_now()")
        assert clock.now() == AT

    assert in_sql != AT
    assert abs((in_sql - datetime.now(UTC)).total_seconds()) < 60
    await admin_session.rollback()


async def test_the_simulated_clock_does_not_survive_the_transaction(
    admin_session,  # type: ignore[no-untyped-def]
) -> None:
    """A pooled connection must not carry the setting to the next caller.

    `set_config(..., TRUE)` is transaction-local. Were it session-local,
    one replay would backdate every later request that happened to be
    handed the same connection.
    """
    with clock.simulate(AT):
        assert await _scalar(admin_session, "SELECT public.app_now()") == AT
    await admin_session.commit()

    value = await _scalar(admin_session, "SELECT public.app_now()")
    assert abs((value - datetime.now(UTC)).total_seconds()) < 60
    assert await _scalar(admin_session, "SELECT current_setting('agripulse.now', true)") in (
        None,
        "",
    )
    await admin_session.rollback()
