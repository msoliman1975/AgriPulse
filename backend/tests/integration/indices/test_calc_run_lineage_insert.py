"""Regression: `indices_calc_runs` inserts must actually execute.

`IndicesRepository.insert_calc_run` raised on every call in production:

    operator is not unique: unknown - unknown

The offending expression was
``(EXTRACT(EPOCH FROM (:completed_at - :started_at)) * 1000)::int``.
asyncpg sends an unadorned bind as `unknown`, so Postgres saw
`unknown - unknown`, could not pick an operator, and refused the statement.

It stayed invisible for two compounding reasons. The caller
(`imagery.tasks._record_calc_run`) treats lineage as best-effort and
swallows the exception into a log line — correct, since a scene that
computed fine must not be reported as failed because its history did not
write. And the only tests that touched the table were the Observer
fixtures, which INSERT with their own hand-written SQL rather than through
the repository. A fixture that writes its own INSERT cannot fail on an
INSERT the production code gets wrong.

Result: zero rows in `indices_calc_runs` in all three production tenants,
from the day the table shipped. This test calls the real repository method
so that arrangement cannot recur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.indices.service import get_indices_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


async def _seed_block(
    admin_session: AsyncSession,
    schema_name: str,
    *,
    block_id: UUID,
    farm_id: UUID,
) -> None:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, 'CR-FARM', 'Calc-run Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type) "
            "VALUES (:bid, :fid, 'B-CR', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100, 'abc123', 'block')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_record_calc_run_writes_a_row_and_computes_duration(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="calc-run-lineage",
        name="Calc run lineage",
        contact_email="ops@calc-run-lineage.test",
    )
    block_id, farm_id, product_id = uuid4(), uuid4(), uuid4()
    await _seed_block(admin_session, tenant.schema_name, block_id=block_id, farm_id=farm_id)

    started = datetime(2026, 8, 21, 1, 0, 0, tzinfo=UTC)
    completed = datetime(2026, 8, 21, 1, 0, 2, tzinfo=UTC)

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        await get_indices_service(tenant_session=session).record_calc_run(
            job_id=uuid4(),
            scene_time=datetime(2026, 8, 20, 8, 25, tzinfo=UTC),
            scene_id="S2B_TEST_20260820",
            stac_item_id="stac/test/1",
            block_id=block_id,
            product_id=product_id,
            aoi_hash="abc123",
            # Nullable UUIDs on the same statement — the bind-typing half of
            # the same family of bug.
            grid_config_id=None,
            cell_count=None,
            band_order=["red", "nir"],
            aoi_pixel_count=100,
            masked_pixel_count=10,
            per_index={"ndvi": {"mean": 0.42}},
            trigger="live",
            outcome="ok",
            error=None,
            started_at=started,
            completed_at=completed,
        )

    async with factory() as session:
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        row = (
            (
                await session.execute(
                    text(
                        "SELECT scene_id, outcome, duration_ms, per_index, band_order "
                        "FROM indices_calc_runs"
                    )
                )
            )
            .mappings()
            .one()
        )

    assert row["scene_id"] == "S2B_TEST_20260820"
    assert row["outcome"] == "ok"
    # Two seconds, subtracted in Python rather than by Postgres.
    assert row["duration_ms"] == 2000
    assert row["per_index"] == {"ndvi": {"mean": 0.42}}
    assert row["band_order"] == ["red", "nir"]
