"""Overdue must not count the block rows the sweeps deliberately skip.

Both sweeps stop polling a block subscription once its farm acquires on its
own behalf:

* `WeatherRepository.list_due_farm_provider_pairs` drops a block weather row
  whose farm has an active farm row for the same provider.
* `ImageryRepository.list_active_subscriptions_due` drops a block imagery row
  whose farm fetches that product as one AOI (`fetch_farm_aoi`).

Nothing advances those rows' watermarks afterwards, so before migration 0085
`v_farm_integration_health` counted every one of them as overdue for ever.

Production, tenant agrosina, 2026-08-25:

  Bashier Elkhier   weather synced 04:33 that morning through its farm row,
                    imagery through two farm-AOI subscriptions
    -> the Overview tab read "36 overdue" weather and "36 overdue" imagery.

  B-Elkair-Suez     weather synced 06:01 that morning
    -> "36 overdue" weather, same cause.

The Queue tab already had the weather half right, so the same page gave two
different answers depending on which tab was open.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _health(admin_session: AsyncSession, schema: str) -> dict[str, Any]:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    row = (
        (await admin_session.execute(text("SELECT * FROM v_farm_integration_health")))
        .mappings()
        .one()
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return dict(row)


_LONG_AGO = datetime(2026, 8, 13, 17, 38, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_block_weather_row_superseded_by_a_farm_row_is_not_overdue(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "overdue-weather-cutover")
    farm_id, block_id = await _farm_and_block(admin_session, schema)

    # The abandoned block row: active, frozen at the cut-over.
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', 3, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "old": _LONG_AGO},
    )
    # The farm row now doing the work, synced minutes ago.
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', 3, TRUE, :now)"
        ),
        {"id": uuid4(), "farm": farm_id, "now": datetime.now(UTC) - timedelta(minutes=5)},
    )
    await admin_session.commit()

    row = await _health(admin_session, schema)
    assert int(row["weather_overdue_count"]) == 0
    # The block row is still a subscription; only the overdue verdict changes.
    assert int(row["weather_active_subs"]) == 2


@pytest.mark.asyncio
async def test_a_block_weather_row_with_no_farm_row_is_still_overdue(
    admin_session: AsyncSession,
) -> None:
    """The guard must be narrow. A farm that has not cut over still reports."""
    schema = await _tenant(admin_session, "overdue-weather-block-only")
    _, block_id = await _farm_and_block(admin_session, schema)
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', 3, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "old": _LONG_AGO},
    )
    await admin_session.commit()

    assert int((await _health(admin_session, schema))["weather_overdue_count"]) == 1


@pytest.mark.asyncio
async def test_a_block_imagery_row_on_a_farm_aoi_farm_is_not_overdue(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "overdue-imagery-cutover")
    farm_id, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, last_attempted_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "pid": product_id, "old": _LONG_AGO},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, cadence_hours, is_active, fetch_farm_aoi, "
            " last_attempted_at) "
            "VALUES (:id, :farm, :pid, 24, TRUE, TRUE, :now)"
        ),
        {
            "id": uuid4(),
            "farm": farm_id,
            "pid": product_id,
            "now": datetime.now(UTC) - timedelta(minutes=5),
        },
    )
    await admin_session.commit()

    assert int((await _health(admin_session, schema))["imagery_overdue_count"]) == 0


@pytest.mark.asyncio
async def test_a_block_imagery_row_whose_farm_row_is_off_is_still_overdue(
    admin_session: AsyncSession,
) -> None:
    """`fetch_farm_aoi` is the gate, not the farm row existing.

    0074 gave every farm a row. Keying off existence alone would silence the
    overdue count platform-wide, which is the same mistake the block sweep
    itself carries a comment about.
    """
    schema = await _tenant(admin_session, "overdue-imagery-flag-off")
    farm_id, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, last_attempted_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "pid": product_id, "old": _LONG_AGO},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, cadence_hours, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, 24, TRUE, FALSE)"
        ),
        {"id": uuid4(), "farm": farm_id, "pid": product_id},
    )
    await admin_session.commit()

    assert int((await _health(admin_session, schema))["imagery_overdue_count"]) == 1
