"""The Blocks tab must report the acquisition that actually serves a block.

`v_block_integration_health` read only `weather_subscriptions` and
`imagery_aoi_subscriptions` until migration 0088. Both are block-keyed, so
the view was wrong in two opposite directions once a farm started acquiring
on its own behalf. Both were measured on prod on 2026-08-28:

  A farm with no block subscriptions at all
    36 blocks read "Idle - No active subscription" while the farm weather
    subscription had synced 8 minutes earlier.

  A farm whose block rows were superseded at the cut-over
    72 blocks read "Failing" because their watermarks froze on 2026-08-13,
    15 days before the farm last synced.

These tests run against the real views, because the defect was in the SQL
and every layer above it was already correct. A test that stubbed the
repository would have passed on the broken view.
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

# The cut-over date on the prod tenant these tests describe.
_FROZEN = datetime(2026, 8, 13, 17, 38, tzinfo=UTC)


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


async def _block_health(admin_session: AsyncSession, schema: str) -> dict[str, Any]:
    """The single row the Blocks tab renders for this block."""
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    row = (
        (await admin_session.execute(text("SELECT * FROM v_block_integration_health")))
        .mappings()
        .one()
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return dict(row)


async def _farm_health(admin_session: AsyncSession, schema: str) -> dict[str, Any]:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    row = (
        (await admin_session.execute(text("SELECT * FROM v_farm_integration_health")))
        .mappings()
        .one()
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return dict(row)


# --- the "Idle" direction ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_block_with_no_rows_of_its_own_reports_the_farm_weather_sub(
    admin_session: AsyncSession,
) -> None:
    """Valley Farms / Mango Republic: 36 blocks, 0 block subscriptions.

    `activeSubs === 0` is what makes the cell say "No active subscription",
    so this assertion is the one that stops the page calling a working block
    unconfigured.
    """
    schema = await _tenant(admin_session, "bh-farm-only-weather")
    farm_id, _ = await _farm_and_block(admin_session, schema)
    synced = datetime.now(UTC) - timedelta(minutes=8)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', 3, TRUE, :at)"
        ),
        {"id": uuid4(), "farm": farm_id, "at": synced},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    assert int(row["weather_active_subs"]) == 1
    assert abs((row["weather_last_sync_at"] - synced).total_seconds()) < 1
    assert int(row["weather_overdue_count"]) == 0


@pytest.mark.asyncio
async def test_a_block_with_no_rows_of_its_own_reports_the_farm_imagery_sub(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "bh-farm-only-imagery")
    farm_id, _ = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")
    sub_id = uuid4()
    requested = datetime.now(UTC) - timedelta(hours=2)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, cadence_hours, is_active, fetch_farm_aoi, "
            " last_attempted_at) "
            "VALUES (:id, :farm, :pid, 24, TRUE, TRUE, :at)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id, "at": requested},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " requested_at, status) "
            "VALUES (:id, :sub, :farm, :pid, 'S1', :at, :at, 'succeeded')"
        ),
        {"id": uuid4(), "sub": sub_id, "farm": farm_id, "pid": product_id, "at": requested},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    assert int(row["imagery_active_subs"]) == 1
    assert abs((row["imagery_last_sync_at"] - requested).total_seconds()) < 1
    assert int(row["imagery_overdue_count"]) == 0


# --- the "Failing" direction ------------------------------------------------


@pytest.mark.asyncio
async def test_a_superseded_block_weather_row_reports_the_farm_clock(
    admin_session: AsyncSession,
) -> None:
    """agrosina: block rows frozen 15 days back on a farm that synced today.

    The frozen date is what drove `statusFor` past its 50-hour ceiling and
    painted 72 working blocks red.
    """
    schema = await _tenant(admin_session, "bh-superseded-weather")
    farm_id, block_id = await _farm_and_block(admin_session, schema)
    fresh = datetime.now(UTC) - timedelta(minutes=20)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', 3, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "old": _FROZEN},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', 3, TRUE, :at)"
        ),
        {"id": uuid4(), "farm": farm_id, "at": fresh},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    assert abs((row["weather_last_sync_at"] - fresh).total_seconds()) < 1
    # One thing fetches for this block, so the count is 1, not 2.
    assert int(row["weather_active_subs"]) == 1
    assert int(row["weather_overdue_count"]) == 0


@pytest.mark.asyncio
async def test_a_superseded_block_imagery_row_reports_the_farm_clock(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "bh-superseded-imagery")
    farm_id, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")
    sub_id = uuid4()
    fresh = datetime.now(UTC) - timedelta(hours=3)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, last_attempted_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "pid": product_id, "old": _FROZEN},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, cadence_hours, is_active, fetch_farm_aoi, "
            " last_attempted_at) "
            "VALUES (:id, :farm, :pid, 24, TRUE, TRUE, :at)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id, "at": fresh},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " requested_at, status) "
            "VALUES (:id, :sub, :farm, :pid, 'S1', :at, :at, 'succeeded')"
        ),
        {"id": uuid4(), "sub": sub_id, "farm": farm_id, "pid": product_id, "at": fresh},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    assert abs((row["imagery_last_sync_at"] - fresh).total_seconds()) < 1
    assert int(row["imagery_active_subs"]) == 1
    assert int(row["imagery_overdue_count"]) == 0


# --- the guard must stay narrow ---------------------------------------------


@pytest.mark.asyncio
async def test_a_farm_that_has_not_cut_over_still_reports_its_block_row(
    admin_session: AsyncSession,
) -> None:
    """No farm subscription means the block row is still the one polled."""
    schema = await _tenant(admin_session, "bh-block-only")
    _, block_id = await _farm_and_block(admin_session, schema)
    synced = datetime.now(UTC) - timedelta(minutes=30)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', 3, TRUE, :at)"
        ),
        {"id": uuid4(), "block": block_id, "at": synced},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    assert int(row["weather_active_subs"]) == 1
    assert abs((row["weather_last_sync_at"] - synced).total_seconds()) < 1


@pytest.mark.asyncio
async def test_a_farm_row_for_another_provider_does_not_supersede(
    admin_session: AsyncSession,
) -> None:
    """The skip is per provider, the way the sweep's own predicate is.

    Dropping a block row because the farm fetches some other provider would
    hide a stream that is genuinely unpolled.
    """
    schema = await _tenant(admin_session, "bh-other-provider")
    farm_id, block_id = await _farm_and_block(admin_session, schema)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', 3, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "old": _FROZEN},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :farm, 'some_other_provider', 3, TRUE, :now)"
        ),
        {"id": uuid4(), "farm": farm_id, "now": datetime.now(UTC)},
    )
    await admin_session.commit()

    row = await _block_health(admin_session, schema)
    # Two providers, two subscriptions, and the block one is still overdue.
    assert int(row["weather_active_subs"]) == 2
    assert int(row["weather_overdue_count"]) == 1


@pytest.mark.asyncio
async def test_an_imagery_farm_row_that_does_not_fetch_does_not_supersede(
    admin_session: AsyncSession,
) -> None:
    """`fetch_farm_aoi` is the gate, matching the imagery sweep."""
    schema = await _tenant(admin_session, "bh-no-fetch")
    farm_id, block_id = await _farm_and_block(admin_session, schema)
    product_id = await _product_id(admin_session, "s2_l2a")

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, cadence_hours, is_active, last_attempted_at) "
            "VALUES (:id, :block, :pid, 24, TRUE, :old)"
        ),
        {"id": uuid4(), "block": block_id, "pid": product_id, "old": _FROZEN},
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

    row = await _block_health(admin_session, schema)
    # The non-fetching farm row is not counted anywhere, so the block row is
    # the only subscription and it is still overdue.
    assert int(row["imagery_active_subs"]) == 1
    assert int(row["imagery_overdue_count"]) == 1


# --- the two views must not double count ------------------------------------


@pytest.mark.asyncio
async def test_the_farm_view_does_not_count_the_farm_row_twice(
    admin_session: AsyncSession,
) -> None:
    """The Farms tab and the Blocks tab must agree on one farm subscription.

    The block view now carries the farm row on every block, so the farm view
    reads its block half from `v_block_own_integration_health`. Reading the
    public block view instead would give a 36-block farm 37 weather
    subscriptions again, this time once per block.
    """
    schema = await _tenant(admin_session, "bh-no-double-count")
    farm_id, _ = await _farm_and_block(admin_session, schema)
    synced = datetime.now(UTC) - timedelta(minutes=10)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, cadence_hours, is_active, "
            " last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', 3, TRUE, :at)"
        ),
        {"id": uuid4(), "farm": farm_id, "at": synced},
    )
    await admin_session.commit()

    farm_row = await _farm_health(admin_session, schema)
    block_row = await _block_health(admin_session, schema)
    assert int(farm_row["weather_active_subs"]) == 1
    assert int(block_row["weather_active_subs"]) == 1
    assert abs((farm_row["weather_last_sync_at"] - synced).total_seconds()) < 1
