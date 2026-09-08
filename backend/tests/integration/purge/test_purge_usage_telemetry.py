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
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.purge.engine import PurgeEngine, refresh_public_caggs
from app.shared.purge.registry import PUBLIC_CAGGS

pytestmark = [pytest.mark.integration]

_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, schema_version, session_id, user_id, tenant_id, actor_role,
        is_platform_staff, event_name, feature, route, flow, step, outcome,
        duration_ms, locale, app_version, props
    ) VALUES (
        :time, :id, 1, :session_id, :user_id, :tenant_id, 'Agronomist',
        false, :event_name, 'insights', '/insights/:farmId', :flow, :step, 'ok',
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
            "flow": "farm_onboarding",
            "step": None,
        },
    ]


async def _autocommit(session: AsyncSession):
    engine = session.get_bind().engine  # type: ignore[union-attr]
    conn = await engine.connect()
    await conn.execution_options(isolation_level="AUTOCOMMIT")
    return conn


async def _refresh_all(session: AsyncSession, around: datetime) -> None:
    conn = await _autocommit(session)
    try:
        for view, _src in PUBLIC_CAGGS:
            await conn.execute(
                text(f"CALL refresh_continuous_aggregate('public.\"{view}\"', :s, :e)"),
                {"s": around - timedelta(days=2), "e": around + timedelta(days=2)},
            )
    finally:
        await conn.close()


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


async def _purge(session: AsyncSession, tenant_id: UUID) -> list[str]:
    """Run the tenant public-schema delete and the CAGG phase after it."""
    engine = PurgeEngine(session)
    report = await engine.delete_tenant_public([tenant_id])
    await session.commit()
    # Post-commit, on its own autocommit connection — exactly as the purge
    # service does it, because refresh_continuous_aggregate cannot run inside a
    # transaction block.
    from app.core.settings import get_settings

    return await refresh_public_caggs(
        engine_url=str(get_settings().database_url),
        window=report.public_cagg_range,
    )


@pytest.mark.asyncio
async def test_recent_telemetry_dies_with_the_tenant(admin_session: AsyncSession) -> None:
    tenant_id = uuid4()
    when = datetime.now(UTC) - timedelta(days=1)
    await admin_session.execute(_INSERT, _events(tenant_id, when))
    await admin_session.commit()
    await _refresh_all(admin_session, when)

    assert await _raw_rows(admin_session, tenant_id) == 2
    before = await _aggregate_rows(admin_session, tenant_id)
    assert all(n > 0 for n in before.values()), (
        f"aggregates were already empty before the purge ({before}) — the test "
        "would pass without proving anything"
    )

    refreshed = await _purge(admin_session, tenant_id)

    assert sorted(refreshed) == sorted(v for v, _ in PUBLIC_CAGGS)
    assert await _raw_rows(admin_session, tenant_id) == 0
    after = await _aggregate_rows(admin_session, tenant_id)
    assert after == dict.fromkeys(after, 0), (
        f"a purged tenant is still visible in the aggregates: {after}. The raw "
        "rows are gone, so the orphan scanner reports clean and the dashboard "
        "still shows this tenant."
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
    await _refresh_all(admin_session, when)

    # Force compression on the chunk holding these rows rather than waiting for
    # the background policy, which will not have run inside a test session.
    conn = await _autocommit(admin_session)
    compressed = 0
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

    assert compressed > 0, (
        "no chunk older than 14 days was compressed, so this test would exercise "
        "the same uncompressed path as the one above and prove nothing"
    )

    refreshed = await _purge(admin_session, tenant_id)

    assert sorted(refreshed) == sorted(v for v, _ in PUBLIC_CAGGS)
    assert await _raw_rows(admin_session, tenant_id) == 0, (
        "DELETE did not reach the compressed chunk — an old tenant cannot be "
        "fully purged. Fallback is decompress_chunk before the delete, or "
        "dropping compression on this table."
    )
    after = await _aggregate_rows(admin_session, tenant_id)
    assert after == dict.fromkeys(after, 0)


@pytest.mark.asyncio
async def test_a_tenant_with_no_telemetry_skips_the_refresh(
    admin_session: AsyncSession,
) -> None:
    """No window means no rows to recompute. Refreshing 24 months of buckets
    "just in case" on every purge is not a safe default."""
    engine = PurgeEngine(admin_session)
    report = await engine.delete_tenant_public([uuid4()])
    assert report.public_cagg_range is None

    from app.core.settings import get_settings

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
