"""Verify migration 0033 seeds mango + potato phenology / size classes
and that every seeded payload passes the PR-A1 shape validators.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.phenology import (
    validate_phenology_payload,
    validate_size_classes_payload,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_mango_seed_and_validators(admin_session: AsyncSession) -> None:
    crop = (
        await admin_session.execute(
            text(
                "SELECT phenology_stages, size_classes, classification_depth, "
                " relevant_indices FROM public.crops WHERE code = 'mango'"
            )
        )
    ).one()
    pheno, sizes, depth, indices = crop
    # 0030 set mango to variety_strain; this migration must not change it.
    assert depth == "variety_strain"
    assert {"ndre", "ndmi", "savi"}.issubset(set(indices))
    # Seeded crop payloads pass the validators (perennial -> calendar/manual).
    validate_phenology_payload(pheno, is_perennial=True, has_gdd_base=False)
    validate_size_classes_payload(sizes)
    stage_codes = {s["code"] for s in pheno["stages"]}
    assert "pre_flowering" in stage_codes
    assert "post_harvest_flush" in stage_codes

    varieties = (
        await admin_session.execute(
            text(
                "SELECT code, phenology_stages_override FROM public.crop_varieties WHERE path LIKE 'mango.%'"
            )
        )
    ).all()
    codes = {c for c, _ in varieties}
    # The 5 commercial varieties seeded here live alongside the 0030 example rows.
    assert {"keitt", "yasmina", "sukkary", "zebda", "crimson"}.issubset(codes)
    # Keitt carries a phenology override; it must validate too.
    keitt_pheno = next(p for c, p in varieties if c == "keitt")
    validate_phenology_payload(keitt_pheno, is_perennial=True, has_gdd_base=False)


@pytest.mark.asyncio
async def test_potato_seed_is_annual(admin_session: AsyncSession) -> None:
    pheno = (
        await admin_session.execute(
            text("SELECT phenology_stages FROM public.crops WHERE code = 'potato'")
        )
    ).scalar_one()
    assert pheno is not None
    # Annual crop -> days_from_planting must be allowed, calendar_doy rejected.
    validate_phenology_payload(pheno, is_perennial=False, has_gdd_base=True)
    assert pheno["stages"][0]["advance"]["mode"] == "days_from_planting"


@pytest.mark.asyncio
async def test_resolved_taxonomy_returns_keitt_override(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pheno-seed-resolve",
        name="Pheno Seed",
        contact_email="ops@pheno-seed.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    await admin_session.commit()

    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/crops/resolved-taxonomy", params={"crop_path": "mango.keitt"})
        assert r.status_code == 200, r.text
        body = r.json()
        pre = next(s for s in body["phenology_stages"]["stages"] if s["code"] == "pre_flowering")
        # Keitt's override shifts the induction window start to mid-December.
        assert pre["advance"]["start_doy"] == "12-15"
        # Size classes fall back to the mango crop default (3 classes).
        assert len(body["size_classes"]["classes"]) == 3
