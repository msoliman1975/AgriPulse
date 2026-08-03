"""Integration test: `load_gdd_since` — accumulated heat over a window.

This is the query behind the phenology task's `gdd_from_planting` stage
mode. The interesting assertions are the two design decisions it encodes:
it sums the *daily* `gdd_base10` rather than reading the season
cumulative (which resets on an anchor unrelated to any block's planting
date), and it distinguishes "no weather history" (None → the block holds
its stage) from "no heat accumulated yet" (0 → genuinely stage one).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.modules.weather.snapshot import load_gdd_since

pytestmark = [pytest.mark.integration]

_UUID = PG_UUID(as_uuid=True)


async def _schema_for(admin_session: AsyncSession, tenant_id) -> str:
    return (
        await admin_session.execute(
            text("SELECT schema_name FROM public.tenants WHERE id = :id").bindparams(
                bindparam("id", type_=_UUID)
            ),
            {"id": tenant_id},
        )
    ).scalar_one()


async def _seed_farm(admin_session: AsyncSession, schema: str):
    farm_id = uuid4()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'GDD', 'GDD Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=_UUID)),
        {"id": farm_id},
    )
    return farm_id


async def _insert_day(
    admin_session: AsyncSession,
    *,
    farm_id,
    on_date: date,
    gdd: float | None,
    season_cumulative: float | None = None,
) -> None:
    await admin_session.execute(
        text(
            "INSERT INTO weather_derived_daily "
            " (farm_id, date, gdd_base10, gdd_cumulative_base10_season) "
            "VALUES (:farm, :d, :gdd, :cum)"
        ).bindparams(bindparam("farm", type_=_UUID)),
        # Bind a real `date`, never an isoformat string.
        {"farm": farm_id, "d": on_date, "gdd": gdd, "cum": season_cumulative},
    )


@pytest.mark.asyncio
async def test_sums_daily_gdd_across_the_window(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="gdd-sum", name="GDD Sum", contact_email="ops@gdd-sum.test"
    )
    schema = await _schema_for(admin_session, tenant.tenant_id)
    farm_id = await _seed_farm(admin_session, schema)

    # A wildly wrong season cumulative on every row: if the query ever
    # reads it instead of summing the dailies, this test fails loudly.
    for day, gdd in [(1, 5.0), (2, 10.0), (3, 15.0), (4, 20.0)]:
        await _insert_day(
            admin_session,
            farm_id=farm_id,
            on_date=date(2026, 4, day),
            gdd=gdd,
            season_cumulative=9999.0,
        )
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    total = await load_gdd_since(
        admin_session, farm_id=farm_id, since=date(2026, 4, 1), until=date(2026, 4, 4)
    )
    assert total == Decimal("50.00")

    # Window bounds are inclusive on both ends and exclude everything else.
    inner = await load_gdd_since(
        admin_session, farm_id=farm_id, since=date(2026, 4, 2), until=date(2026, 4, 3)
    )
    assert inner == Decimal("25.00")

    await admin_session.execute(text("SET search_path TO public"))


@pytest.mark.asyncio
async def test_no_rows_is_none_but_null_heat_is_zero(admin_session: AsyncSession) -> None:
    """The distinction the phenology task depends on: None means "no
    weather history, hold the stage"; 0 means "measured, no heat yet"."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="gdd-null", name="GDD Null", contact_email="ops@gdd-null.test"
    )
    schema = await _schema_for(admin_session, tenant.tenant_id)
    farm_id = await _seed_farm(admin_session, schema)
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))

    # No rows at all in the window.
    assert (
        await load_gdd_since(
            admin_session, farm_id=farm_id, since=date(2026, 4, 1), until=date(2026, 4, 30)
        )
        is None
    )

    # Rows exist but carry no GDD — a real zero, not missing data.
    await _insert_day(admin_session, farm_id=farm_id, on_date=date(2026, 4, 10), gdd=None)
    await admin_session.commit()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    assert (
        await load_gdd_since(
            admin_session, farm_id=farm_id, since=date(2026, 4, 1), until=date(2026, 4, 30)
        )
        == 0
    )

    await admin_session.execute(text("SET search_path TO public"))


@pytest.mark.asyncio
async def test_other_farms_are_not_counted(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="gdd-scope", name="GDD Scope", contact_email="ops@gdd-scope.test"
    )
    schema = await _schema_for(admin_session, tenant.tenant_id)
    farm_a = await _seed_farm(admin_session, schema)

    farm_b = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'GDD2', 'Other Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.3 30.0,31.31 30.0,31.31 30.01,31.3 30.01,31.3 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=_UUID)),
        {"id": farm_b},
    )
    await _insert_day(admin_session, farm_id=farm_a, on_date=date(2026, 4, 1), gdd=7.0)
    await _insert_day(admin_session, farm_id=farm_b, on_date=date(2026, 4, 1), gdd=100.0)
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    assert await load_gdd_since(
        admin_session, farm_id=farm_a, since=date(2026, 4, 1), until=date(2026, 4, 1)
    ) == Decimal("7.00")
    await admin_session.execute(text("SET search_path TO public"))
