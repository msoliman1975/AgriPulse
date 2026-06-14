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

from app.modules.farms.crop_thresholds import (
    resolve_phenology_stages,
    resolve_size_classes,
    resolve_thresholds,
)
from app.modules.farms.phenology import (
    validate_phenology_payload,
    validate_size_classes_payload,
)
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


def test_resolve_thresholds_strain_wins_over_variety_and_crop() -> None:
    out = resolve_thresholds(
        crop_thresholds={"ndvi_deviation_warning_pct": -10, "frost_threshold_c": 2},
        variety_thresholds={"ndvi_deviation_warning_pct": -15},
        strain_thresholds={"frost_threshold_c": 0},
    )
    assert out == {"ndvi_deviation_warning_pct": -15, "frost_threshold_c": 0}


def test_resolve_thresholds_strain_only_when_others_null() -> None:
    out = resolve_thresholds(
        crop_thresholds=None,
        variety_thresholds=None,
        strain_thresholds={"chill_hours_required": 150},
    )
    assert out == {"chill_hours_required": 150}


def test_resolve_phenology_strain_override_beats_variety() -> None:
    crop_stages = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]}
    variety_override = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 400}]}
    strain_override = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 350}]}
    assert (
        resolve_phenology_stages(
            crop_stages=crop_stages,
            variety_override=variety_override,
            strain_override=strain_override,
        )
        is strain_override
    )


def test_resolve_phenology_falls_back_to_variety_when_strain_null() -> None:
    crop_stages = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 500}]}
    variety_override = {"stages": [{"name": "vegetative", "start_gdd": 0, "end_gdd": 400}]}
    assert (
        resolve_phenology_stages(
            crop_stages=crop_stages,
            variety_override=variety_override,
            strain_override=None,
        )
        is variety_override
    )


# ---------------------------------------------------------------------------
# Size-class resolution (mirrors phenology: wholesale deepest-wins)
# ---------------------------------------------------------------------------


def test_resolve_size_classes_strain_wins() -> None:
    crop = {"classes": [{"code": "small", "name_en": "S", "name_ar": "ص", "order": 1}]}
    variety = {"classes": [{"code": "medium", "name_en": "M", "name_ar": "م", "order": 1}]}
    strain = {"classes": [{"code": "large", "name_en": "L", "name_ar": "ك", "order": 1}]}
    assert (
        resolve_size_classes(crop_classes=crop, variety_override=variety, strain_override=strain)
        is strain
    )


def test_resolve_size_classes_falls_back_to_crop() -> None:
    crop = {"classes": [{"code": "small", "name_en": "S", "name_ar": "ص", "order": 1}]}
    assert (
        resolve_size_classes(crop_classes=crop, variety_override=None, strain_override=None) is crop
    )


def test_resolve_size_classes_none_when_absent() -> None:
    assert resolve_size_classes(crop_classes=None, variety_override=None) is None


# ---------------------------------------------------------------------------
# Phenology / size-class shape validation
# ---------------------------------------------------------------------------

_PERENNIAL_STAGES = {
    "stages": [
        {
            "code": "pre_flowering",
            "name_en": "Pre-flowering",
            "name_ar": "ما قبل التزهير",
            "order": 1,
            "advance": {"mode": "calendar_doy", "start_doy": "12-01", "end_doy": "01-31"},
        }
    ]
}

_ANNUAL_STAGES = {
    "stages": [
        {
            "code": "vegetative",
            "name_en": "Vegetative",
            "name_ar": "نمو خضري",
            "order": 1,
            "advance": {"mode": "days_from_planting", "start_day": 0, "end_day": 40},
        }
    ]
}


def test_validate_phenology_perennial_calendar_ok() -> None:
    out = validate_phenology_payload(_PERENNIAL_STAGES, is_perennial=True, has_gdd_base=False)
    assert out.stages[0].advance.mode == "calendar_doy"


def test_validate_phenology_annual_days_ok() -> None:
    out = validate_phenology_payload(_ANNUAL_STAGES, is_perennial=False, has_gdd_base=False)
    assert out.stages[0].advance.mode == "days_from_planting"


def test_validate_phenology_perennial_rejects_days_mode() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_phenology_payload(_ANNUAL_STAGES, is_perennial=True, has_gdd_base=False)


def test_validate_phenology_annual_rejects_calendar_doy() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_phenology_payload(_PERENNIAL_STAGES, is_perennial=False, has_gdd_base=False)


def test_validate_phenology_gdd_requires_base() -> None:
    gdd = {
        "stages": [
            {
                "code": "veg",
                "name_en": "Veg",
                "name_ar": "خضري",
                "order": 1,
                "advance": {"mode": "gdd_from_planting", "start_gdd": 0, "end_gdd": 500},
            }
        ]
    }
    with pytest.raises(ValueError, match="gdd_base_temp_c"):
        validate_phenology_payload(gdd, is_perennial=False, has_gdd_base=False)
    # With a base temp it passes.
    assert validate_phenology_payload(gdd, is_perennial=False, has_gdd_base=True)


def test_validate_phenology_rejects_duplicate_codes() -> None:
    dup = {
        "stages": [
            {
                "code": "veg",
                "name_en": "A",
                "name_ar": "أ",
                "order": 1,
                "advance": {"mode": "manual"},
            },
            {
                "code": "veg",
                "name_en": "B",
                "name_ar": "ب",
                "order": 2,
                "advance": {"mode": "manual"},
            },
        ]
    }
    with pytest.raises(ValueError, match="unique"):
        validate_phenology_payload(dup, is_perennial=True, has_gdd_base=False)


def test_validate_phenology_rejects_bad_doy() -> None:
    bad = {
        "stages": [
            {
                "code": "x",
                "name_en": "X",
                "name_ar": "س",
                "order": 1,
                "advance": {"mode": "calendar_doy", "start_doy": "13-40", "end_doy": "01-31"},
            }
        ]
    }
    with pytest.raises(ValueError, match="MM-DD"):
        validate_phenology_payload(bad, is_perennial=True, has_gdd_base=False)


def test_validate_size_classes_ok_and_dup_rejected() -> None:
    ok = {
        "classes": [
            {"code": "small", "name_en": "S", "name_ar": "ص", "order": 1},
            {"code": "large", "name_en": "L", "name_ar": "ك", "order": 2},
        ]
    }
    assert validate_size_classes_payload(ok)
    dup = {
        "classes": [
            {"code": "small", "name_en": "S", "name_ar": "ص", "order": 1},
            {"code": "small", "name_en": "S2", "name_ar": "ص٢", "order": 2},
        ]
    }
    with pytest.raises(ValueError, match="unique"):
        validate_size_classes_payload(dup)


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


@pytest.mark.asyncio
async def test_resolved_taxonomy_endpoint_merges_levels(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pheno-resolve",
        name="Pheno Resolve",
        contact_email="ops@pheno-resolve.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    crop_id = uuid4()
    variety_id = uuid4()
    crop_code = f"mango-{crop_id.hex[:6]}"
    crop_stages = (
        '{"stages": [{"code": "veg_flush", "name_en": "Flush", "name_ar": "نمو", '
        '"order": 1, "advance": {"mode": "calendar_doy", "start_doy": "03-01", '
        '"end_doy": "05-15"}}]}'
    )
    crop_sizes = (
        '{"classes": [{"code": "small", "name_en": "Small", "name_ar": "صغير", "order": 1}]}'
    )
    variety_stages = (
        '{"stages": [{"code": "pre_flowering", "name_en": "Pre-flower", '
        '"name_ar": "تزهير", "order": 1, "advance": {"mode": "calendar_doy", '
        '"start_doy": "12-01", "end_doy": "01-31"}}]}'
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.crops "
            "(id, code, name_en, name_ar, category, is_perennial, "
            " phenology_stages, size_classes, classification_depth, is_active) "
            "VALUES (:id, :code, 'Mango', 'مانجو', 'fruit_tree', TRUE, "
            "        CAST(:stages AS jsonb), CAST(:sizes AS jsonb), 'variety', TRUE)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": crop_id, "code": crop_code, "stages": crop_stages, "sizes": crop_sizes},
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.crop_varieties "
            "(id, crop_id, code, name_en, path, phenology_stages_override, is_active) "
            "VALUES (:vid, :cid, 'keitt', 'Keitt', :path, CAST(:stages AS jsonb), TRUE)"
        ).bindparams(
            bindparam("vid", type_=PG_UUID(as_uuid=True)),
            bindparam("cid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "vid": variety_id,
            "cid": crop_id,
            "path": f"{crop_code}.keitt",
            "stages": variety_stages,
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
        # Variety path → variety phenology override wins; size falls back to crop.
        r = await client.get(
            "/api/v1/crops/resolved-taxonomy", params={"crop_path": f"{crop_code}.keitt"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["phenology_stages"]["stages"][0]["code"] == "pre_flowering"
        assert body["size_classes"]["classes"][0]["code"] == "small"

        # Crop path → crop's own phenology.
        r2 = await client.get("/api/v1/crops/resolved-taxonomy", params={"crop_path": crop_code})
        assert r2.status_code == 200, r2.text
        assert r2.json()["phenology_stages"]["stages"][0]["code"] == "veg_flush"
