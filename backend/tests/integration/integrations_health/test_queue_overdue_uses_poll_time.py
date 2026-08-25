"""The Queue tab and the Overview tab must give the same overdue answer.

Migration 0042 re-pointed imagery `overdue` from the ingest clock to the poll
clock, and said why: `last_successful_ingest_at` advances only on a real
ingest, so keying overdue on it conflates two clocks.

  * the poll cadence, every 24h, which we control, and
  * the satellite revisit, 2 to 5 days for Sentinel-2 and longer under
    cloud, which we do not.

`IntegrationsHealthService.list_queue` was written after 0042 and kept the
ingest clock. Production, 2026-08-25, tenant agrosina: the Overview tab said
0 overdue and the Queue tab said 38 for the same tenant on the same
afternoon. 36 of those were B-Elkair-Suez blocks polled 17 hours earlier on a
24-hour cadence. The last new scene was four days old, which is an ordinary
week for Sentinel-2.

Weather keeps the ingest clock, exactly as 0042 says: it delivers data every
cadence, so a gap there is a real fault rather than empty sky.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations_health.service import IntegrationsHealthService
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_BOUNDARY = "POLYGON((32.6 30.0,32.7 30.0,32.7 30.1,32.6 30.1,32.6 30.0))"


async def _tenant(admin_session: AsyncSession, slug: str) -> str:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    await admin_session.commit()
    return tenant.schema_name


async def _farm_and_block(admin_session: AsyncSession, schema: str) -> tuple[str, str]:
    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".farms (id, name, code, boundary, boundary_utm) '
            "VALUES (:id, 'F', 'F', "
            f"ST_GeomFromText('{_BOUNDARY}', 4326), "
            f"ST_Transform(ST_GeomFromText('{_BOUNDARY}', 4326), 32636))"
        ),
        {"id": farm_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".blocks (id, farm_id, name, code, boundary, boundary_utm) '
            "VALUES (:id, :farm, 'B', 'B', "
            f"ST_GeomFromText('{_BOUNDARY}', 4326), "
            f"ST_Transform(ST_GeomFromText('{_BOUNDARY}', 4326), 32636))"
        ),
        {"id": block_id, "farm": farm_id},
    )
    await admin_session.commit()
    return str(farm_id), str(block_id)


async def _product_id(admin_session: AsyncSession, code: str) -> UUID:
    row = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = :c"), {"c": code}
        )
    ).first()
    assert row is not None, f"seed is missing imagery product {code!r}"
    return UUID(str(row[0]))


async def _overdue_imagery(admin_session: AsyncSession, schema: str) -> list[dict]:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = await IntegrationsHealthService(tenant_session=admin_session).list_queue(
        kind="imagery", state="overdue"
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return [dict(r) for r in rows]


async def _view_overdue(admin_session: AsyncSession, schema: str) -> int:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    n = (
        await admin_session.execute(
            text("SELECT imagery_overdue_count FROM v_farm_integration_health")
        )
    ).scalar_one()
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return int(n)


@pytest.mark.asyncio
async def test_a_block_polled_on_cadence_is_not_overdue_after_a_revisit_gap(
    admin_session: AsyncSession,
) -> None:
    """B-Elkair-Suez's shape: polled 17h ago, last new scene 4 days ago."""
    schema = await _tenant(admin_session, "queue-poll-clock")
    _, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, "
            " last_attempted_at, last_successful_ingest_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :polled, :ingested)"
        ),
        {
            "id": uuid4(),
            "block": block_id,
            "pid": product_id,
            "polled": datetime.now(UTC) - timedelta(hours=17),
            "ingested": datetime.now(UTC) - timedelta(days=4),
        },
    )
    await admin_session.commit()

    assert await _overdue_imagery(admin_session, schema) == []
    # And the two tabs agree, which is the whole point.
    assert await _view_overdue(admin_session, schema) == 0


@pytest.mark.asyncio
async def test_a_block_the_poller_stopped_visiting_is_overdue(
    admin_session: AsyncSession,
) -> None:
    """The direction that matters. A poll clock two days behind a 24h cadence
    is a real integration fault, and both reads must say so."""
    schema = await _tenant(admin_session, "queue-poll-stopped")
    _, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, "
            " last_attempted_at, last_successful_ingest_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :polled, :ingested)"
        ),
        {
            "id": uuid4(),
            "block": block_id,
            "pid": product_id,
            "polled": datetime.now(UTC) - timedelta(days=2),
            "ingested": datetime.now(UTC) - timedelta(days=2),
        },
    )
    await admin_session.commit()

    assert len(await _overdue_imagery(admin_session, schema)) == 1
    assert await _view_overdue(admin_session, schema) == 1
