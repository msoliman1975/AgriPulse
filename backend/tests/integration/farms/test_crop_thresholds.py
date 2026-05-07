"""Tests for `crop_thresholds.resolve_*` + the catalog endpoints surfacing
the new fields after migration 0011 (PR-2).

Pure-function tests don't need a DB but still ride the integration
marker so pytest discovery groups them with the rest of the farms
suite. The integration tests inject thresholds directly via SQL
because there's no admin write API yet — that lands with the alerts
module (PR-5).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.crop_thresholds import resolve_phenology_stages, resolve_thresholds
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_resolve_thresholds_variety_wins_per_key() -> None:
    out = resolve_thresholds(
        crop_thresholds={"ndvi_deviation_warning_pct": -10, "frost_threshold_c": 2},
        variety_thresholds={"ndvi_deviation_warning_pct": -15},
    )
    assert out == {"ndvi_deviation_warning_pct": -15, "frost_threshold_c": 2}


def test_resolve_thresholds_variety_only_when_crop_null() -> None:
    out = resolve_thresholds(
        crop_thresholds=None,
        variety_thresholds={"chill_hours_required": 200},
    )
    assert out == {"chill_hours_required": 200}


def test_resolve_thresholds_crop_only_when_variety_null() -> None:
    out = resolve_thresholds(
        crop_thresholds={"frost_threshold_c": 2},
        variety_thresholds=None,
    )
    assert out == {"frost_threshold_c": 2}


def test_resolve_thresholds_both_null_yields_empty() -> None:
    assert resolve_thresholds(crop_thresholds=None, variety_thresholds=None) == {}


def test_resolve_phenology_override_wholesale() -> None:
    crop_stages = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]}
    variety_override = {
        "stages": [
            {"name": "vegetative", "start_gdd": 0, "end_gdd": 400},
            {"name": "reproductive", "start_gdd": 400, "end_gdd": 900},
        ]
    }
    assert (
        resolve_phenology_stages(crop_stages=crop_stages, variety_override=variety_override)
        is variety_override
    )


def test_resolve_phenology_inherits_when_no_override() -> None:
    crop_stages = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]}
    assert resolve_phenology_stages(crop_stages=crop_stages, variety_override=None) is crop_stages


def test_resolve_phenology_returns_none_when_neither_present() -> None:
    assert resolve_phenology_stages(crop_stages=None, variety_override=None) is None


# ---------------------------------------------------------------------------
# Catalog endpoints expose the new fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crops_catalog_exposes_thresholds(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr2-crops-cat",
        name="PR-2 Crops",
        contact_email="ops@pr2-crops.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    # Seed a synthetic crop + variety with thresholds set. Real catalog
    # rows are seeded by migration 0006; the alerts admin endpoint
    # (PR-5) will be the first first-class write path.
    crop_id = uuid4()
    variety_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.crops "
            "(id, code, name_en, name_ar, category, is_perennial, "
            " gdd_base_temp_c, default_thresholds, phenology_stages, is_active) "
            "VALUES (:id, :code, 'PR2 Crop', 'محصول 2', 'cereal', FALSE, "
            "        10, CAST(:thresh AS jsonb), CAST(:stages AS jsonb), TRUE)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": crop_id,
            "code": f"pr2-crop-{crop_id.hex[:6]}",
            "thresh": '{"ndvi_deviation_warning_pct": -10, "frost_threshold_c": 2}',
            "stages": '{"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]}',
        },
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.crop_varieties "
            "(id, crop_id, code, name_en, default_thresholds, "
            " phenology_stages_override, is_active) "
            "VALUES (:vid, :cid, :code, 'PR2 Variety', "
            "        CAST(:thresh AS jsonb), CAST(:stages AS jsonb), TRUE)"
        ).bindparams(
            bindparam("vid", type_=PG_UUID(as_uuid=True)),
            bindparam("cid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "vid": variety_id,
            "cid": crop_id,
            "code": f"pr2-var-{variety_id.hex[:6]}",
            "thresh": '{"ndvi_deviation_warning_pct": -15}',
            "stages": '{"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 400}]}',
        },
    )
    await admin_session.commit()

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        crops = (await client.get("/api/v1/crops")).json()
        ours_crop = next((c for c in crops if c["id"] == str(crop_id)), None)
        assert ours_crop is not None, "seeded crop missing from /api/v1/crops"
        assert ours_crop["default_thresholds"] == {
            "ndvi_deviation_warning_pct": -10,
            "frost_threshold_c": 2,
        }
        assert ours_crop["phenology_stages"] == {
            "stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]
        }
        assert ours_crop["gdd_base_temp_c"] == "10.0"

        varieties = (await client.get(f"/api/v1/crops/{crop_id}/varieties")).json()
        assert len(varieties) == 1
        v = varieties[0]
        assert v["default_thresholds"] == {"ndvi_deviation_warning_pct": -15}
        assert v["phenology_stages_override"] == {
            "stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 400}]
        }

    # Verify resolve_thresholds composes correctly against the seeded data.
    merged = resolve_thresholds(
        crop_thresholds=ours_crop["default_thresholds"],
        variety_thresholds=v["default_thresholds"],
    )
    assert merged == {"ndvi_deviation_warning_pct": -15, "frost_threshold_c": 2}
