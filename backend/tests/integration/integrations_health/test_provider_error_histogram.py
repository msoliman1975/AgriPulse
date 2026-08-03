"""Cross-tenant provider failure-cause histogram (PR-IH10) actually counts.

Two defects shipped together and hid each other:

1. The imagery branch filtered on ``public.imagery_products.provider_code``
   — a column that has never existed. Products key on ``provider_id``; only
   ``imagery_providers`` has a ``code``. Every imagery provider raised
   ``UndefinedColumn``.

2. The per-tenant ``except Exception: continue`` was supposed to make that
   survivable, but the failing statement aborts the *whole* session, so the
   ``finally``'s ``SET LOCAL search_path`` then raised
   ``InFailedSqlTransaction`` — out of the ``finally``, past the ``except``.
   The endpoint 500'd and the Providers tab rendered
   "Could not load integration health."

So the swallow has to be tested by its *outcome*: a broken tenant must be
skipped while the healthy ones still report, and the healthy path must
return real counts rather than the empty list a still-broken query yields.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations_health.providers_service import ProviderHealthService
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


async def _seed_tenant_with_failures(
    session: AsyncSession,
    *,
    weather_error_code: str,
    imagery_error_code: str,
) -> dict[str, Any]:
    """A tenant with one failed weather attempt and one failed imagery job."""
    slug = f"ihh-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    schema = tenant.schema_name

    farm_id, block_id = uuid4(), uuid4()
    product_id: UUID = (
        await session.execute(text("SELECT id FROM public.imagery_products WHERE code = 's2_l2a'"))
    ).scalar_one()

    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'IH', 'IH farm', "
            "ST_GeomFromText('POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,"
            "31.2 30.0))', 4326))"
        ),
        {"id": str(farm_id)},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary) VALUES (:id, :fid, 'B1', "
            "'B1', ST_GeomFromText('POLYGON((31.201 30.001,31.205 30.001,31.205 30.005,"
            "31.201 30.005,31.201 30.001))', 4326))"
        ),
        {"id": str(block_id), "fid": str(farm_id)},
    )

    weather_sub_id = (
        await session.execute(
            text(
                "INSERT INTO weather_subscriptions (block_id, provider_code, cadence_hours, "
                "is_active) VALUES (:bid, 'open_meteo', 6, TRUE) RETURNING id"
            ),
            {"bid": str(block_id)},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO weather_ingestion_attempts "
            "(subscription_id, block_id, farm_id, provider_code, status, error_code, "
            " started_at, completed_at) "
            "VALUES (:sid, :bid, :fid, 'open_meteo', 'failed', :ec, now(), now())"
        ),
        {
            "sid": str(weather_sub_id),
            "bid": str(block_id),
            "fid": str(farm_id),
            "ec": weather_error_code,
        },
    )

    imagery_sub_id = (
        await session.execute(
            text(
                "INSERT INTO imagery_aoi_subscriptions (block_id, product_id, cadence_hours, "
                "is_active) VALUES (:bid, :pid, 24, TRUE) RETURNING id"
            ),
            {"bid": str(block_id), "pid": str(product_id)},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO imagery_ingestion_jobs "
            "(subscription_id, block_id, product_id, scene_id, scene_datetime, status, "
            " error_code, requested_at) "
            "VALUES (:sid, :bid, :pid, :scene, now(), 'failed', :ec, now())"
        ),
        {
            "sid": str(imagery_sub_id),
            "bid": str(block_id),
            "pid": str(product_id),
            "scene": f"S2_{uuid4().hex[:10]}",
            "ec": imagery_error_code,
        },
    )

    await session.execute(text("SET search_path TO public"))
    await session.commit()
    return {"tenant_id": tenant.tenant_id, "schema": schema}


@pytest.mark.asyncio
async def test_imagery_histogram_counts_failures(admin_session: AsyncSession) -> None:
    """The imagery branch must join products → providers, not a phantom column.

    Before the fix this raised UndefinedColumn on every tenant, so the
    endpoint 500'd. A regression that only re-broke the join (without
    re-breaking the swallow) would return [] — hence asserting on the count,
    not on the absence of an exception.
    """
    code = f"test_img_{uuid4().hex[:8]}"
    await _seed_tenant_with_failures(
        admin_session, weather_error_code="test_unused", imagery_error_code=code
    )

    service = ProviderHealthService(public_session=admin_session)
    # s2_l2a is seeded under the 'sentinel_hub' provider by public/0008.
    rows = await service.cross_tenant_error_histogram(
        provider_kind="imagery", provider_code="sentinel_hub", hours=24
    )

    by_code = {r["error_code"]: r["count"] for r in rows}
    assert by_code.get(code) == 1, rows


@pytest.mark.asyncio
async def test_weather_histogram_counts_failures(admin_session: AsyncSession) -> None:
    code = f"test_wx_{uuid4().hex[:8]}"
    await _seed_tenant_with_failures(
        admin_session, weather_error_code=code, imagery_error_code="test_unused"
    )

    service = ProviderHealthService(public_session=admin_session)
    rows = await service.cross_tenant_error_histogram(
        provider_kind="weather", provider_code="open_meteo", hours=24
    )

    by_code = {r["error_code"]: r["count"] for r in rows}
    assert by_code.get(code) == 1, rows


@pytest.mark.asyncio
async def test_broken_tenant_is_skipped_not_fatal(admin_session: AsyncSession) -> None:
    """A tenant whose schema is mid-migration must not take the rollup down.

    Simulated by dropping the table the histogram reads. Without the
    per-tenant SAVEPOINT the aborted session poisons the `finally`'s
    search_path reset and the whole call raises.
    """
    code = f"test_img_{uuid4().hex[:8]}"
    healthy = await _seed_tenant_with_failures(
        admin_session, weather_error_code="test_unused", imagery_error_code=code
    )
    broken = await _seed_tenant_with_failures(
        admin_session, weather_error_code="test_unused", imagery_error_code="test_unused"
    )
    await admin_session.execute(
        text(f'DROP TABLE "{broken["schema"]}".imagery_ingestion_jobs CASCADE')
    )
    await admin_session.commit()

    service = ProviderHealthService(public_session=admin_session)
    rows = await service.cross_tenant_error_histogram(
        provider_kind="imagery", provider_code="sentinel_hub", hours=24
    )

    # The healthy tenant still reports; the broken one is simply absent.
    by_code = {r["error_code"]: r["count"] for r in rows}
    assert by_code.get(code) == 1, (healthy, rows)

    # And the session is still usable afterwards — proof the transaction
    # was never left in the aborted state.
    assert (await admin_session.execute(text("SELECT 1"))).scalar_one() == 1
