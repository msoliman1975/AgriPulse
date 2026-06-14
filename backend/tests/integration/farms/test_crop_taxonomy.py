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

from app.modules.farms.errors import CropTaxonomyError
from app.modules.farms.repository import _resolve_crop_path
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


# ---- exact classification-depth resolver (pure) ----------------------------


def test_path_crop_only() -> None:
    assert (
        _resolve_crop_path(
            depth="crop_only",
            crop_code="cotton",
            crop_variety_id=None,
            variety_path=None,
            crop_variety_strain_id=None,
            strain_path=None,
        )
        == "cotton"
    )


def test_path_variety_strain_full() -> None:
    assert (
        _resolve_crop_path(
            depth="variety_strain",
            crop_code="mango",
            crop_variety_id=uuid4(),
            variety_path="mango.alphonso",
            crop_variety_strain_id=uuid4(),
            strain_path="mango.alphonso.short",
        )
        == "mango.alphonso.short"
    )


def test_path_variety_strain_missing_strain_raises() -> None:
    with pytest.raises(CropTaxonomyError):
        _resolve_crop_path(
            depth="variety_strain",
            crop_code="mango",
            crop_variety_id=uuid4(),
            variety_path="mango.alphonso",
            crop_variety_strain_id=None,
            strain_path=None,
        )


def test_path_crop_only_with_variety_raises() -> None:
    with pytest.raises(CropTaxonomyError):
        _resolve_crop_path(
            depth="crop_only",
            crop_code="cotton",
            crop_variety_id=uuid4(),
            variety_path="x",
            crop_variety_strain_id=None,
            strain_path=None,
        )


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
        # 0030 seeds the alphonso/eswwy worked example; 0033 adds the 5
        # commercial varieties alongside them.
        assert {"alphonso", "eswwy"}.issubset(set(by_code))
        assert by_code["alphonso"]["path"] == "mango.alphonso"
        assert by_code["eswwy"]["path"] == "mango.eswwy"

        alphonso_id = by_code["alphonso"]["id"]
        strains = (await client.get(f"/api/v1/crop-varieties/{alphonso_id}/strains")).json()
        strain_paths = {s["path"] for s in strains}
        assert strain_paths == {"mango.alphonso.short", "mango.alphonso.long"}

        # Empty strains for a variety-less variety is a clean [] (cotton has none).
        cotton_varieties = (await client.get(f"/api/v1/crops/{cotton['id']}/varieties")).json()
        assert cotton_varieties == []
