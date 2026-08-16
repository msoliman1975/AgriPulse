"""A provider a tenant actually uses must appear on the Providers tab.

The list was gated on `EXISTS (block subscriptions)` alone. That predicate
predates whole-farm fetching and quietly stopped describing reality:

  * a farm cut over to one whole-farm AOI may have had its block
    subscriptions deactivated, so a provider it fetches from every day
    vanished from the page whose job is to say whether it is healthy;
  * `landsat_pc` was worse than a regression. Thermal is farm-AOI only —
    it has NO block subscriptions by construction — so it could never
    appear here at all, however hard it was failing.

Confirmed against production before the fix: the tenant fetching thermal
daily showed `sentinel_hub` and `open_meteo` on this page, and no
`landsat_pc`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations_health.providers_service import ProviderHealthService
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


async def _tenant(admin_session: AsyncSession, slug: str) -> str:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    await admin_session.commit()
    return tenant.schema_name


async def _farm(admin_session: AsyncSession, schema: str) -> str:
    farm_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".farms (id, name, code, boundary, boundary_utm) '
            "VALUES (:id, 'F', 'F', "
            "ST_GeomFromText('POLYGON((32.6 30.0,32.7 30.0,32.7 30.1,32.6 30.1,32.6 30.0))', 4326), "
            "ST_Transform(ST_GeomFromText("
            "'POLYGON((32.6 30.0,32.7 30.0,32.7 30.1,32.6 30.1,32.6 30.0))', 4326), 32636))"
        ),
        {"id": farm_id},
    )
    await admin_session.commit()
    return str(farm_id)


async def _codes(admin_session: AsyncSession, schema: str) -> set[str]:
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    rows = await ProviderHealthService(public_session=admin_session).list_tenant_providers(
        tenant_schema=schema
    )
    await admin_session.execute(text("SET LOCAL search_path TO public"))
    return {r["provider_code"] for r in rows}


@pytest.mark.asyncio
async def test_a_farm_only_imagery_provider_is_listed(admin_session: AsyncSession) -> None:
    """The thermal case: farm-AOI only, so zero block rows exist."""
    schema = await _tenant(admin_session, "ph-farm-imagery")
    farm_id = await _farm(admin_session, schema)
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "SELECT :id, :farm, id, TRUE, TRUE FROM public.imagery_products "
            "WHERE code = 'landsat_c2_l2_st'"
        ),
        {"id": uuid4(), "farm": farm_id},
    )
    await admin_session.commit()

    assert "landsat_pc" in await _codes(admin_session, schema)


@pytest.mark.asyncio
async def test_a_farm_only_weather_provider_is_listed(admin_session: AsyncSession) -> None:
    """A tenant whose weather moved to the farm row after 0077."""
    schema = await _tenant(admin_session, "ph-farm-weather")
    farm_id = await _farm(admin_session, schema)
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_farm_subscriptions '
            "(id, farm_id, provider_code, is_active) "
            "VALUES (:id, :farm, 'open_meteo', TRUE)"
        ),
        {"id": uuid4(), "farm": farm_id},
    )
    await admin_session.commit()

    assert "open_meteo" in await _codes(admin_session, schema)


@pytest.mark.asyncio
async def test_a_tenant_using_nothing_still_lists_nothing(
    admin_session: AsyncSession,
) -> None:
    """The predicate still has to mean something.

    Widening it to a bare `OR TRUE` would list every provider on the
    platform for every tenant, which is the opposite failure and just as
    useless.
    """
    schema = await _tenant(admin_session, "ph-none")
    await _farm(admin_session, schema)

    assert await _codes(admin_session, schema) == set()


@pytest.mark.asyncio
async def test_an_inactive_farm_subscription_does_not_list_its_provider(
    admin_session: AsyncSession,
) -> None:
    schema = await _tenant(admin_session, "ph-inactive")
    farm_id = await _farm(admin_session, schema)
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "SELECT :id, :farm, id, FALSE, TRUE FROM public.imagery_products "
            "WHERE code = 'landsat_c2_l2_st'"
        ),
        {"id": uuid4(), "farm": farm_id},
    )
    await admin_session.commit()

    assert "landsat_pc" not in await _codes(admin_session, schema)
