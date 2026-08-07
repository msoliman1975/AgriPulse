"""Integration tests for crop attribute definitions (platform authoring + resolve).

Covers the guards that have no other line of defence:

* the reserved-code check (an attribute shadowing ``growth_stage`` would put
  two identically-named entries in the decision-tree condition builder, one of
  which never resolves, with no error anywhere);
* gate validation (a gate pointing at a missing, non-gateable, or
  later-authored attribute silently never opens);
* deepest-wins resolution and suppression through the API, not just the pure
  resolver.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(),
        tenant_id=None,
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _tenant_client(admin_session: AsyncSession, slug: str) -> AsyncClient:
    """A tenant-scoped client. Definitions are platform-curated but every read
    goes through a tenant context, so the reads need a real tenant."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _make_crop(client: AsyncClient, *, depth: str = "variety_strain") -> tuple[str, str]:
    code = f"tree-{uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/admin/crops",
        json={
            "code": code,
            "name_en": "Test Tree",
            "name_ar": "شجرة اختبار",
            "category": "fruit_tree",
            "is_perennial": True,
            "classification_depth": depth,
        },
    )
    assert r.status_code == 201, r.text
    return code, r.json()["id"]


def _method_payload(**overrides) -> dict:
    payload = {
        "code": "establishment_method",
        "name_en": "Establishment method",
        "name_ar": "طريقة التأسيس",
        "value_type": "single_select",
        "is_required": True,
        "sort_order": 1,
        "group_code": "establishment",
        "options": [
            {"code": "seed", "name_en": "Seed", "name_ar": "بذرة", "sort_order": 1},
            {
                "code": "grafted_tree",
                "name_en": "Grafted tree",
                "name_ar": "شجرة مطعمة",
                "sort_order": 2,
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_authoring_roundtrip_with_gates() -> None:
    async with _platform_client() as client:
        crop_code, crop_id = await _make_crop(client)

        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json=_method_payload(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["path"] == crop_code
        assert r.json()["is_reportable"] is True

        # A gated, conditionally-required field.
        gate = {"code": "establishment_method", "in": ["grafted_tree"]}
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "age_at_transplant_months",
                "name_en": "Age at transplant",
                "name_ar": "عمر الشجرة عند الشتل",
                "value_type": "integer",
                "unit_en": "months",
                "unit_ar": "شهر",
                "value_min": 0,
                "value_max": 600,
                "sort_order": 2,
                "show_when": gate,
                "required_when": gate,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # The gate must round-trip under its wire name ``in`` — the evaluator
        # and the frontend both read that key, not the Python-safe ``in_``.
        assert body["show_when"] == gate
        assert body["required_when"] == gate

        # Same code on the same node → 409.
        dup = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json=_method_payload(sort_order=9),
        )
        assert dup.status_code == 409


@pytest.mark.asyncio
async def test_reserved_code_is_rejected() -> None:
    async with _platform_client() as client:
        _code, crop_id = await _make_crop(client)
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "growth_stage",
                "name_en": "Growth stage",
                "name_ar": "مرحلة النمو",
                "value_type": "text",
            },
        )
        assert r.status_code == 422, r.text
        assert "reserved" in r.json()["type"]


@pytest.mark.asyncio
async def test_gate_must_point_at_an_existing_gateable_earlier_field() -> None:
    async with _platform_client() as client:
        _code, crop_id = await _make_crop(client)

        # Unknown target → the gate would never open, and nothing would say so.
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "transplant_date",
                "name_en": "Transplant date",
                "name_ar": "تاريخ الشتل",
                "value_type": "date",
                "sort_order": 5,
                "show_when": {"code": "nope", "in": ["x"]},
            },
        )
        assert r.status_code == 422
        assert "not defined" in r.json()["detail"]

        await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json=_method_payload(sort_order=5),
        )

        # Forward reference (target sorts at or after the gated field).
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "transplant_date",
                "name_en": "Transplant date",
                "name_ar": "تاريخ الشتل",
                "value_type": "date",
                "sort_order": 5,
                "show_when": {"code": "establishment_method", "in": ["grafted_tree"]},
            },
        )
        assert r.status_code == 422
        assert "earlier field" in r.json()["detail"]

        # Testing against a value that is not an option of the target.
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "transplant_date",
                "name_en": "Transplant date",
                "name_ar": "تاريخ الشتل",
                "value_type": "date",
                "sort_order": 6,
                "show_when": {"code": "establishment_method", "in": ["airlayered"]},
            },
        )
        assert r.status_code == 422
        assert "not options" in r.json()["detail"]


@pytest.mark.asyncio
async def test_gate_cannot_point_at_a_numeric_field() -> None:
    async with _platform_client() as client:
        _code, crop_id = await _make_crop(client)
        await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "tree_count",
                "name_en": "Tree count",
                "name_ar": "عدد الأشجار",
                "value_type": "integer",
                "sort_order": 1,
            },
        )
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "notes_field",
                "name_en": "Notes",
                "name_ar": "ملاحظات",
                "value_type": "text",
                "sort_order": 2,
                "show_when": {"code": "tree_count", "eq": "5"},
            },
        )
        assert r.status_code == 422
        assert "can gate a field" in r.json()["detail"]


@pytest.mark.asyncio
async def test_deepest_wins_and_suppression_through_the_api(admin_session: AsyncSession) -> None:
    async with _platform_client() as platform:
        crop_code, crop_id = await _make_crop(platform)
        rv = await platform.post(
            f"/api/v1/admin/crops/{crop_id}/varieties",
            json={"code": "sukkary", "name_en": "Sukkary", "name_ar": "سكري"},
        )
        assert rv.status_code == 201, rv.text
        variety_id = rv.json()["id"]

        # Crop level: range 0-2000.
        await platform.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "transplant_height_cm",
                "name_en": "Height at transplant",
                "name_ar": "ارتفاع الشجرة",
                "value_type": "decimal",
                "unit_en": "cm",
                "unit_ar": "سم",
                "value_min": 0,
                "value_max": 2000,
                "sort_order": 1,
            },
        )
        # Crop level: an attribute the variety will suppress.
        await platform.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "rootstock_type",
                "name_en": "Rootstock",
                "name_ar": "الأصل",
                "value_type": "single_select",
                "sort_order": 2,
                "options": [{"code": "local", "name_en": "Local", "name_ar": "بلدي"}],
            },
        )
        # Variety level: narrow the range.
        await platform.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "crop_variety_id": variety_id,
                "code": "transplant_height_cm",
                "name_en": "Height at transplant",
                "name_ar": "ارتفاع الشجرة",
                "value_type": "decimal",
                "unit_en": "cm",
                "unit_ar": "سم",
                "value_min": 0,
                "value_max": 250,
                "sort_order": 1,
            },
        )
        # Variety level: suppress the inherited rootstock attribute.
        r = await platform.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "crop_variety_id": variety_id,
                "code": "rootstock_type",
                "name_en": "Rootstock",
                "name_ar": "الأصل",
                "value_type": "single_select",
                "sort_order": 2,
                "options": [{"code": "local", "name_en": "Local", "name_ar": "بلدي"}],
            },
        )
        suppressed_id = r.json()["id"]
        r = await platform.patch(
            f"/api/v1/admin/crop-attribute-definitions/{suppressed_id}",
            json={"is_active": False},
        )
        assert r.status_code == 200, r.text

    client = await _tenant_client(admin_session, f"ca-res-{uuid4().hex[:6]}")
    async with client as tenant:
        r = await tenant.get("/api/v1/crops/resolved-attributes", params={"crop_path": crop_code})
        assert r.status_code == 200, r.text
        crop_level = {d["code"]: d for d in r.json()["definitions"]}
        assert float(crop_level["transplant_height_cm"]["value_max"]) == 2000
        assert "rootstock_type" in crop_level

        r = await tenant.get(
            "/api/v1/crops/resolved-attributes",
            params={"crop_path": f"{crop_code}.sukkary"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        resolved = {d["code"]: d for d in body["definitions"]}
        # Deeper definition replaces the inherited one wholesale.
        assert float(resolved["transplant_height_cm"]["value_max"]) == 250
        # Deeper inactive row suppresses the inherited attribute entirely.
        assert "rootstock_type" not in resolved
        assert "transplant_height_cm" in body["shadowed_codes"]


@pytest.mark.asyncio
async def test_patch_cannot_reach_a_state_create_would_reject() -> None:
    """``value_type`` is immutable, so the PATCH path re-checks consistency
    against the *stored* type — otherwise a text attribute could grow a
    value_min that the create validator refuses."""
    async with _platform_client() as client:
        _code, crop_id = await _make_crop(client)
        r = await client.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json={
                "code": "nursery_source",
                "name_en": "Nursery",
                "name_ar": "المشتل",
                "value_type": "text",
                "sort_order": 1,
            },
        )
        definition_id = r.json()["id"]

        bad = await client.patch(
            f"/api/v1/admin/crop-attribute-definitions/{definition_id}",
            json={"value_min": 3},
        )
        assert bad.status_code == 422, bad.text
        assert "only valid for" in bad.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_cannot_author_definitions(admin_session: AsyncSession) -> None:
    async with _platform_client() as platform:
        _code, crop_id = await _make_crop(platform)
    client = await _tenant_client(admin_session, f"ca-rbac-{uuid4().hex[:6]}")
    async with client as tenant:
        r = await tenant.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json=_method_payload(),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_catalog_lists_definitions_across_crops(admin_session: AsyncSession) -> None:
    """The flat list the decision-tree condition builder reads — the first
    condition source that is data rather than a frontend constant."""
    async with _platform_client() as platform:
        crop_code, crop_id = await _make_crop(platform)
        await platform.post(
            f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
            json=_method_payload(),
        )
    client = await _tenant_client(admin_session, f"ca-cat-{uuid4().hex[:6]}")
    async with client as tenant:
        r = await tenant.get("/api/v1/crops/attribute-definitions")
        assert r.status_code == 200, r.text
        mine = [d for d in r.json() if d["path"] == crop_code]
        assert [d["code"] for d in mine] == ["establishment_method"]
