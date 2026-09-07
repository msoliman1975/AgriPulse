"""The three verdict reads, over HTTP.

What the endpoints add on top of the SQL is worth its own test: the farm read
groups by block and computes each block's single status, the block read
replays a date, and the status catalog has to be reachable by a farm-scoped
caller — the audience that would otherwise get a silent 403 on a request that
looks correct.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.recommendations.router import router as recommendations_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _build_app(context: Any) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(recommendations_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, Any, str, list[str]]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"Verdicts {slug}", contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = _build_app(context)
    block_ids: list[str] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm = await client.post(
            "/api/v1/farms",
            json={
                "code": "VD-FARM",
                "name": "Verdict farm",
                "boundary": _square(31.60, 30.60),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]
        for i, offset in enumerate((0.01, 0.02)):
            block = await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": f"B{i + 1}", "boundary": _polygon(31.60 + offset, 30.60 + offset)},
            )
            assert block.status_code == 201, block.text
            block_ids.append(block.json()["id"])
    return tenant, context, farm_id, block_ids


async def _insert_verdict(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    block_id: str,
    tree_code: str,
    status_code: str,
    valid_from: datetime,
    valid_to: datetime | None = None,
) -> None:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            """
            INSERT INTO decision_tree_block_verdicts (
                farm_id, block_id, cell_id, scope, tree_id, tree_code,
                tree_version, leaf_node_id, kind, status_code, severity,
                text_en, valid_from, valid_to, last_evaluated_at
            ) VALUES (
                :farm_id, :block_id, NULL, 'block', gen_random_uuid(), :tree_code,
                1, 'leaf_ok', 'status', :status_code, NULL,
                'Checked and fine.', :valid_from, :valid_to, :valid_from
            )
            """
        ),
        {
            "farm_id": farm_id,
            "block_id": block_id,
            "tree_code": tree_code,
            "status_code": status_code,
            "valid_from": valid_from,
            "valid_to": valid_to,
        },
    )
    await session.commit()


@pytest.mark.asyncio
async def test_the_status_catalog_is_the_five_platform_codes(
    admin_session: AsyncSession,
) -> None:
    _, context, _, _ = await _bootstrap(admin_session, f"vs-{uuid4().hex[:8]}")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/verdict-statuses")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [entry["code"] for entry in body] == ["na", "very_good", "good", "issue", "alert"]
    # The colours are what the map paints; shipping them in the frontend
    # bundle is how a copy of a backend list drifts.
    assert all(entry["color"].startswith("#") for entry in body)
    assert all(entry["label_ar"] for entry in body)


@pytest.mark.asyncio
async def test_a_block_reports_its_verdicts_and_the_worst_of_them(
    admin_session: AsyncSession,
) -> None:
    tenant, context, farm_id, block_ids = await _bootstrap(admin_session, f"vb-{uuid4().hex[:8]}")
    at = datetime.now(UTC) - timedelta(days=1)
    for tree_code, status_code in (("salinity_v1", "good"), ("pest_v1", "issue")):
        await _insert_verdict(
            admin_session,
            schema=str(tenant.schema_name),
            farm_id=farm_id,
            block_id=block_ids[0],
            tree_code=tree_code,
            status_code=status_code,
            valid_from=at,
        )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{block_ids[0]}/verdicts", params={"farm_id": farm_id}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["worst_status"] == "issue"
    assert {v["tree_code"] for v in body["verdicts"]} == {"salinity_v1", "pest_v1"}
    assert body["as_of"] is None


@pytest.mark.asyncio
async def test_a_block_no_tree_has_run_on_reports_no_status(
    admin_session: AsyncSession,
) -> None:
    """Not `na`, and not an error. Nothing has looked at it."""
    _, context, farm_id, block_ids = await _bootstrap(admin_session, f"vn-{uuid4().hex[:8]}")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{block_ids[1]}/verdicts", params={"farm_id": farm_id}
        )

    assert response.status_code == 200, response.text
    assert response.json()["worst_status"] is None
    assert response.json()["verdicts"] == []


@pytest.mark.asyncio
async def test_the_block_read_replays_a_date(admin_session: AsyncSession) -> None:
    tenant, context, farm_id, block_ids = await _bootstrap(admin_session, f"vr-{uuid4().hex[:8]}")
    schema = str(tenant.schema_name)
    three_days = datetime.now(UTC) - timedelta(days=3)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await _insert_verdict(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_ids[0],
        tree_code="salinity_v1",
        status_code="good",
        valid_from=three_days,
        valid_to=yesterday,
    )
    await _insert_verdict(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_ids[0],
        tree_code="salinity_v1",
        status_code="issue",
        valid_from=yesterday,
    )
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        now = await client.get(
            f"/api/v1/blocks/{block_ids[0]}/verdicts", params={"farm_id": farm_id}
        )
        replay = await client.get(
            f"/api/v1/blocks/{block_ids[0]}/verdicts",
            params={"farm_id": farm_id, "at": two_days_ago.isoformat()},
        )

    assert now.json()["worst_status"] == "issue"
    assert replay.json()["worst_status"] == "good"


@pytest.mark.asyncio
async def test_an_instant_with_no_offset_is_accepted(admin_session: AsyncSession) -> None:
    """`?at=2026-09-01T00:00`.

    A naive datetime subtracted from a timestamptz raises TypeError, so this
    would be a 500 rather than a reading.
    """
    tenant, context, farm_id, block_ids = await _bootstrap(admin_session, f"vt-{uuid4().hex[:8]}")
    await _insert_verdict(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_ids[0],
        tree_code="salinity_v1",
        status_code="good",
        valid_from=datetime.now(UTC) - timedelta(days=2),
    )
    naive = (datetime.now(UTC) - timedelta(days=1)).replace(tzinfo=None).isoformat()
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{block_ids[0]}/verdicts",
            params={"farm_id": farm_id, "at": naive},
        )

    assert response.status_code == 200, response.text
    assert response.json()["worst_status"] == "good"
    # Echoed exactly as sent, with no offset bolted on.
    assert response.json()["as_of"] == naive


@pytest.mark.asyncio
async def test_the_farm_read_groups_every_block(admin_session: AsyncSession) -> None:
    tenant, context, farm_id, block_ids = await _bootstrap(admin_session, f"vf-{uuid4().hex[:8]}")
    schema = str(tenant.schema_name)
    at = datetime.now(UTC) - timedelta(days=1)
    await _insert_verdict(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_ids[0],
        tree_code="salinity_v1",
        status_code="very_good",
        valid_from=at,
    )
    await _insert_verdict(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_ids[1],
        tree_code="pest_v1",
        status_code="alert",
        valid_from=at,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/farms/{farm_id}/verdicts")

    assert response.status_code == 200, response.text
    body = response.json()
    by_block = {b["block_id"]: b["worst_status"] for b in body["blocks"]}
    assert by_block == {block_ids[0]: "very_good", block_ids[1]: "alert"}
