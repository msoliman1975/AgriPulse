"""Shared bootstrap for the scouting integration tests.

Builds a real tenant with a farm and a block, then hands back two contexts:
an Agronomist (dispatch + assign) and a **farm-scoped-only Scout**, which is
the persona that matters — a Scout holds no tenant role at all, so these tests
also prove the farm_id_param gating works for the mobile app's actual user.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.iam.router import router as iam_router
from app.modules.scouting.router import router as scouting_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square


def build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(scouting_router)
    # Enrolment is how a scout comes to exist, so the assignee picker
    # tests need both halves mounted on one app.
    app.include_router(iam_router)
    app.add_middleware(StubAuth, context=context)
    return app


class ScoutingFixture:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        schema: str,
        farm_id: str,
        block_id: str,
        admin_context,
        scout_context,
        scout_user_id: UUID,
        agronomist_context,
        agronomist_user_id: UUID,
    ) -> None:
        self.tenant_id = tenant_id
        self.schema = schema
        self.farm_id = farm_id
        self.block_id = block_id
        self.admin_context = admin_context
        self.scout_context = scout_context
        self.scout_user_id = scout_user_id
        self.agronomist_context = agronomist_context
        self.agronomist_user_id = agronomist_user_id


@pytest.fixture
async def scouting_env(admin_session: AsyncSession) -> ScoutingFixture:
    slug = f"scout-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"Scouting {slug}", contact_email=f"ops@{slug}.test"
    )
    admin_user = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=admin_user)
    admin_context = make_context(
        user_id=admin_user, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )

    app = build_app(admin_context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm = await client.post(
            "/api/v1/farms",
            json={
                "code": "SC-FARM",
                "name": "Scouting farm",
                "boundary": _square(31.60, 30.60),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]
        block = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "SB1", "boundary": _polygon(31.61, 30.61)},
        )
        assert block.status_code == 201, block.text
        block_id = block.json()["id"]

    scout_user = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=scout_user)
    agro_user = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=agro_user)

    scope = (FarmScope(farm_id=UUID(farm_id), role=FarmRole.SCOUT),)
    agro_scope = (FarmScope(farm_id=UUID(farm_id), role=FarmRole.AGRONOMIST),)
    return ScoutingFixture(
        tenant_id=tenant.tenant_id,
        schema=tenant.schema_name,
        farm_id=farm_id,
        block_id=block_id,
        admin_context=admin_context,
        # No tenant_role at all — a Scout is farm-scoped only.
        scout_context=make_context(
            user_id=scout_user, tenant_id=tenant.tenant_id, farm_scopes=scope
        ),
        scout_user_id=scout_user,
        agronomist_context=make_context(
            user_id=agro_user, tenant_id=tenant.tenant_id, farm_scopes=agro_scope
        ),
        agronomist_user_id=agro_user,
    )
