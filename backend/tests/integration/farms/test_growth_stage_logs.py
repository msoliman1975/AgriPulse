"""Integration tests for growth_stage_logs (PR-3).

Covers the migration shape, the POST/GET endpoint round-trip, the
mirror-onto-block_crops side effect, and the RBAC denial path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole

from .conftest import build_app, make_context
from .test_blocks_unit_type import _create_farm, _polygon
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _bootstrap_with_block(
    admin_session: AsyncSession, slug: str
) -> tuple[object, object, str, str]:
    """Create tenant + admin user + farm + a single block. Return
    (tenant, request_context, farm_id, block_id)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"PR-3 {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client, code="FARM-PR3")
        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-PR3", "boundary": _polygon(31.21, 30.11)},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
    return tenant, context, farm_id, block_id


async def _seed_crop_assignment(
    admin_session: AsyncSession, *, schema_name: str, block_id: str
) -> str:
    """Insert a current crop assignment directly via SQL.

    There's no /crop-assignments POST route shape that lets us specify
    growth_stage today (assign_block_crop accepts only the metadata
    fields). For the timeline tests we just need a row with
    is_current=TRUE so record_growth_stage_transition can mirror onto it.
    """
    # Pick any active crop from the catalog.
    crop_id = (
        await admin_session.execute(
            text("SELECT id FROM public.crops WHERE is_active = TRUE LIMIT 1")
        )
    ).scalar_one()

    assignment_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO block_crops "
            "(id, block_id, crop_id, season_label, is_current, status) "
            "VALUES (:aid, :bid, :cid, '2026-summer', TRUE, 'growing')"
        ).bindparams(
            bindparam("aid", type_=PG_UUID(as_uuid=True)),
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("cid", type_=PG_UUID(as_uuid=True)),
        ),
        {"aid": assignment_id, "bid": UUID(block_id), "cid": crop_id},
    )
    await admin_session.commit()
    return str(assignment_id)


# ---------------------------------------------------------------------------
# Schema check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_stage_logs_table_exists(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr3-schema",
        name="PR-3 Schema",
        contact_email="ops@pr3-schema.test",
    )
    rows = (
        await admin_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'growth_stage_logs'"
            ),
            {"s": tenant.schema_name},
        )
    ).all()
    cols = {r[0] for r in rows}
    expected = {
        "id",
        "block_id",
        "block_crop_id",
        "stage",
        "source",
        "confirmed_by",
        "transition_date",
        "notes",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_at",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"


# ---------------------------------------------------------------------------
# Endpoint round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_growth_stage_appends_log_and_mirrors(
    admin_session: AsyncSession,
) -> None:
    tenant, context, _farm_id, block_id = await _bootstrap_with_block(admin_session, "pr3-record")
    assignment_id = await _seed_crop_assignment(
        admin_session, schema_name=tenant.schema_name, block_id=block_id
    )

    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        when = datetime.now(UTC).replace(microsecond=0)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/growth-stages",
            json={
                "stage": "vegetative",
                "source": "manual",
                "transition_date": when.isoformat(),
                "notes": "first observation",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stage"] == "vegetative"
    assert body["source"] == "manual"
    assert body["block_crop_id"] == assignment_id
    assert body["confirmed_by"] is not None  # service stamps actor for manual

    # The block_crops mirror.
    bc_row = (
        await admin_session.execute(
            text(
                f'SELECT growth_stage, growth_stage_updated_at FROM "{tenant.schema_name}".'
                "block_crops WHERE id = :id"
            ),
            {"id": UUID(assignment_id)},
        )
    ).one()
    assert bc_row.growth_stage == "vegetative"
    assert bc_row.growth_stage_updated_at is not None


@pytest.mark.asyncio
async def test_list_growth_stages_returns_descending_timeline(
    admin_session: AsyncSession,
) -> None:
    tenant, context, _farm_id, block_id = await _bootstrap_with_block(admin_session, "pr3-timeline")
    await _seed_crop_assignment(admin_session, schema_name=tenant.schema_name, block_id=block_id)

    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Three transitions, oldest first (so the GET should reverse them).
        base = datetime.now(UTC).replace(microsecond=0) - timedelta(days=10)
        for offset, stage in enumerate(("vegetative", "flowering", "fruit_set")):
            resp = await client.post(
                f"/api/v1/blocks/{block_id}/growth-stages",
                json={
                    "stage": stage,
                    "source": "manual",
                    "transition_date": (base + timedelta(days=offset)).isoformat(),
                },
            )
            assert resp.status_code == 201, resp.text

        listed = await client.get(f"/api/v1/blocks/{block_id}/growth-stages")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 3
    # Newest first.
    assert [r["stage"] for r in rows] == ["fruit_set", "flowering", "vegetative"]


@pytest.mark.asyncio
async def test_record_growth_stage_without_current_assignment(
    admin_session: AsyncSession,
) -> None:
    """Block without a current crop still gets a log row, but block_crops
    isn't touched."""
    tenant, context, _farm_id, block_id = await _bootstrap_with_block(
        admin_session, "pr3-no-assign"
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/growth-stages",
            json={"stage": "vegetative", "source": "manual"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["block_crop_id"] is None

    # Direct check that no block_crops row exists for this block.
    count = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{tenant.schema_name}".block_crops ' "WHERE block_id = :bid"
            ),
            {"bid": UUID(block_id)},
        )
    ).scalar_one()
    assert count == 0


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_growth_stage_denied_for_viewer(admin_session: AsyncSession) -> None:
    """Viewer can read the timeline but cannot record a transition."""
    tenant, _admin_ctx, farm_id, block_id = await _bootstrap_with_block(admin_session, "pr3-rbac")

    viewer_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=viewer_id)
    viewer_ctx = make_context(
        user_id=viewer_id,
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.VIEWER),),
    )
    app = build_app(viewer_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post_resp = await client.post(
            f"/api/v1/blocks/{block_id}/growth-stages",
            json={"stage": "vegetative", "source": "manual"},
        )
        get_resp = await client.get(f"/api/v1/blocks/{block_id}/growth-stages")

    # Surface as 404 rather than 403 to avoid leaking block existence —
    # matches the imagery / weather pattern.
    assert post_resp.status_code == 404, post_resp.text
    assert get_resp.status_code == 200, get_resp.text


@pytest.mark.asyncio
async def test_invalid_source_rejected_by_pydantic(admin_session: AsyncSession) -> None:
    _tenant, context, _farm_id, block_id = await _bootstrap_with_block(
        admin_session, "pr3-bad-source"
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/growth-stages",
            json={"stage": "vegetative", "source": "guess"},
        )
    assert resp.status_code == 422, resp.text
