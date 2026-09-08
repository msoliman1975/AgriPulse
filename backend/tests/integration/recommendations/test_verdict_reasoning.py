"""From a verdict to the walk that produced it.

The Farm Health View colours a cell from a verdict and then has to answer
"why". The trace endpoints already hold that answer, but they are gated on
``decision_tree.read``, which FarmManager, Agronomist, FieldOperator, Scout
and Viewer do not hold. Every reader of the map would get a silent 403 on the
one request that explains the colour, so the walk gets a second door gated
the way the verdict reads are.

These tests cover the three states that door can be in: the walk is there,
the walk has been pruned by retention, and there is no such verdict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

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

NODE_PATH = [
    {
        "node_id": "saturation",
        "matched": False,
        "label_en": "Is CWSI clipped at the index ceiling?",
        "condition": {"op": "ge", "left": "indices.cwsi.mean", "right": "0.99"},
        "values": {"indices.cwsi.mean": "0.47"},
    },
    {
        "node_id": "medium_check",
        "matched": True,
        "label_en": "Is CWSI above the medium-tree bound?",
        "condition": {"op": "gt", "left": "indices.cwsi.mean", "right": "0.30"},
        "values": {"indices.cwsi.mean": "0.47"},
    },
]
RESOLVED = {"indices.cwsi.mean": "0.47"}


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
        slug=slug, name=f"Reasoning {slug}", contact_email=f"ops@{slug}.test"
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
                "code": "RS-FARM",
                "name": "Reasoning farm",
                "boundary": _square(31.70, 30.70),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]
        block = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.71, 30.71)},
        )
        assert block.status_code == 201, block.text
    return tenant, context, farm_id, block.json()["id"]


async def _seed(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    block_id: str,
    with_trace: bool,
) -> str:
    """One verdict, optionally with the run and trace behind it.

    The tree id is shared between the verdict and the trace on purpose: the
    join is on run, block, cell and tree, and a test that let them differ
    would pass while the join was wrong.
    """
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    tree_id = uuid4()
    at = datetime.now(UTC) - timedelta(hours=2)
    run_id: UUID | None = None

    if with_trace:
        run_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO decision_tree_eval_runs (id, kind, started_at, finished_at)
                VALUES (:run_id, 'sweep', :at, :at)
                """
            ),
            {"run_id": run_id, "at": at},
        )
        await session.execute(
            text(
                """
                INSERT INTO decision_tree_eval_traces (
                    run_id, evaluated_at, farm_id, block_id, cell_id,
                    tree_id, tree_code, tree_version, scope, status,
                    node_path, resolved_values
                ) VALUES (
                    :run_id, :at, :farm_id, :block_id, NULL,
                    :tree_id, 't_cwsi_irrigation_stress', 1, 'block', 'fired',
                    CAST(:node_path AS jsonb), CAST(:resolved AS jsonb)
                )
                """
            ),
            {
                "run_id": run_id,
                "at": at,
                "farm_id": farm_id,
                "block_id": block_id,
                "tree_id": tree_id,
                "node_path": json.dumps(NODE_PATH),
                "resolved": json.dumps(RESOLVED),
            },
        )

    verdict_id = (
        await session.execute(
            text(
                """
                INSERT INTO decision_tree_block_verdicts (
                    farm_id, block_id, cell_id, scope, tree_id, tree_code,
                    tree_version, leaf_node_id, kind, status_code, severity,
                    text_en, run_id, last_run_id, valid_from, last_evaluated_at
                ) VALUES (
                    :farm_id, :block_id, NULL, 'block', :tree_id,
                    't_cwsi_irrigation_stress', 1, 'leaf_above', 'recommendation',
                    'issue', 'warning', 'Add one irrigation set.',
                    :run_id, :run_id, :at, :at
                )
                RETURNING id
                """
            ),
            {
                "farm_id": farm_id,
                "block_id": block_id,
                "tree_id": tree_id,
                "run_id": run_id,
                "at": at,
            },
        )
    ).scalar_one()
    await session.commit()
    return str(verdict_id)


@pytest.mark.asyncio
async def test_a_verdict_carries_the_run_that_produced_it(admin_session: AsyncSession) -> None:
    """Without `last_run_id` on the response there is no way back to the walk.

    The column has existed since migration 0091; it was the SELECT that
    never returned it.
    """
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"rr-{uuid4().hex[:8]}")
    verdict_id = await _seed(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_id,
        with_trace=True,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        block_read = await client.get(
            f"/api/v1/blocks/{block_id}/verdicts", params={"farm_id": farm_id}
        )
        farm_read = await client.get(f"/api/v1/farms/{farm_id}/verdicts")

    assert block_read.status_code == 200, block_read.text
    verdict = block_read.json()["verdicts"][0]
    assert verdict["id"] == verdict_id
    assert verdict["last_run_id"] is not None

    # The farm read paints the map, so it needs the same field.
    assert farm_read.status_code == 200, farm_read.text
    assert farm_read.json()["blocks"][0]["verdicts"][0]["last_run_id"] == verdict["last_run_id"]


@pytest.mark.asyncio
async def test_the_reasoning_read_returns_the_node_walk(admin_session: AsyncSession) -> None:
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"rw-{uuid4().hex[:8]}")
    verdict_id = await _seed(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_id,
        with_trace=True,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{block_id}/verdicts/{verdict_id}/reasoning",
            params={"farm_id": farm_id},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reasoning_available"] is True
    assert body["leaf_node_id"] == "leaf_above"
    assert body["status_code"] == "issue"
    # The walk arrives in order, and the values with it. Both are what the
    # screen renders as the steps.
    assert [step["node_id"] for step in body["node_path"]] == ["saturation", "medium_check"]
    assert [step["matched"] for step in body["node_path"]] == [False, True]
    assert body["resolved_values"] == RESOLVED


@pytest.mark.asyncio
async def test_a_pruned_run_leaves_the_verdict_readable(admin_session: AsyncSession) -> None:
    """Retention deletes runs. The verdict outlives its walk, and says so.

    An inner join here would answer 404, which reads as "no such verdict"
    and is a different, wrong sentence.
    """
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"rp-{uuid4().hex[:8]}")
    verdict_id = await _seed(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_id,
        with_trace=False,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{block_id}/verdicts/{verdict_id}/reasoning",
            params={"farm_id": farm_id},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reasoning_available"] is False
    assert body["node_path"] == []
    assert body["resolved_values"] == {}
    # The verdict itself is still fully readable.
    assert body["status_code"] == "issue"
    assert body["tree_code"] == "t_cwsi_irrigation_stress"


@pytest.mark.asyncio
async def test_a_verdict_id_from_another_block_does_not_resolve(
    admin_session: AsyncSession,
) -> None:
    """The block is part of the key, not a filter applied after the fact.

    The route is authorized against the block's farm, so a verdict id
    belonging elsewhere must not resolve because the caller guessed it.
    """
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, f"rx-{uuid4().hex[:8]}")
    verdict_id = await _seed(
        admin_session,
        schema=str(tenant.schema_name),
        farm_id=farm_id,
        block_id=block_id,
        with_trace=True,
    )
    app = _build_app(context)
    other_block = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/blocks/{other_block}/verdicts/{verdict_id}/reasoning",
            params={"farm_id": farm_id},
        )

    assert response.status_code == 404, response.text
