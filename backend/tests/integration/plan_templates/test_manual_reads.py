"""Agri Operation PR 2: operation manual reads for farms and authors.

* ``GET /plan-templates/catalog`` lists published manuals only (E4) with their
  activity counts, and needs ``plan_template.read`` on the farm.
* ``GET /plan-templates/{id}/manual`` returns a published manual with its
  stages and the stages per variety it covers (H5); drafts read as 404.
* ``GET /plan-templates/{id}/authoring-view`` returns drafts too, for platform
  authors only.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.plan_templates.router import router as plan_templates_router
from app.modules.plan_templates.schemas import (
    PlanTemplateActivityInput,
    PlanTemplateWriteRequest,
)
from app.modules.plan_templates.service import get_plan_templates_service
from app.shared.auth.context import PlatformRole, TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.plans.test_plans_pipeline import _bootstrap

pytestmark = [pytest.mark.integration]


def _app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(plan_templates_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _template_id(session: AsyncSession, code: str) -> str:
    return str(
        (
            await session.execute(
                text("SELECT id FROM public.plan_templates WHERE code = :c"), {"c": code}
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_farm_catalog_and_manual(admin_session: AsyncSession) -> None:
    tenant, context, farm_id, _ = await _bootstrap(admin_session, "pt-manual-reads")
    svc = get_plan_templates_service(public_session=admin_session)
    draft = await svc.create_template(
        payload=PlanTemplateWriteRequest(
            code="mango-draft-reads",
            name="Draft mango manual",
            crop_path="mango",
            activities=[PlanTemplateActivityInput(activity_type="pruning", anchor="start")],
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    keitt_id = await _template_id(admin_session, "mango-keitt-eg")

    async with AsyncClient(transport=ASGITransport(app=_app(context)), base_url="http://t") as c:
        catalog = await c.get("/api/v1/plan-templates/catalog", params={"farm_id": farm_id})
        assert catalog.status_code == 200, catalog.text
        by_code = {m["code"]: m for m in catalog.json()}
        assert by_code["mango-keitt-eg"]["activity_count"] == 16
        assert "mango-draft-reads" not in by_code  # drafts stay hidden (E4)
        assert all(m["status"] == "published" for m in by_code.values())

        mango_only = await c.get(
            "/api/v1/plan-templates/catalog", params={"farm_id": farm_id, "crop": "mango"}
        )
        assert {m["crop_path"].split(".")[0] for m in mango_only.json()} == {"mango"}

        manual = await c.get(
            f"/api/v1/plan-templates/{keitt_id}/manual", params={"farm_id": farm_id}
        )
        assert manual.status_code == 200, manual.text
        body = manual.json()
        assert body["is_perennial"] is True
        assert {s["code"] for s in body["stages"]} >= {"flowering", "post_harvest_flush"}
        assert len(body["activities"]) == 16
        assert all(a["title"] for a in body["activities"])
        # A variety-level manual covers that variety only.
        assert [v["path"] for v in body["varieties"]] == ["mango.keitt"]

        hidden = await c.get(
            f"/api/v1/plan-templates/{draft['id']}/manual", params={"farm_id": farm_id}
        )
        assert hidden.status_code == 404

        # Farm users cannot use the authoring view.
        authoring = await c.get(f"/api/v1/plan-templates/{draft['id']}/authoring-view")
        assert authoring.status_code == 403

    # Without access to the farm, the catalog is refused.
    outsider = make_context(
        user_id=uuid4(), tenant_id=tenant.tenant_id, tenant_role=TenantRole.BILLING_ADMIN
    )
    async with AsyncClient(transport=ASGITransport(app=_app(outsider)), base_url="http://t") as c:
        refused = await c.get("/api/v1/plan-templates/catalog", params={"farm_id": farm_id})
        assert refused.status_code == 403


@pytest.mark.asyncio
async def test_authoring_view_shows_drafts_and_every_variety(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)
    draft = await svc.create_template(
        payload=PlanTemplateWriteRequest(
            code="mango-draft-authoring",
            name="Crop-level mango manual",
            crop_path="mango",
            activities=[
                PlanTemplateActivityInput(
                    activity_type="fertilizing", anchor="stage", stage_code="flowering"
                )
            ],
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    admin = make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=_app(admin)), base_url="http://t") as c:
        resp = await c.get(f"/api/v1/plan-templates/{draft['id']}/authoring-view")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    paths = [v["path"] for v in body["varieties"]]
    # The crop's own calendar first, then every active mango variety.
    assert paths[0] == "mango"
    assert "mango.keitt" in paths
    assert "mango.zebda" in paths
    stage_start = {
        v["path"]: {s["code"]: s["advance"] for s in v["stages"]} for v in body["varieties"]
    }
    # Keitt runs on its own, later calendar (variety override).
    assert stage_start["mango.keitt"] != stage_start["mango.zebda"]
