"""Integration tests for platform crop-catalog authoring (/admin/crops…).

PlatformAdmin can create/edit/retire crops, varieties, and strains; codes
are immutable and paths auto-derive from the parent. Soft-retire via
is_active toggles visibility but keeps the row.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.shared.auth.context import PlatformRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(),
        tenant_id=None,
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    app = build_app(context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_full_catalog_authoring_roundtrip() -> None:
    code = f"durum-{uuid4().hex[:6]}"
    async with _platform_client() as client:
        # Create a variety_strain crop.
        r = await client.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Durum Wheat",
                "name_ar": "قمح ديورم",
                "category": "cereal",
                "is_perennial": False,
                "classification_depth": "variety_strain",
            },
        )
        assert r.status_code == 201, r.text
        crop = r.json()
        assert crop["classification_depth"] == "variety_strain"
        assert crop["is_active"] is True
        crop_id = crop["id"]

        # Duplicate code → 409.
        dup = await client.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Dup",
                "name_ar": "x",
                "category": "cereal",
            },
        )
        assert dup.status_code == 409

        # Add a variety → path derives from crop code.
        rv = await client.post(
            f"/api/v1/admin/crops/{crop_id}/varieties",
            json={"code": "waha", "name_en": "Waha"},
        )
        assert rv.status_code == 201, rv.text
        variety = rv.json()
        assert variety["path"] == f"{code}.waha"
        variety_id = variety["id"]

        # Add a strain → path derives from variety path.
        rs = await client.post(
            f"/api/v1/admin/crop-varieties/{variety_id}/strains",
            json={"code": "early", "name_en": "Early Waha"},
        )
        assert rs.status_code == 201, rs.text
        assert rs.json()["path"] == f"{code}.waha.early"

        # Duplicate variety code under the same crop → 409.
        dupv = await client.post(
            f"/api/v1/admin/crops/{crop_id}/varieties",
            json={"code": "waha", "name_en": "Waha again"},
        )
        assert dupv.status_code == 409

        # Rename the variety.
        ru = await client.patch(
            f"/api/v1/admin/crop-varieties/{variety_id}",
            json={"name_en": "Waha (renamed)"},
        )
        assert ru.status_code == 200
        assert ru.json()["name_en"] == "Waha (renamed)"

        # Retire the crop → hidden by default, visible with include_inactive.
        rr = await client.patch(f"/api/v1/admin/crops/{crop_id}", json={"is_active": False})
        assert rr.status_code == 200
        assert rr.json()["is_active"] is False

        active = (await client.get("/api/v1/admin/crops")).json()
        assert crop_id not in [c["id"] for c in active]
        allc = (await client.get("/api/v1/admin/crops?include_inactive=true")).json()
        assert crop_id in [c["id"] for c in allc]


@pytest.mark.asyncio
async def test_create_crop_with_phenology_and_size_classes() -> None:
    code = f"mango-{uuid4().hex[:6]}"
    async with _platform_client() as client:
        r = await client.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Mango",
                "name_ar": "مانجو",
                "category": "fruit_tree",
                "is_perennial": True,
                "classification_depth": "variety",
                "phenology_stages": {
                    "stages": [
                        {
                            "code": "pre_flowering",
                            "name_en": "Pre-flowering",
                            "name_ar": "ما قبل التزهير",
                            "order": 1,
                            "advance": {
                                "mode": "calendar_doy",
                                "start_doy": "12-01",
                                "end_doy": "01-31",
                            },
                        }
                    ]
                },
                "size_classes": {
                    "classes": [
                        {"code": "small", "name_en": "Small", "name_ar": "صغير", "order": 1},
                        {"code": "large", "name_en": "Large", "name_ar": "كبير", "order": 2},
                    ]
                },
            },
        )
        assert r.status_code == 201, r.text
        crop = r.json()
        assert crop["phenology_stages"]["stages"][0]["code"] == "pre_flowering"
        assert len(crop["size_classes"]["classes"]) == 2


@pytest.mark.asyncio
async def test_create_perennial_crop_rejects_days_from_planting() -> None:
    code = f"mango-{uuid4().hex[:6]}"
    async with _platform_client() as client:
        r = await client.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Mango",
                "name_ar": "مانجو",
                "category": "fruit_tree",
                "is_perennial": True,
                "phenology_stages": {
                    "stages": [
                        {
                            "code": "veg",
                            "name_en": "Veg",
                            "name_ar": "خضري",
                            "order": 1,
                            "advance": {
                                "mode": "days_from_planting",
                                "start_day": 0,
                                "end_day": 40,
                            },
                        }
                    ]
                },
            },
        )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_variety_on_missing_crop_404() -> None:
    async with _platform_client() as client:
        r = await client.post(
            f"/api/v1/admin/crops/{uuid4()}/varieties",
            json={"code": "x", "name_en": "X"},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_authoring_forbidden_without_platform_cap() -> None:
    # A tenant-only context (no platform role) must be rejected.
    from app.shared.auth.context import TenantRole

    context = make_context(
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_role=TenantRole.TENANT_OWNER,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/admin/crops",
            json={"code": "nope", "name_en": "N", "name_ar": "ن", "category": "cereal"},
        )
        assert r.status_code == 403
