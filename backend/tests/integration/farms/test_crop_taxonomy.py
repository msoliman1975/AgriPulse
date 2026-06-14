"""Crop taxonomy catalog (Crop -> Variety -> Strain) — migration 0030.

Relies on the Mango worked-example seeded by migration 0030
(Mango[variety_strain] -> {Alphonso, Eswwy} -> {Short, Long}). Asserts
the catalog endpoints expose classification_depth + hierarchical path
codes and the new strains endpoint.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_taxonomy_depth_varieties_strains_and_paths(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="ct-taxonomy",
        name="CT Taxonomy",
        contact_email="ops@ct-taxonomy.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        crops = (await client.get("/api/v1/crops")).json()
        mango = next((c for c in crops if c["code"] == "mango"), None)
        assert mango is not None, "mango seeded crop missing"
        assert mango["classification_depth"] == "variety_strain"

        # A crop with no subdivision stays crop_only.
        cotton = next((c for c in crops if c["code"] == "cotton"), None)
        assert cotton is not None
        assert cotton["classification_depth"] == "crop_only"

        varieties = (await client.get(f"/api/v1/crops/{mango['id']}/varieties")).json()
        by_code = {v["code"]: v for v in varieties}
        assert set(by_code) == {"alphonso", "eswwy"}
        assert by_code["alphonso"]["path"] == "mango.alphonso"
        assert by_code["eswwy"]["path"] == "mango.eswwy"

        alphonso_id = by_code["alphonso"]["id"]
        strains = (await client.get(f"/api/v1/crop-varieties/{alphonso_id}/strains")).json()
        strain_paths = {s["path"] for s in strains}
        assert strain_paths == {"mango.alphonso.short", "mango.alphonso.long"}

        # Empty strains for a variety-less variety is a clean [] (cotton has none).
        cotton_varieties = (await client.get(f"/api/v1/crops/{cotton['id']}/varieties")).json()
        assert cotton_varieties == []
