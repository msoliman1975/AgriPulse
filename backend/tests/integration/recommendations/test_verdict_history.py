"""One read for a whole replay window.

`/farms/{id}/verdicts?at=` answers one instant. A day-by-day replay over a
year would call it 365 times for a farm whose answers change a handful of
times. `/farms/{id}/verdict-history` returns the intervals themselves, once,
and the client rebuilds each frame from them.

The tests that matter are about which rows the window admits, because an
overlap test is easy to write backwards, and because getting it wrong makes
a replay quietly miss days rather than fail.
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

NOW = datetime.now(UTC)
WINDOW_FROM = NOW - timedelta(days=30)
WINDOW_TO = NOW


def _build_app(context: Any) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(recommendations_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, Any, str, str]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"History {slug}", contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm = await client.post(
            "/api/v1/farms",
            json={
                "code": "HS-FARM",
                "name": "History farm",
                "boundary": _square(31.80, 30.80),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]
        block = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.81, 30.81)},
        )
        assert block.status_code == 201, block.text
    return tenant, context, farm_id, block.json()["id"]


async def _insert(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    block_id: str,
    tree_code: str,
    status_code: str,
    valid_from: datetime,
    valid_to: datetime | None,
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
                'Checked.', :valid_from, :valid_to, :valid_from
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


async def _history(context: Any, farm_id: str, **params: Any) -> Any:
    app = _build_app(context)
    query = {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat(), **params}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(f"/api/v1/farms/{farm_id}/verdict-history", params=query)


@pytest.mark.asyncio
async def test_a_run_of_changes_returns_one_row_each_not_one_per_day(
    admin_session: AsyncSession,
) -> None:
    """Three changes in a month is three rows, whatever the range asked for.

    This is the whole reason the endpoint exists. A read that returned a row
    per day would put 365 times the payload on a year of replay.
    """
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"hr-{uuid4().hex[:8]}")
    schema = str(tenant.schema_name)
    starts = [NOW - timedelta(days=20), NOW - timedelta(days=12), NOW - timedelta(days=4)]
    for i, start in enumerate(starts):
        await _insert(
            admin_session,
            schema=schema,
            farm_id=farm_id,
            block_id=block_id,
            tree_code="cwsi_v1",
            status_code=("good", "issue", "alert")[i],
            valid_from=start,
            valid_to=starts[i + 1] if i + 1 < len(starts) else None,
        )

    response = await _history(context, farm_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is False
    assert [v["status_code"] for v in body["verdicts"]] == ["good", "issue", "alert"]
    # The open one is the current answer and carries a null end.
    assert body["verdicts"][-1]["valid_to"] is None


@pytest.mark.asyncio
async def test_the_window_admits_a_row_that_started_before_it(
    admin_session: AsyncSession,
) -> None:
    """A verdict opened last year and still open is the answer for every day
    of the window. Excluding it would leave the map blank for the whole
    replay, which is the failure this test exists to catch."""
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"hb-{uuid4().hex[:8]}")
    await _insert(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_id,
        tree_code="salinity_v1",
        status_code="very_good",
        valid_from=NOW - timedelta(days=400),
        valid_to=None,
    )

    response = await _history(context, farm_id)

    assert response.status_code == 200, response.text
    assert [v["status_code"] for v in response.json()["verdicts"]] == ["very_good"]


@pytest.mark.asyncio
async def test_a_row_that_closed_before_the_window_is_left_out(
    admin_session: AsyncSession,
) -> None:
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"hc-{uuid4().hex[:8]}")
    schema = str(tenant.schema_name)
    await _insert(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_id,
        tree_code="old_v1",
        status_code="alert",
        valid_from=NOW - timedelta(days=90),
        valid_to=NOW - timedelta(days=60),
    )
    await _insert(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        block_id=block_id,
        tree_code="new_v1",
        status_code="good",
        valid_from=NOW - timedelta(days=10),
        valid_to=None,
    )

    response = await _history(context, farm_id)

    assert response.status_code == 200, response.text
    assert [v["tree_code"] for v in response.json()["verdicts"]] == ["new_v1"]


@pytest.mark.asyncio
async def test_naming_a_tree_returns_only_that_tree(admin_session: AsyncSession) -> None:
    """The screen shows one tree at a time. Filtering here rather than in the
    client is what keeps a year inside one response."""
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"ht-{uuid4().hex[:8]}")
    schema = str(tenant.schema_name)
    for code in ("cwsi_v1", "ndvi_v1"):
        await _insert(
            admin_session,
            schema=schema,
            farm_id=farm_id,
            block_id=block_id,
            tree_code=code,
            status_code="good",
            valid_from=NOW - timedelta(days=5),
            valid_to=None,
        )

    response = await _history(context, farm_id, tree_code="ndvi_v1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tree_code"] == "ndvi_v1"
    assert [v["tree_code"] for v in body["verdicts"]] == ["ndvi_v1"]


@pytest.mark.asyncio
async def test_an_end_before_the_start_is_refused(admin_session: AsyncSession) -> None:
    """A backwards window returns nothing from the SQL, which reads the same
    as a farm with no history. Refusing it says which of the two happened."""
    _, context, farm_id, _ = await _bootstrap(admin_session, f"hw-{uuid4().hex[:8]}")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/farms/{farm_id}/verdict-history",
            params={"from": WINDOW_TO.isoformat(), "to": WINDOW_FROM.isoformat()},
        )

    assert response.status_code == 422, response.text
