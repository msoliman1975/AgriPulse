"""Integration tests for crop attribute values on a block assignment.

The behaviours here have no other line of defence:

* a closed gate **deletes** the value and records ``cleared_by_gate`` — a
  stale ``transplant_date`` surviving a switch back to Seed would reappear in
  reports and decision trees;
* conditional requiredness is enforced server-side, not only by the form;
* an omitted code keeps its stored value (omission is "unchanged", not
  "clear") — otherwise a partial client would silently wipe fields;
* an unchanged value writes no history row, or the timeline fills with saves
  that changed nothing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import build_app, make_context
from .test_block_crops import _multipolygon, _polygon
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]

_GATE = {"code": "establishment_method", "in": ["grafted_tree", "transplanted_tree"]}


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _seed_catalog(platform: AsyncClient) -> str:
    """A perennial crop carrying the establishment attribute group."""
    crop_code = f"tree-{uuid4().hex[:6]}"
    r = await platform.post(
        "/api/v1/admin/crops",
        json={
            "code": crop_code,
            "name_en": "Test Tree",
            "name_ar": "شجرة اختبار",
            "category": "fruit_tree",
            "is_perennial": True,
        },
    )
    assert r.status_code == 201, r.text
    crop_id = r.json()["id"]

    await platform.post(
        f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
        json={
            "code": "establishment_method",
            "name_en": "Establishment method",
            "name_ar": "طريقة التأسيس",
            "value_type": "single_select",
            "is_required": True,
            "sort_order": 1,
            "options": [
                {"code": "seed", "name_en": "Seed", "name_ar": "بذرة"},
                {"code": "grafted_tree", "name_en": "Grafted tree", "name_ar": "شجرة مطعمة"},
                {
                    "code": "transplanted_tree",
                    "name_en": "Transplanted tree",
                    "name_ar": "شجرة منقولة",
                },
            ],
        },
    )
    await platform.post(
        f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
        json={
            "code": "transplant_date",
            "name_en": "Transplant date",
            "name_ar": "تاريخ الشتل",
            "value_type": "date",
            "sort_order": 2,
            "show_when": _GATE,
            "required_when": _GATE,
        },
    )
    await platform.post(
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
            "sort_order": 3,
            "show_when": _GATE,
        },
    )
    await platform.post(
        f"/api/v1/admin/crops/{crop_id}/attribute-definitions",
        json={
            "code": "nursery_source",
            "name_en": "Nursery",
            "name_ar": "المشتل",
            "value_type": "text",
            "sort_order": 4,
        },
    )
    return crop_code


async def _tenant_client(admin_session: AsyncSession, slug: str) -> AsyncClient:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _make_assignment(client: AsyncClient, crop_code: str) -> str:
    """A farm → block → crop assignment for ``crop_code``."""
    r = await client.post(
        "/api/v1/farms",
        json={
            "code": f"F-{uuid4().hex[:5]}",
            "name": "Attr Farm",
            "boundary": _multipolygon(31.2, 30.0),
        },
    )
    assert r.status_code == 201, r.text
    farm_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": f"B-{uuid4().hex[:5]}", "boundary": _polygon(31.2, 30.0)},
    )
    assert r.status_code == 201, r.text
    block_id = r.json()["id"]

    crops = await client.get("/api/v1/crops")
    crop = next(c for c in crops.json() if c["code"] == crop_code)

    r = await client.post(
        f"/api/v1/blocks/{block_id}/crop-assignments",
        json={"crop_id": crop["id"], "season_label": "2026"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_save_read_and_gate_clearing(admin_session: AsyncSession) -> None:
    async with _platform_client() as platform:
        crop_code = await _seed_catalog(platform)

    client = await _tenant_client(admin_session, f"bca-gate-{uuid4().hex[:6]}")
    async with client as tenant:
        assignment_id = await _make_assignment(tenant, crop_code)
        url = f"/api/v1/crop-assignments/{assignment_id}/attributes"

        # Definitions ship with the values so the form renders from one call.
        r = await tenant.get(url)
        assert r.status_code == 200, r.text
        assert [d["code"] for d in r.json()["definitions"]] == [
            "establishment_method",
            "transplant_date",
            "age_at_transplant_months",
            "nursery_source",
        ]
        assert r.json()["values"] == {}

        r = await tenant.put(
            url,
            json={
                "attributes": {
                    "establishment_method": "grafted_tree",
                    "transplant_date": "2023-02-18",
                    "age_at_transplant_months": 30,
                    "nursery_source": "Nubaria Nursery Co.",
                }
            },
        )
        assert r.status_code == 200, r.text
        values = r.json()["values"]
        assert values["establishment_method"] == "grafted_tree"
        assert values["transplant_date"] == "2023-02-18"
        assert values["nursery_source"] == "Nubaria Nursery Co."

        # Switch back to Seed: the gated fields must be gone, not merely hidden.
        r = await tenant.put(url, json={"attributes": {"establishment_method": "seed"}})
        assert r.status_code == 200, r.text
        values = r.json()["values"]
        assert values["establishment_method"] == "seed"
        assert "transplant_date" not in values
        assert "age_at_transplant_months" not in values
        # An ungated field is untouched by the gate change.
        assert values["nursery_source"] == "Nubaria Nursery Co."

        history = await tenant.get(f"{url}/history", params={"code": "transplant_date"})
        assert history.status_code == 200, history.text
        kinds = [h["change_kind"] for h in history.json()]
        assert kinds == ["cleared_by_gate", "set"]
        assert history.json()[0]["previous_value"] == "2023-02-18"


@pytest.mark.asyncio
async def test_partial_save_does_not_close_gates_on_omitted_fields(
    admin_session: AsyncSession,
) -> None:
    """Gates are evaluated against stored-plus-submitted, not the submission.

    A client sending only ``age_at_transplant_months`` must not look like it
    cleared ``establishment_method`` — that would close the gate and delete
    the transplant fields as a side effect of editing one of them.
    """
    async with _platform_client() as platform:
        crop_code = await _seed_catalog(platform)

    client = await _tenant_client(admin_session, f"bca-partial-{uuid4().hex[:6]}")
    async with client as tenant:
        assignment_id = await _make_assignment(tenant, crop_code)
        url = f"/api/v1/crop-assignments/{assignment_id}/attributes"

        await tenant.put(
            url,
            json={
                "attributes": {
                    "establishment_method": "grafted_tree",
                    "transplant_date": "2023-02-18",
                    "age_at_transplant_months": 30,
                }
            },
        )
        r = await tenant.put(url, json={"attributes": {"age_at_transplant_months": 36}})
        assert r.status_code == 200, r.text
        values = r.json()["values"]
        assert values["establishment_method"] == "grafted_tree"
        assert values["transplant_date"] == "2023-02-18"
        assert float(values["age_at_transplant_months"]) == 36

        history = await tenant.get(f"{url}/history", params={"code": "transplant_date"})
        assert [h["change_kind"] for h in history.json()] == ["set"]


@pytest.mark.asyncio
async def test_conditional_requiredness_is_enforced_server_side(
    admin_session: AsyncSession,
) -> None:
    async with _platform_client() as platform:
        crop_code = await _seed_catalog(platform)

    client = await _tenant_client(admin_session, f"bca-req-{uuid4().hex[:6]}")
    async with client as tenant:
        assignment_id = await _make_assignment(tenant, crop_code)
        url = f"/api/v1/crop-assignments/{assignment_id}/attributes"

        # transplant_date is required once the method is grafted_tree.
        r = await tenant.put(url, json={"attributes": {"establishment_method": "grafted_tree"}})
        assert r.status_code == 422, r.text
        assert "transplant_date" in r.json()["detail"]

        # ...and not required for seed.
        r = await tenant.put(url, json={"attributes": {"establishment_method": "seed"}})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_out_of_range_and_unknown_codes_are_rejected(
    admin_session: AsyncSession,
) -> None:
    async with _platform_client() as platform:
        crop_code = await _seed_catalog(platform)

    client = await _tenant_client(admin_session, f"bca-val-{uuid4().hex[:6]}")
    async with client as tenant:
        assignment_id = await _make_assignment(tenant, crop_code)
        url = f"/api/v1/crop-assignments/{assignment_id}/attributes"

        r = await tenant.put(
            url,
            json={
                "attributes": {
                    "establishment_method": "grafted_tree",
                    "transplant_date": "2023-02-18",
                    "age_at_transplant_months": 9999,
                }
            },
        )
        assert r.status_code == 422
        assert "above the maximum" in r.json()["detail"]

        r = await tenant.put(url, json={"attributes": {"made_up_code": 1}})
        assert r.status_code == 422
        assert "not attributes of" in r.json()["detail"]

        r = await tenant.put(url, json={"attributes": {"establishment_method": "airlayered"}})
        assert r.status_code == 422
        assert "is not one of" in r.json()["detail"]


@pytest.mark.asyncio
async def test_omitted_code_keeps_its_value_and_unchanged_writes_no_history(
    admin_session: AsyncSession,
) -> None:
    async with _platform_client() as platform:
        crop_code = await _seed_catalog(platform)

    client = await _tenant_client(admin_session, f"bca-omit-{uuid4().hex[:6]}")
    async with client as tenant:
        assignment_id = await _make_assignment(tenant, crop_code)
        url = f"/api/v1/crop-assignments/{assignment_id}/attributes"

        await tenant.put(
            url,
            json={
                "attributes": {
                    "establishment_method": "seed",
                    "nursery_source": "Nubaria Nursery Co.",
                }
            },
        )
        # Omitting nursery_source must not clear it.
        r = await tenant.put(url, json={"attributes": {"establishment_method": "seed"}})
        assert r.json()["values"]["nursery_source"] == "Nubaria Nursery Co."

        # Re-saving identical values adds no history noise.
        history = await tenant.get(f"{url}/history", params={"code": "establishment_method"})
        assert [h["change_kind"] for h in history.json()] == ["set"]

        # An explicit null clears.
        r = await tenant.put(url, json={"attributes": {"nursery_source": None}})
        assert "nursery_source" not in r.json()["values"]
        history = await tenant.get(f"{url}/history", params={"code": "nursery_source"})
        assert [h["change_kind"] for h in history.json()] == ["cleared", "set"]
