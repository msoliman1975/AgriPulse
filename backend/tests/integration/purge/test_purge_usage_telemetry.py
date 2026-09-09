"""TEL-6b: telemetry does not survive a tenant purge — rows AND aggregates.

Acceptance criterion 10 of the telemetry plan. The interesting failure is not
the rows: `DELETE FROM usage_events WHERE tenant_id = ...` is registered in the
manifest and works. It is the two continuous aggregates.

`usage_daily` and `usage_flow_daily` GROUP BY `tenant_id` and run with real-time
aggregation on, so the already-materialised daily buckets keep serving a purged
tenant's numbers to every chart after the raw rows are gone. Nothing catches
that on its own: the orphan scanner inspects tables, not aggregates, so the
purge reports success and the tenant is still visible on the dashboard.

Two cases matter and they fail differently:

  * a tenant whose events are recent — the plain case;
  * a tenant whose events predate the 14-day compression threshold, where the
    DELETE has to reach into a compressed chunk. Whether that works depends on
    the TimescaleDB version behind the production image, so it is asserted
    rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.settings import get_settings
from app.shared.purge.engine import PurgeEngine, PurgeReport, refresh_public_caggs
from app.shared.purge.registry import PUBLIC_CAGGS

pytestmark = [pytest.mark.integration]

# `route` is a BIND, not a literal. A route template contains ":farmId", and
# SQLAlchemy's text() parses ":name" inside the string as a bind parameter — so
# an inlined template turns into a missing-parameter error at execute time.
# Same family as the CAST-and-string-bind bugs: the SQL looks right and fails
# only when it runs.
_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, schema_version, session_id, user_id, tenant_id, actor_role,
        is_platform_staff, event_name, feature, route, flow, step, outcome,
        duration_ms, locale, app_version, props
    ) VALUES (
        :time, :id, 1, :session_id, :user_id, :tenant_id, 'Agronomist',
        false, :event_name, 'insights', :route, :flow, :step, 'ok',
        1000, 'en', 'purgetest', '{}'::jsonb
    )
    """
)


def _events(tenant_id: UUID, when: datetime) -> list[dict[str, Any]]:
    session_id = uuid4()
    user_id = uuid4()
    return [
        {
            "time": when,
            "id": uuid4(),
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "event_name": "page_view",
            "route": "/insights/:farmId",
            "flow": None,
            "step": None,
        },
        {
            "time": when + timedelta(minutes=1),
            "id": uuid4(),
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "event_name": "flow_start",
            "route": "/insights/:farmId",
            "flow": "farm_onboarding",
            "step": None,
        },
    ]


def _autocommit_engine():
    """A dedicated autocommit engine.

    Not `session.get_bind()`: on an AsyncSession that returns a sync-style bind
    and awaiting IO through it raises MissingGreenlet. `compress_chunk` and
    `refresh_continuous_aggregate` also cannot run inside a transaction block,
    so a separate autocommit connection is required regardless.
    """
    return create_async_engine(str(get_settings().database_url), isolation_level="AUTOCOMMIT")


async def _refresh_all(around: datetime) -> None:
    engine = _autocommit_engine()
    try:
        async with engine.connect() as conn:
            for view, _src in PUBLIC_CAGGS:
                await conn.execute(
                    text(
                        f"CALL refresh_continuous_aggregate('public.\"{view}\"', CAST(:s AS timestamptz), CAST(:e AS timestamptz))"
                    ),
                    {"s": around - timedelta(days=2), "e": around + timedelta(days=2)},
                )
    finally:
        await engine.dispose()


async def _aggregate_rows(session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Row counts for this tenant in each aggregate. This is the assertion the
    orphan scanner cannot make."""
    counts: dict[str, int] = {}
    for view, _src in PUBLIC_CAGGS:
        counts[view] = int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM public.{view} WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )
    return counts


async def _raw_rows(session: AsyncSession, tenant_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM public.usage_events WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    )


async def _purge(session: AsyncSession, tenant_id: UUID) -> tuple[list[str], PurgeReport]:
    """Run the tenant public-schema delete and the CAGG phase after it.

    Returns the report as well as the refreshed views. The window is captured
    inside `delete_tenant_public`, so when the refresh does nothing there are two
    possible causes — the capture found no rows, or the refresh itself failed —
    and the caller needs the report to tell them apart.
    """
    engine = PurgeEngine(session)
    report = await engine.delete_tenant_public([tenant_id])
    await session.commit()
    # Post-commit, on its own autocommit connection — exactly as the purge
    # service does it, because refresh_continuous_aggregate cannot run inside a
    # transaction block.
    refreshed = await refresh_public_caggs(
        engine_url=str(get_settings().database_url),
        window=report.public_cagg_range,
    )
    return refreshed, report


@pytest.mark.asyncio
async def test_recent_telemetry_dies_with_the_tenant(admin_session: AsyncSession) -> None:
    tenant_id = uuid4()
    when = datetime.now(UTC) - timedelta(days=1)
    await admin_session.execute(_INSERT, _events(tenant_id, when))
    await admin_session.commit()
    await _refresh_all(when)

    assert await _raw_rows(admin_session, tenant_id) == 2
    before = await _aggregate_rows(admin_session, tenant_id)
    assert all(n > 0 for n in before.values()), (
        f"aggregates were already empty before the purge ({before}) — the test "
        "would pass without proving anything"
    )

    refreshed, report = await _purge(admin_session, tenant_id)

    # Outcome first, mechanism second. The property this test exists to prove is
    # "no row attributable to the tenant survives"; which views got refreshed is
    # an implementation detail, and asserting it first hid the real answer.
    assert await _raw_rows(admin_session, tenant_id) == 0
    after = await _aggregate_rows(admin_session, tenant_id)
    assert after == dict.fromkeys(after, 0), (
        f"a purged tenant is still visible in the aggregates: {after}. The raw "
        "rows are gone, so the orphan scanner reports clean and the dashboard "
        "still shows this tenant."
    )

    # Mechanism, checked last and reported separately. An empty window means the
    # pre-delete capture found nothing; a captured window with no refreshed views
    # means the refresh itself failed. The two need different fixes.
    assert report.public_cagg_range is not None, (
        "the pre-delete capture found no usage_events for this tenant, so the "
        "refresh was skipped — even though the rows were there a moment earlier"
    )
    assert sorted(refreshed) == sorted(v for v, _ in PUBLIC_CAGGS), (
        f"window was captured ({report.public_cagg_range}) but these views came "
        f"back refreshed: {refreshed}. The refresh call itself failed."
    )


@pytest.mark.asyncio
async def test_telemetry_older_than_the_compression_threshold_also_dies(
    admin_session: AsyncSession,
) -> None:
    """The risky case. `usage_events` compresses at 14 days, so purging an
    older tenant deletes from a COMPRESSED chunk. Whether that works depends on
    the extension version behind the production image, and `audit_events` has
    the same shape but may never have been exercised on a genuinely old tenant.
    """
    tenant_id = uuid4()
    when = datetime.now(UTC) - timedelta(days=45)
    await admin_session.execute(_INSERT, _events(tenant_id, when))
    await admin_session.commit()
    await _refresh_all(when)

    # Force compression on the chunk holding these rows rather than waiting for
    # the background policy, which will not have run inside a test session.
    engine = _autocommit_engine()
    compressed = 0
    conn = await engine.connect()
    try:
        chunks = (
            await conn.execute(
                text(
                    """
                    SELECT c.chunk_schema || '.' || c.chunk_name
                      FROM timescaledb_information.chunks c
                     WHERE c.hypertable_schema = 'public'
                       AND c.hypertable_name = 'usage_events'
                       AND c.range_end <= :cutoff
                       AND NOT c.is_compressed
                    """
                ),
                {"cutoff": datetime.now(UTC) - timedelta(days=14)},
            )
        ).all()
        for (chunk,) in chunks:
            await conn.execute(text("SELECT compress_chunk(:c)"), {"c": chunk})
            compressed += 1
    finally:
        await conn.close()
        await engine.dispose()

    assert compressed > 0, (
        "no chunk older than 14 days was compressed, so this test would exercise "
        "the same uncompressed path as the one above and prove nothing"
    )

    refreshed, report = await _purge(admin_session, tenant_id)

    # The assertion this whole test exists for, checked before anything else.
    assert await _raw_rows(admin_session, tenant_id) == 0, (
        "DELETE did not reach the compressed chunk — an old tenant cannot be "
        "fully purged. Fallback is decompress_chunk before the delete, or "
        "dropping compression on this table."
    )
    after = await _aggregate_rows(admin_session, tenant_id)
    assert after == dict.fromkeys(after, 0)

    assert report.public_cagg_range is not None
    assert sorted(refreshed) == sorted(v for v, _ in PUBLIC_CAGGS), (
        f"window was captured ({report.public_cagg_range}) but these views came "
        f"back refreshed: {refreshed}. The refresh call itself failed."
    )


@pytest.mark.asyncio
async def test_a_tenant_with_no_telemetry_skips_the_refresh(
    admin_session: AsyncSession,
) -> None:
    """No window means no rows to recompute. Refreshing 24 months of buckets
    "just in case" on every purge is not a safe default."""
    engine = PurgeEngine(admin_session)
    report = await engine.delete_tenant_public([uuid4()])
    assert report.public_cagg_range is None
    assert (
        await refresh_public_caggs(
            engine_url=str(get_settings().database_url),
            window=report.public_cagg_range,
        )
        == []
    )


@pytest.mark.asyncio
async def test_usage_events_is_registered_for_both_owners() -> None:
    """The manifest entries are what make the delete happen at all; without
    them the purge guard fails CI and the rows survive."""
    from app.shared.purge.registry import FARM_OWNED, TENANT_PUBLIC_OWNED

    assert any(
        t.table == "usage_events" and t.owner_column == "tenant_id" and t.schema == "public"
        for t in TENANT_PUBLIC_OWNED
    )
    assert any(
        t.table == "usage_events" and t.owner_column == "farm_id" and t.schema == "public"
        for t in FARM_OWNED
    )
