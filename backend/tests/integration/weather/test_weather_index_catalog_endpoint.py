"""GET /api/v1/weather/indices/catalog — weather-index catalog endpoint.

Surfaced for the SPA's weather-index picker + "why this matters"
tooltips (Weather-Indices PR-W1). Tenant-scoped like the provider
catalog, but the row source — `public.weather_indices_catalog` — is
platform-wide curated data, not per-farm. Active rows only, ordered by
`sort_order`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_lists_active_indices_ordered_by_sort_order(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-index-catalog",
        name="Weather Index Catalog",
        contact_email="ops@windex.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    # An inactive row must be filtered out of the response.
    await admin_session.execute(
        text(
            "INSERT INTO public.weather_indices_catalog "
            "(code, name_en, unit, source_kind, sort_order, is_active) "
            "VALUES ('zz_inactive_idx', 'Inactive Idx', 'mm', 'observed', 99, FALSE) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    await admin_session.commit()

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/weather/indices/catalog")
        assert resp.status_code == 200, resp.text
        body = resp.json()

    codes = [row["code"] for row in body]
    # Every seeded index surfaces; the inactive row does not. Order is
    # append-only: 0049 put `humidity` at 8 and 0057 the gap-audit trio at
    # 9-11, each time leaving the earlier rows where they were.
    assert codes == [
        "temperature",
        "radiation",
        "wind",
        "rainfall",
        "evapotranspiration",
        "evaporation_coeff",
        "rain_et_balance",
        "humidity",
        "leaf_wetness",
        "frost_risk",
        "heat_stress",
    ], codes
    assert "zz_inactive_idx" not in codes, codes

    # Ordered by sort_order ascending.
    orders = [row["sort_order"] for row in body]
    assert orders == sorted(orders), orders

    # Schema shape carries the agronomy relationship metadata + EN/AR names.
    temp = next(r for r in body if r["code"] == "temperature")
    assert temp["name_en"] == "Max/Min Temperature"
    assert temp["name_ar"]
    assert temp["unit"] == "°C"
    assert temp["source_kind"] == "observed"
    assert temp["relation_disease_en"]
    assert temp["relation_insect_ar"]

    # Same for humidity (0049) — the SPA picker reads name/unit off this row.
    hum = next(r for r in body if r["code"] == "humidity")
    assert hum["name_en"] == "Relative Humidity"
    assert hum["name_ar"]
    assert hum["unit"] == "%"
    assert hum["source_kind"] == "observed"
    assert hum["relation_disease_en"]
    assert hum["relation_insect_ar"]
