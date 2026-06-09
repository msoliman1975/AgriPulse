"""GET /api/v1/weather/providers — provider catalog endpoint.

Surfaced for the SPA's subscriptions-template editor to populate its
provider picker (replaces a free-text input that was easy to typo).
The endpoint is tenant-scoped (any authenticated user with a tenant
JWT) but the row source — `public.weather_providers` — is platform-
wide curated catalog data, not per-farm.
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
async def test_lists_active_providers_ordered_by_name(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-catalog-list",
        name="Weather Catalog List",
        contact_email="ops@catalog.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    # Add a second active provider + one inactive provider so we exercise
    # ordering + the is_active filter without depending on what else
    # happens to be seeded.
    await admin_session.execute(
        text(
            "INSERT INTO public.weather_providers (code, name, kind, is_active) "
            "VALUES ('zz_active_other', 'AAA Other Provider', 'open_api', TRUE), "
            "       ('zz_inactive', 'Inactive Provider', 'open_api', FALSE) "
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
        resp = await client.get("/api/v1/weather/providers")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        codes = [row["code"] for row in body]

        # Active rows surface; inactive row does not.
        assert "open_meteo" in codes, body
        assert "zz_active_other" in codes, body
        assert "zz_inactive" not in codes, body

        # Ordered by name ascending — "AAA Other Provider" should come
        # before "Open-Meteo" lexically.
        names = [row["name"] for row in body]
        assert names == sorted(names), names

        # Schema shape: code/name/kind only.
        sample = next(r for r in body if r["code"] == "open_meteo")
        assert set(sample.keys()) == {"code", "name", "kind"}, sample
