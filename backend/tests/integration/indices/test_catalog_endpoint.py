"""GET /api/v1/indices/catalog — the imagery-index catalog endpoint.

Mirrors the weather-index catalog: tenant-scoped, but the rows come from
`public.indices_catalog`, which is platform-wide curated data rather than
per-farm, so there is no farm to gate on.

The reason it exists now is `unit`. Every index was a dimensionless ratio
until `lst` arrived, so the SPA could hardcode its metadata; a formatter
that assumes one shape cannot be right for both a temperature and a
normalized difference.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.imagery.conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


async def _client(admin_session: AsyncSession, slug: str) -> AsyncClient:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    await admin_session.commit()

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


@pytest.mark.asyncio
async def test_catalog_lists_every_index_with_its_bounds(admin_session: AsyncSession) -> None:
    async with await _client(admin_session, "idx-catalog") as client:
        response = await client.get("/api/v1/indices/catalog")

    assert response.status_code == 200
    rows = {r["code"]: r for r in response.json()}

    # The nine spectral indices plus the three thermal ones (0066).
    assert {"ndvi", "ndmi", "bsi", "msi"} <= set(rows)
    assert {"lst", "cwsi", "smi"} <= set(rows)

    ndvi = rows["ndvi"]
    assert float(ndvi["value_min"]) == -1.0
    assert float(ndvi["value_max"]) == 1.0
    assert ndvi["name_en"]
    assert ndvi["is_standard"] is True


@pytest.mark.asyncio
async def test_lst_is_the_only_index_carrying_a_unit(admin_session: AsyncSession) -> None:
    """The whole reason the column exists.

    A chart printing `31.85` with no `°C`, next to an NDVI of `0.723`,
    reads as the same kind of number when it is not.
    """
    async with await _client(admin_session, "idx-catalog-unit") as client:
        response = await client.get("/api/v1/indices/catalog")

    rows = {r["code"]: r for r in response.json()}

    assert rows["lst"]["unit"] == "°C"
    # Everything else is dimensionless. Empty string, not null — it
    # matches `weather_indices_catalog.unit` so the SPA's
    # `${value} ${unit}` shape needs no special case.
    for code in ("ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi", "bsi", "msi"):
        assert rows[code]["unit"] == "", code
    # cwsi and smi are 0-1 indices by construction, not measurements.
    assert rows["cwsi"]["unit"] == ""
    assert rows["smi"]["unit"] == ""


@pytest.mark.asyncio
async def test_lst_bounds_are_a_temperature_range_not_a_ratio(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, "idx-catalog-bounds") as client:
        response = await client.get("/api/v1/indices/catalog")

    rows = {r["code"]: r for r in response.json()}
    assert float(rows["lst"]["value_min"]) == 0.0
    assert float(rows["lst"]["value_max"]) == 60.0


@pytest.mark.asyncio
async def test_catalog_requires_a_tenant_scope(admin_session: AsyncSession) -> None:
    context = make_context(user_id=uuid4(), tenant_id=None, tenant_role=None)
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/indices/catalog")

    assert response.status_code == 403
