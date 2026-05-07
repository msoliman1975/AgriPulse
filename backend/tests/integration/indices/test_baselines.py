"""Integration + pure-function tests for index baselines (PR-4).

Pure-function half exercises ``baselines.compute_block_baselines`` and
``compute_baseline_deviation`` against synthetic data. The integration
half seeds two years of `block_index_aggregates` rows for one block and
runs the recompute service path, verifying the baselines table fills
in and that a subsequent `record_aggregate_row` lands a populated
``baseline_deviation``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.indices.baselines import (
    HistoryRow,
    compute_baseline_deviation,
    compute_block_baselines,
    find_baseline_for_doy,
)
from app.modules.indices.service import get_indices_service
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _hist(iso: str, mean: float) -> HistoryRow:
    return HistoryRow(
        time=datetime.fromisoformat(iso).replace(tzinfo=UTC),
        mean=Decimal(str(mean)),
    )


def test_compute_baselines_emits_one_row_per_doy_with_enough_samples() -> None:
    # Pre-March-1 dates land on the same DOY every year — leap-year
    # drift only kicks in once Feb 29 has passed. Use Jan 15 to keep
    # the test stable across leap years.
    history = (
        _hist("2023-01-15T00:00:00", 0.65),
        _hist("2024-01-15T00:00:00", 0.70),
        _hist("2025-01-15T00:00:00", 0.68),
    )
    out = compute_block_baselines(history, window_days=0, min_sample_count=3)
    assert len(out) == 1
    row = out[0]
    assert row.day_of_year == datetime(2025, 1, 15).timetuple().tm_yday
    assert row.sample_count == 3
    assert row.years_observed == 3


def test_compute_baselines_skips_doys_below_floor() -> None:
    history = (_hist("2023-05-01T00:00:00", 0.65),)
    out = compute_block_baselines(history, window_days=0, min_sample_count=3)
    assert out == []


def test_compute_baselines_window_unions_adjacent_doys() -> None:
    history = (
        _hist("2023-05-01T00:00:00", 0.60),
        _hist("2023-05-02T00:00:00", 0.62),
        _hist("2023-05-03T00:00:00", 0.64),
    )
    # window_days=2 catches all three for any DOY in the cluster's reach
    out = compute_block_baselines(history, window_days=2, min_sample_count=3)
    sample_at_may1 = find_baseline_for_doy(out, datetime(2023, 5, 1).timetuple().tm_yday)
    assert sample_at_may1 is not None
    assert sample_at_may1.sample_count == 3


def test_compute_baselines_wraps_year_boundary() -> None:
    """Dec 31 + Jan 1 are 1 day apart, not 364.

    Leap-year drift bites here: 2024-12-31 is DOY 366, while 2023-12-31
    is DOY 365. We use 2025-12-31 (non-leap, DOY 365) and Jan 1 entries
    so the wrap-distance from DOY 1 to DOY 365 is 1 day.
    """
    history = (
        _hist("2025-12-31T00:00:00", 0.50),
        _hist("2024-01-01T00:00:00", 0.51),
        _hist("2025-01-01T00:00:00", 0.49),
    )
    out = compute_block_baselines(history, window_days=1, min_sample_count=3)
    target = find_baseline_for_doy(out, 1)
    assert target is not None
    assert target.sample_count == 3


def test_baseline_deviation_zscore() -> None:
    out = compute_baseline_deviation(
        value=Decimal("0.50"),
        baseline_mean=Decimal("0.60"),
        baseline_std=Decimal("0.05"),
    )
    assert out == Decimal("-2.0000")


def test_baseline_deviation_returns_none_when_std_zero() -> None:
    out = compute_baseline_deviation(
        value=Decimal("0.50"),
        baseline_mean=Decimal("0.50"),
        baseline_std=Decimal("0"),
    )
    assert out is None


# ---------------------------------------------------------------------------
# Integration: seed history → recompute → record + populate deviation
# ---------------------------------------------------------------------------


async def _seed_block(
    admin_session: AsyncSession,
    schema_name: str,
    *,
    block_id: UUID,
    farm_id: UUID,
) -> None:
    """Insert a minimal block + farm row directly via SQL.

    The PR-4 test only needs IDs that exist for FK validation; full
    farm/block creation through the service is overkill (it would also
    fire all the imagery side effects).
    """
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2, status) "
            "VALUES (:fid, 'PR4-FARM', 'PR-4 Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100, 'active')"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type, status) "
            "VALUES (:bid, :fid, 'B-PR4', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'pr4-aoi-hash', 'block', 'active')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.commit()


async def _seed_aggregate_history(
    admin_session: AsyncSession,
    schema_name: str,
    *,
    block_id: UUID,
    product_id: UUID,
    rows: list[tuple[datetime, Decimal]],
) -> None:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    for time, mean in rows:
        await admin_session.execute(
            text(
                "INSERT INTO block_index_aggregates ("
                "  time, block_id, index_code, product_id, "
                "  mean, valid_pixel_count, total_pixel_count, stac_item_id"
                ") VALUES ("
                "  :time, :block_id, 'ndvi', :product_id, "
                "  :mean, 100, 100, :stac_item_id"
                ")"
            ).bindparams(
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("product_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "time": time,
                "block_id": block_id,
                "product_id": product_id,
                "mean": mean,
                "stac_item_id": f"seeded/{time.isoformat()}",
            },
        )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_recompute_then_record_populates_baseline_deviation(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr4-baselines",
        name="PR-4 Baselines",
        contact_email="ops@pr4-baselines.test",
    )

    block_id = uuid4()
    farm_id = uuid4()
    product_id = uuid4()
    await _seed_block(admin_session, tenant.schema_name, block_id=block_id, farm_id=farm_id)

    # Three years of observations on the same Jan 15 (DOY 15 every
    # year, leap or not) clustered tightly around 0.60 NDVI, so the
    # baseline mean lands at ~0.60 with tight std. We then record a
    # fresh aggregate at 0.40 — the deviation should be strongly
    # negative.
    history = [
        (datetime(2023, 1, 15, 12, 0, tzinfo=UTC), Decimal("0.60")),
        (datetime(2024, 1, 15, 12, 0, tzinfo=UTC), Decimal("0.62")),
        (datetime(2025, 1, 15, 12, 0, tzinfo=UTC), Decimal("0.58")),
    ]
    await _seed_aggregate_history(
        admin_session,
        tenant.schema_name,
        block_id=block_id,
        product_id=product_id,
        rows=history,
    )

    # Recompute baselines for this (block, ndvi) pair, then record a new
    # aggregate row dated on Jan 15 (same DOY as the seeds, leap-year-safe).
    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    new_time = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        svc = get_indices_service(tenant_session=session)
        rows_written = await svc.recompute_block_index_baselines(
            block_id=block_id, index_code="ndvi", window_days=0
        )
    assert rows_written == 1, f"expected 1 baseline row, got {rows_written}"

    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        svc = get_indices_service(tenant_session=session)
        await svc.record_aggregate_row(
            time=new_time,
            block_id=block_id,
            index_code="ndvi",
            product_id=product_id,
            stac_item_id="pr4/new",
            mean=Decimal("0.40"),
            min_value=Decimal("0.30"),
            max_value=Decimal("0.50"),
            p10=Decimal("0.32"),
            p50=Decimal("0.40"),
            p90=Decimal("0.48"),
            std_dev=Decimal("0.05"),
            valid_pixel_count=100,
            total_pixel_count=100,
            cloud_cover_pct=Decimal("5.0"),
        )

    row = (
        await admin_session.execute(
            text(
                f'SELECT baseline_deviation FROM "{tenant.schema_name}".block_index_aggregates '
                "WHERE block_id = :bid AND time = :time"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id, "time": new_time},
        )
    ).scalar_one()
    assert row is not None, "baseline_deviation was not populated"
    # Mean of 0.60, std ~0.0163; (0.40 - 0.60)/0.0163 ≈ -12 — strongly negative.
    assert row < Decimal("-5"), f"expected strongly negative deviation, got {row}"


@pytest.mark.asyncio
async def test_record_without_baseline_leaves_deviation_null(
    admin_session: AsyncSession,
) -> None:
    """Brand-new block (no baseline yet) → deviation NULL."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr4-no-baseline",
        name="PR-4 No Baseline",
        contact_email="ops@pr4-nb.test",
    )
    block_id = uuid4()
    farm_id = uuid4()
    product_id = uuid4()
    await _seed_block(admin_session, tenant.schema_name, block_id=block_id, farm_id=farm_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        svc = get_indices_service(tenant_session=session)
        await svc.record_aggregate_row(
            time=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            block_id=block_id,
            index_code="ndvi",
            product_id=product_id,
            stac_item_id="pr4-nb/new",
            mean=Decimal("0.55"),
            min_value=None,
            max_value=None,
            p10=None,
            p50=None,
            p90=None,
            std_dev=None,
            valid_pixel_count=100,
            total_pixel_count=100,
            cloud_cover_pct=None,
        )

    row = (
        await admin_session.execute(
            text(
                f'SELECT baseline_deviation FROM "{tenant.schema_name}".block_index_aggregates '
                "WHERE block_id = :bid"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id},
        )
    ).scalar_one()
    assert row is None
