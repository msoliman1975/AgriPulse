"""`farm_scope_consistency_check` against the real database.

`tests/unit/farms/test_consistency_check.py` mocks `_existing_farms_in_schema`
and asserts on the plumbing around it. That is the function that was broken,
so the mock asserted that correct code called an incorrect query correctly.

The bind was `bindparam(..., expanding=True)` against `id = ANY(:ids)`.
`expanding` is for `IN :ids`; against `ANY` it renders `ANY($1::UUID)`, a
scalar on the right-hand side, and Postgres answers::

    op ANY/ALL (array) requires array on right side

So the task raised on the first tenant holding any farm scope, on every run
since it was written, and nothing reported it until the platform alert sweep
started watching Celery failures. This test executes the statement.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms import consistency_check as cc
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]

_ID = bindparam("id", type_=PG_UUID(as_uuid=True))


async def _seed_farm(session: AsyncSession, *, schema: str, code: str) -> None:
    """One real farm row.

    `boundary`, `boundary_utm`, `centroid` and `area_m2` are all NOT NULL
    (tenant migration 0002), so the geometry is derived here rather than
    stubbed. The lookup under test reads only `id` and `deleted_at`, but the
    row has to exist for real or a passing test proves nothing about
    matching.

    The envelope corners are literals, not binds. Reusing one bind on both
    sides of `ST_MakeEnvelope` makes asyncpg deduce numeric in one position
    and double precision in the other, and it refuses the statement.
    """
    await session.execute(
        text(
            f"INSERT INTO {schema}.farms "
            "(id, code, name, boundary, boundary_utm, centroid, area_m2, active_from) "
            "SELECT :id, :code, :name, g, "
            "       ST_Transform(g, 32636), ST_Centroid(g), ST_Area(g::geography), "
            "       current_date "
            "  FROM (SELECT ST_Multi(ST_MakeEnvelope(31.2, 30.0, 31.205, 30.005, 4326))"
            "               ::geometry(MultiPolygon, 4326) AS g) t"
        ).bindparams(_ID),
        {"id": uuid4(), "code": code, "name": f"Farm {code}"},
    )


@pytest.mark.asyncio
async def test_existing_farms_lookup_runs_against_the_real_schema(
    admin_session: AsyncSession,
) -> None:
    """The query the task died on, executed for real.

    Asserting on the returned set rather than only on "it did not raise":
    a bind that parses but matches nothing would make the task report every
    farm scope as an orphan, which is a worse failure than a crash.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="scope-check-real-sql",
        name="Scope check real SQL",
        contact_email="ops@scope-check.test",
    )
    schema = tenant.schema_name

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _seed_farm(session, schema=schema, code="F-1")
        await _seed_farm(session, schema=schema, code="F-2")

    async with factory() as session, session.begin():
        rows = (await session.execute(text(f"SELECT id FROM {schema}.farms ORDER BY code"))).all()
    real_ids = [r.id for r in rows]
    assert len(real_ids) == 2

    absent = uuid4()
    async with factory() as session, session.begin():
        found = await cc._existing_farms_in_schema(
            session, schema=schema, farm_ids=[*real_ids, absent]
        )

    assert found == set(real_ids)
    # The whole point of the call: a farm id with no row is what the task
    # reports as an orphaned scope.
    assert absent not in found


@pytest.mark.asyncio
async def test_empty_id_list_does_not_reach_the_database(
    admin_session: AsyncSession,
) -> None:
    """`ANY` on an empty array is legal but pointless. The guard stays."""
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        assert await cc._existing_farms_in_schema(session, schema="public", farm_ids=[]) == set()
