"""Integration health has to see the farm acquisition path.

Every view behind the page was written when a subscription was necessarily
per-block. Once a farm could subscribe on its own behalf (0074/0076/0077),
the page kept reading only the block tables and started reporting two
opposite falsehoods at once — both confirmed on production before the fix
(`tenant_019eafdc242c7320948e13490efc67dd`, 2026-08-17):

  * **Silence.** Green Farm [Demo-01] had 1 active weather farm sub and 2
    active imagery farm subs, all synced within the hour, 65 farm ingestion
    jobs behind them — and zero block subscriptions. The farm view reported
    0 subs, NULL last-sync, 0 failures. A farm ingesting continuously read
    as never configured.

  * **A false alarm.** Bashier Elkhier's weather farm sub had synced at
    06:17 that morning. The view reported 2026-08-13 17:38, because it
    maxed only over the abandoned per-block rows, and called a healthy farm
    four days stale.

And `v_integration_recent_attempts` omitted `imagery_farm_ingestion_jobs`
entirely, which is why the Runs tab, the per-block drill-down and
`streak_watcher` had never seen a single thermal ingestion: thermal is
farm-AOI only, so it has no block jobs to see.

These tests assert the counts and timestamps from both paths, and — just
as importantly — that the block path did not start double-counting.
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


async def _farm(admin_session: AsyncSession, schema: str, name: str = "F") -> str:
    farm_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".farms (id, name, code, boundary, boundary_utm) '
            "VALUES (:id, :name, :name, "
            f"ST_GeomFromText('{_BOUNDARY}', 4326), "
            f"ST_Transform(ST_GeomFromText('{_BOUNDARY}', 4326), 32636))"
        ),
        {"id": farm_id, "name": name},
    )
    await admin_session.commit()
    return str(farm_id)


async def _block(admin_session: AsyncSession, schema: str, farm_id: str) -> str:
    block_id = uuid4()
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
    return str(block_id)


async def _product_id(admin_session: AsyncSession, code: str) -> UUID:
    row = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products WHERE code = :c"), {"c": code}
        )
    ).first()
    assert row is not None, f"seed is missing imagery product {code!r}"
    return UUID(str(row[0]))


async def _farm_health(admin_session: AsyncSession, schema: str) -> dict[str, Any]:
    """The single row the Overview tab renders for this farm."""
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    row = (
        (await admin_session.execute(text("SELECT * FROM v_farm_integration_health")))
        .mappings()
        .one()
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return dict(row)


async def _attempts(admin_session: AsyncSession, schema: str) -> list[dict[str, Any]]:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = (
        (
            await admin_session.execute(
                text("SELECT * FROM v_integration_recent_attempts ORDER BY started_at DESC")
            )
        )
        .mappings()
        .all()
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return [dict(r) for r in rows]


# --- the silence: a farm-only farm reading as unconfigured ------------------


@pytest.mark.asyncio
async def test_a_farm_only_farm_reports_its_subscriptions(
    admin_session: AsyncSession,
) -> None:
    """Green Farm's shape: farm subs, farm jobs, zero block subs."""
    schema = await _tenant(admin_session, "fh-farm-only")
    farm_id = await _farm(admin_session, schema)
    synced = datetime.now(UTC) - timedelta(minutes=30)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, is_active, last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', TRUE, :at)"
        ),
        {"id": uuid4(), "farm": farm_id, "at": synced},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi, "
            " last_successful_ingest_at, last_attempted_at) "
            "VALUES (:id, :farm, :pid, TRUE, TRUE, :at, :at)"
        ),
        {
            "id": uuid4(),
            "farm": farm_id,
            "pid": await _product_id(admin_session, "landsat_c2_l2_st"),
            "at": synced,
        },
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["weather_active_subs"] == 1
    assert row["imagery_active_subs"] == 1
    # Cadence defaults are 3h weather / 24h imagery, and this synced 30
    # minutes ago — neither is overdue.
    assert row["weather_overdue_count"] == 0
    assert row["imagery_overdue_count"] == 0


@pytest.mark.asyncio
async def test_farm_imagery_jobs_set_the_last_sync_timestamp(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "fh-farm-jobs")
    farm_id = await _farm(admin_session, schema)
    product_id = await _product_id(admin_session, "landsat_c2_l2_st")
    sub_id = uuid4()
    requested = datetime.now(UTC) - timedelta(hours=2)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, TRUE, TRUE)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " requested_at, status) "
            "VALUES (:id, :sub, :farm, :pid, 'S1', :at, :at, 'succeeded')"
        ),
        {
            "id": uuid4(),
            "sub": sub_id,
            "farm": farm_id,
            "pid": product_id,
            "at": requested,
        },
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["imagery_last_sync_at"] is not None
    assert abs((row["imagery_last_sync_at"] - requested).total_seconds()) < 1


@pytest.mark.asyncio
async def test_a_failed_farm_job_counts_toward_failed_24h(
    admin_session: AsyncSession,
) -> None:
    """Otherwise a farm whose every fetch fails still reads as healthy."""
    schema = await _tenant(admin_session, "fh-farm-failed")
    farm_id = await _farm(admin_session, schema)
    product_id = await _product_id(admin_session, "landsat_c2_l2_st")
    sub_id = uuid4()

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, TRUE, TRUE)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " requested_at, status, error_code) "
            "VALUES (:id, :sub, :farm, :pid, 'S1', now(), now(), 'failed', 'http_error')"
        ),
        {"id": uuid4(), "sub": sub_id, "farm": farm_id, "pid": product_id},
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["imagery_failed_24h"] == 1


@pytest.mark.asyncio
async def test_a_farm_scoped_weather_attempt_counts_toward_failed_24h(
    admin_session: AsyncSession,
) -> None:
    """0077 attempts carry `block_id IS NULL`, so the block view cannot see them."""
    schema = await _tenant(admin_session, "fh-wx-attempt")
    farm_id = await _farm(admin_session, schema)
    sub_id = uuid4()

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, is_active) "
            "VALUES (:id, :farm, 'open_meteo', TRUE)"
        ),
        {"id": sub_id, "farm": farm_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_ingestion_attempts '
            "(id, subscription_id, block_id, farm_id, provider_code, started_at, status) "
            "VALUES (:id, :sub, NULL, :farm, 'open_meteo', now(), 'failed')"
        ),
        {"id": uuid4(), "sub": sub_id, "farm": farm_id},
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["weather_failed_24h"] == 1


# --- the false alarm: a stale block row hiding a fresh farm one -------------


@pytest.mark.asyncio
async def test_the_later_of_the_two_paths_wins_the_last_sync(
    admin_session: AsyncSession,
) -> None:
    """Bashier Elkhier's shape: stale block rows, fresh farm row.

    Taking the max over block rows alone reported a farm that synced this
    morning as four days stale — a false alarm on a working farm, which
    trains an operator to distrust the page.
    """
    schema = await _tenant(admin_session, "fh-later-wins")
    farm_id = await _farm(admin_session, schema)
    block_id = await _block(admin_session, schema, farm_id)
    stale = datetime.now(UTC) - timedelta(days=4)
    fresh = datetime.now(UTC) - timedelta(minutes=15)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, is_active, last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', TRUE, :at)"
        ),
        {"id": uuid4(), "block": block_id, "at": stale},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, is_active, last_successful_ingest_at) "
            "VALUES (:id, :farm, 'open_meteo', TRUE, :at)"
        ),
        {"id": uuid4(), "farm": farm_id, "at": fresh},
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert abs((row["weather_last_sync_at"] - fresh).total_seconds()) < 1
    # 0088: only the row that fetches is counted. The block row stopped
    # being polled at the cut-over, so counting it read "37 active weather
    # subscriptions" on a farm where one thing fetches. See
    # test_block_health_sees_farm_path.py.
    assert row["weather_active_subs"] == 1
    # 0085: the abandoned block row is NOT overdue. Nothing polls it any
    # more — `list_due_farm_provider_pairs` skips a block row once its farm
    # has an active farm row for the same provider — so its watermark can
    # never advance and counting it produced a number that only grew. On
    # prod this read "36 overdue" on farms whose weather had synced within
    # the hour. See test_overdue_skips_cutover_rows.py.
    assert row["weather_overdue_count"] == 0


# --- the block path must not start double-counting -------------------------


@pytest.mark.asyncio
async def test_a_block_only_farm_is_unchanged(admin_session: AsyncSession) -> None:
    """The regression guard for every tenant that has not cut over."""
    schema = await _tenant(admin_session, "fh-block-only")
    farm_id = await _farm(admin_session, schema)
    block_id = await _block(admin_session, schema, farm_id)
    synced = datetime.now(UTC) - timedelta(minutes=10)

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, is_active, last_successful_ingest_at) "
            "VALUES (:id, :block, 'open_meteo', TRUE, :at)"
        ),
        {"id": uuid4(), "block": block_id, "at": synced},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_aoi_subscriptions '
            "(id, block_id, product_id, is_active, last_attempted_at) "
            "VALUES (:id, :block, :pid, TRUE, :at)"
        ),
        {
            "id": uuid4(),
            "block": block_id,
            "pid": await _product_id(admin_session, "s2_l2a"),
            "at": synced,
        },
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["weather_active_subs"] == 1
    assert row["imagery_active_subs"] == 1
    assert row["weather_overdue_count"] == 0
    assert row["imagery_overdue_count"] == 0


@pytest.mark.asyncio
async def test_a_farm_sub_that_does_not_fetch_is_not_counted(
    admin_session: AsyncSession,
) -> None:
    """0074 gave every farm a row; `fetch_farm_aoi` is what makes it do anything.

    Counting a non-fetching row would have moved a 36-block farm from 36
    active imagery subs to 37 while nothing about its acquisition changed —
    an inflated number is a different lie, not a fix.
    """
    schema = await _tenant(admin_session, "fh-no-fetch")
    farm_id = await _farm(admin_session, schema)
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, TRUE, FALSE)"
        ),
        {
            "id": uuid4(),
            "farm": farm_id,
            "pid": await _product_id(admin_session, "s2_l2a"),
        },
    )
    await admin_session.commit()

    row = await _farm_health(admin_session, schema)
    assert row["imagery_active_subs"] == 0


# --- the Runs tab / streak watcher ------------------------------------------


@pytest.mark.asyncio
async def test_farm_imagery_jobs_appear_in_the_attempts_view(
    admin_session: AsyncSession,
) -> None:
    """The Runs tab, the block drill-down and `streak_watcher` all read this."""
    schema = await _tenant(admin_session, "fh-attempts")
    farm_id = await _farm(admin_session, schema)
    product_id = await _product_id(admin_session, "landsat_c2_l2_st")
    sub_id = uuid4()

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, TRUE, TRUE)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
            " requested_at, status) "
            "VALUES (:id, :sub, :farm, :pid, 'LC09_X', now(), now(), 'succeeded')"
        ),
        {"id": uuid4(), "sub": sub_id, "farm": farm_id, "pid": product_id},
    )
    await admin_session.commit()

    rows = await _attempts(admin_session, schema)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "imagery"
    assert row["scope"] == "farm"
    assert row["block_id"] is None
    # The farm has to be named, or the row cannot be filtered or attributed.
    assert str(row["farm_id"]) == farm_id
    assert row["scene_id"] == "LC09_X"
    assert row["provider_code"] == "landsat_c2_l2_st"


@pytest.mark.asyncio
async def test_consecutive_farm_job_failures_build_a_streak(
    admin_session: AsyncSession,
) -> None:
    """`failed_streak_position` is what `streak_watcher` alerts on.

    Without the farm arm it was always absent for the farm path, so a
    thermal subscription could fail every day forever without one
    notification.
    """
    schema = await _tenant(admin_session, "fh-streak")
    farm_id = await _farm(admin_session, schema)
    product_id = await _product_id(admin_session, "landsat_c2_l2_st")
    sub_id = uuid4()

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :pid, TRUE, TRUE)"
        ),
        {"id": sub_id, "farm": farm_id, "pid": product_id},
    )
    base = datetime.now(UTC) - timedelta(hours=6)
    for n in range(3):
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".imagery_farm_ingestion_jobs '
                "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, "
                " requested_at, status, error_code) "
                "VALUES (:id, :sub, :farm, :pid, :scene, :at, :at, 'failed', 'http_error')"
            ),
            {
                "id": uuid4(),
                "sub": sub_id,
                "farm": farm_id,
                "pid": product_id,
                "scene": f"LC09_{n}",
                "at": base + timedelta(hours=n),
            },
        )
    await admin_session.commit()

    rows = await _attempts(admin_session, schema)
    assert [r["failed_streak_position"] for r in rows] == [3, 2, 1]


@pytest.mark.asyncio
async def test_weather_attempt_scope_names_the_two_paths(
    admin_session: AsyncSession,
) -> None:
    """A null block_id is the mechanism; `scope` is what a reader should key on."""
    schema = await _tenant(admin_session, "fh-wx-scope")
    farm_id = await _farm(admin_session, schema)
    block_id = await _block(admin_session, schema, farm_id)
    block_sub, farm_sub = uuid4(), uuid4()

    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_subscriptions '
            "(id, block_id, provider_code, is_active) VALUES (:id, :block, 'open_meteo', TRUE)"
        ),
        {"id": block_sub, "block": block_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, is_active) VALUES (:id, :farm, 'open_meteo', TRUE)"
        ),
        {"id": farm_sub, "farm": farm_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_ingestion_attempts '
            "(id, subscription_id, block_id, farm_id, provider_code, started_at, status) "
            "VALUES (:id, :sub, :block, :farm, 'open_meteo', now() - interval '1 hour', "
            "'succeeded')"
        ),
        {"id": uuid4(), "sub": block_sub, "block": block_id, "farm": farm_id},
    )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_ingestion_attempts '
            "(id, subscription_id, block_id, farm_id, provider_code, started_at, status) "
            "VALUES (:id, :sub, NULL, :farm, 'open_meteo', now(), 'succeeded')"
        ),
        {"id": uuid4(), "sub": farm_sub, "farm": farm_id},
    )
    await admin_session.commit()

    rows = await _attempts(admin_session, schema)
    assert [r["scope"] for r in rows] == ["farm", "block"]
    assert rows[0]["block_id"] is None
    assert str(rows[1]["block_id"]) == block_id
